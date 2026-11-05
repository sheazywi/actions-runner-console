#!/usr/bin/env python3
"""Local runner telemetry and masked GitHub Actions job-output console."""
import collections, ctypes, datetime, json, logging, logging.handlers, os, pathlib, re, shutil, socket, subprocess, sys, time
BASE = pathlib.Path.home() / '.runner-console'
RUNNER = pathlib.Path.cwd()
DIAG = RUNNER / '_diag'
SERVICE = ''
TITLE = 'Actions Runner Console'

def configure(runner, data, title='Actions Runner Console'):
    global BASE, RUNNER, DIAG, SERVICE, TITLE
    RUNNER = pathlib.Path(runner).resolve()
    BASE = pathlib.Path(data).resolve()
    DIAG = RUNNER / '_diag'
    SERVICE = (RUNNER / '.service').read_text(encoding='utf-8-sig').strip() if (RUNNER / '.service').exists() else ''
    TITLE = title
    BASE.mkdir(parents=True, exist_ok=True)

ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')

def clean(text):
    text = ANSI.sub('', str(text)).replace('\t', '    ')
    return ''.join(c for c in text if c.isprintable())

def io_retry(operation):
    # Retry Windows sharing/access contention; persistent failures stay visible.
    for attempt in range(12):
        try:
            return operation()
        except PermissionError as exc:
            if os.name != 'nt' or getattr(exc, 'winerror', None) not in (None, 5, 32, 33) or attempt == 11:
                raise
            time.sleep(.005*(attempt+1))


def atomic(name, data):
    path = BASE / name
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data), encoding='utf-8')
    io_retry(lambda: os.replace(tmp, path))

def read_json(name):
    def read():
        with open_shared(BASE / name) as f:
            return json.loads(f.read().decode('utf-8'))
    try:
        return io_retry(read)
    except FileNotFoundError:
        return {}


def tail(path, limit=200000):
    try:
        with open_shared(path) as f:
            f.seek(max(0, os.fstat(f.fileno()).st_size-limit))
            return f.read().decode('utf-8', errors='replace').splitlines()
    except FileNotFoundError:
        return []

def newest(pattern):
    paths = list(DIAG.glob(pattern))
    return max(paths, key=lambda p:p.stat().st_mtime) if paths else None

def hook(status):
    data = {k.lower().removeprefix('github_'):os.environ.get(k,'') for k in
            ('GITHUB_WORKFLOW','GITHUB_JOB','GITHUB_RUN_ID','GITHUB_REPOSITORY','GITHUB_REF_NAME','GITHUB_SHA')}
    if status == 'completed':
        old = read_json('job.json')
        if old.get('run_id') == data['run_id']:
            data = old
    data['status'] = status
    data['updated'] = time.time()
    if status == 'started':
        data['started'] = time.time()
    atomic('job.json', data)

def open_shared(path):
    if os.name != 'nt':
        return pathlib.Path(path).open('rb')
    import msvcrt
    kernel = ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p]
    handle = kernel.CreateFileW(str(path),0x80000000,7,None,3,0,None)
    if handle == ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
    return os.fdopen(msvcrt.open_osfhandle(handle,os.O_RDONLY|os.O_BINARY),'rb')

def collect():
    BASE.mkdir(exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(BASE/'live.log', maxBytes=10*1024*1024, backupCount=4, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger = logging.getLogger('job-output');logger.setLevel(logging.INFO);logger.addHandler(handler)
    opened = {}; seen = set(); prefix = None; worker = None; worker_offset = 0; current = ''; steps = []; job_key = None
    next_state = 0; last_error = ''; next_service_check = 0; active = 'unknown'
    try:
        while True:
            try:
                job = read_json('job.json')
                key = (job.get('run_id'), job.get('job'), job.get('started'))
                if job.get('status') == 'started' and key != job_key:
                    job_key = key;steps = [];current = '';prefix = None
                    logger.info('\n=== %s / %s | run %s ===', clean(job.get('workflow','')), clean(job.get('job','')), job.get('run_id',''))
                candidate = newest('Worker_*.log')
                if candidate and candidate != worker:
                    worker = candidate;worker_offset = 0
                if worker:
                    with worker.open('r',encoding='utf-8',errors='replace') as f:
                        f.seek(worker_offset);lines = f.readlines(1024*1024);worker_offset = f.tell()
                    for line in lines:
                        match = re.search(r"Processing step: DisplayName='(.*)'", line)
                        if match:
                            name = clean(match.group(1))
                            if current and steps:
                                steps[-1]['state'] = 'finished'
                            current = name
                            stamp = re.match(r'^\[\d{4}-\d{2}-\d{2} (\d{2}:\d{2}:\d{2})',line)
                            steps.append({'name':name,'state':'running','time':stamp.group(1) if stamp else 'unknown'})
                            steps = steps[-100:]
                pages = sorted((DIAG/'pages').glob('*.log'),key=lambda p:p.stat().st_mtime)
                if prefix is None and pages:
                    available = [p for p in pages if str(p) not in seen]
                    if available:
                        prefix = available[0].name.rsplit('_',1)[0]
                for path in pages:
                    if path.name.rsplit('_',1)[0] == prefix and str(path) not in seen:
                        opened[str(path)] = [open_shared(path),b'']
                        seen.add(str(path))
                for name, value in list(opened.items()):
                    f, pending = value
                    chunk = f.read(256*1024)
                    if chunk:
                        records = (pending+chunk).split(b'\n')
                        value[1] = records.pop()
                        for record in records:
                            logger.info(clean(record.decode('utf-8',errors='replace')))
                    if not pathlib.Path(name).exists() and not chunk:
                        if value[1]:logger.info(clean(value[1].decode('utf-8',errors='replace')))
                        f.close();del opened[name];seen.discard(name)
                if time.monotonic() >= next_state:
                    if time.monotonic() >= next_service_check:
                        from .process import runner_active
                        active = 'active' if runner_active(RUNNER, SERVICE) else 'inactive'
                        next_service_check = time.monotonic()+5
                    listener = newest('Runner_*.log')
                    events = tail(listener,40000) if listener else []
                    if job.get('status') == 'completed':
                        for recent in sorted(DIAG.glob('Runner_*.log'), key=lambda p:p.stat().st_mtime)[-6:]:
                            for event in tail(recent,120000):
                                stamp = re.match(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})',event)
                                if stamp and datetime.datetime.strptime(stamp.group(1),'%Y-%m-%d %H:%M:%S').replace(tzinfo=datetime.timezone.utc).timestamp() >= job.get('started',0):
                                    events.append(event)
                    messages = [clean(line.split('WRITE LINE:',1)[-1].strip()) for line in events if 'WRITE LINE:' in line]
                    status = 'READY' if active == 'active' else 'OFFLINE'
                    if job.get('status') == 'started':status = 'BUILDING'
                    if any('Job completed' in m for m in messages[-2:]) and job.get('status') == 'completed':status = 'READY'
                    if job.get('status') == 'completed':
                        if steps:steps[-1]['state'] = 'finished'
                        for message in reversed(messages):
                            result = re.search(r'Job .* completed with result: (\w+)', message)
                            if result:
                                job['result'] = result.group(1)
                                break
                    atomic('status.json',{'updated':time.time(),'service':active,'status':status,'job':job,'step':current,'steps':steps,'events':messages[-15:],'error':last_error})
                    next_state = time.monotonic()+1
                last_error = ''
            except KeyboardInterrupt:
                return
            except Exception as exc:
                last_error = f'{type(exc).__name__}: {exc}'
                print(last_error,file=sys.stderr,flush=True)
                atomic('collector-error.json',{'error':last_error,'updated':time.time()})
                time.sleep(1)
            time.sleep(.1)
    finally:
        for f, pending in opened.values():
            f.close()
        handler.close()
        logger.removeHandler(handler)
