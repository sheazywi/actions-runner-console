from .common import *
import curses

def cpu():
    fields = list(map(int,pathlib.Path('/proc/stat').read_text().splitlines()[0].split()[1:]))
    return sum(fields),fields[3]+(fields[4] if len(fields)>4 else 0)

def memory():
    values = {line.split(':')[0]:int(line.split()[1])*1024 for line in pathlib.Path('/proc/meminfo').read_text().splitlines()}
    return values['MemTotal']-values['MemAvailable'],values['MemTotal']

def human(size):return f'{size/1024**3:.1f} GB'

def display(screen):
    curses.curs_set(0);screen.nodelay(True);screen.timeout(500)
    curses.start_color();curses.use_default_colors()
    for i,color in enumerate([curses.COLOR_CYAN,curses.COLOR_GREEN,curses.COLOR_YELLOW,curses.COLOR_RED,curses.COLOR_WHITE],1):curses.init_pair(i,color,-1)
    mode='overview';scroll=0;previous=cpu();last_percent=0;last_sample=0
    os_name = 'Linux'
    try:
        os_name = re.search(r'^PRETTY_NAME="(.*)"',pathlib.Path('/etc/os-release').read_text(),re.M).group(1)
    except (AttributeError,FileNotFoundError):pass
    while True:
        key = screen.getch()
        if key in (ord('q'),ord('Q')):return
        if key in (ord('l'),ord('L')):mode='logs';scroll=0
        elif key in (ord('s'),ord('S')):mode='steps';scroll=0
        elif key in (ord('o'),ord('O'),27):mode='overview';scroll=0
        elif key in (curses.KEY_UP,curses.KEY_PPAGE):scroll+=1 if key==curses.KEY_UP else 10
        elif key in (curses.KEY_DOWN,curses.KEY_NPAGE):scroll=max(0,scroll-(1 if key==curses.KEY_DOWN else 10))
        elif key in (ord('f'),ord('F'),curses.KEY_END):scroll=0
        if time.monotonic()-last_sample>=1:
            current_cpu=cpu();delta=current_cpu[0]-previous[0]
            last_percent=100*(1-(current_cpu[1]-previous[1])/delta) if delta else 0
            previous=current_cpu;last_sample=time.monotonic()
        state=read_json('status.json');job=state.get('job',{});used,total=memory();disk=shutil.disk_usage(RUNNER)
        height,width=screen.getmaxyx();screen.erase()
        def line(y,text,color=5,bold=False):
            if 0<=y<height:
                try:screen.addnstr(y,0,clean(text),max(0,width-1),curses.color_pair(color)|(curses.A_BOLD if bold else 0))
                except curses.error:pass
        status=state.get('status','STARTING');color=3 if status=='BUILDING' else 2 if status=='READY' else 4
        line(0,f' {TITLE.upper()}  /  LINUX                    {datetime.datetime.now():%H:%M:%S UTC}',1,True)
        line(1,' '+('-'*(width-3)),1)
        def bar(percent):return '['+'#'*round(min(100,max(0,percent))/5)+'-'*(20-round(min(100,max(0,percent))/5))+']'
        age=time.time()-state.get('updated',0)
        if mode == 'logs':
            line(2,f' RUNNER: {status}  |  {socket.gethostname()}  |  full log view',color,True)
            row=4
        else:
            line(2,f' {socket.gethostname()}  |  {os_name}  |  {os.cpu_count()} vCPU',5)
            line(3,f' CPU  {bar(last_percent)} {last_percent:5.1f}%    load {os.getloadavg()[0]:.2f}',2)
            line(4,f' RAM  {bar(100*used/total)} {human(used)} / {human(total)}',3)
            line(5,f' SSD  {human(disk.used)} used / {human(disk.total)}  |  runner volume',5)
            line(6,f' RUNNER: {status}   service: {state.get("service","starting")}'+('  [TELEMETRY STALE]' if age>5 else ''),color,True)
            row=8
        if job:
            line(row,f' Workflow: {job.get("workflow","-")}  /  Job: {job.get("job","-")}',1);row+=1
            line(row,f' Branch: {job.get("ref_name","-")}  Commit: {job.get("sha","")[:8]}  Run: {job.get("run_id","-")}',5);row+=1
            elapsed=int(time.time()-job.get('started',time.time())) if job.get('status')=='started' else int(job.get('updated',0)-job.get('started',0))
            result_text = job.get('result','running' if job.get('status')=='started' else 'pending')
            line(row,f' {"Elapsed" if job.get("status")=="started" else "Last job duration"}: {elapsed//60:02d}:{elapsed%60:02d}  Steps observed: {len(state.get("steps",[]))}  Result: {result_text}',5);row+=1
        else:
            line(row,' Waiting for a GitHub Actions job. No build has run on this runner yet.',5);row+=1
        if state.get('step'):
            line(row,f' {"CURRENT STEP" if job.get("status")=="started" else "LAST STEP"}: {state["step"]}',3,True);row+=1
        row+=1
        if mode=='steps':
            line(row,' JOB STEPS  /  chronological; results are shown in the actual log output',1,True);row+=1
            entries=[f' {s["time"]}  {">>" if s["state"]=="running" and job.get("status")=="started" else "--"} {s["name"]}' for s in state.get('steps',[])]
        else:
            line(row,(' LIVE JOB OUTPUT' if not scroll else ' JOB OUTPUT  /  SCROLLED')+'  [GitHub-masked log stream]',1,True);row+=1
            entries=tail(BASE/'live.log',300000)[-2000:]
            if not entries:entries=state.get('events',[])[-8:]+['','Waiting for job output. Service diagnostics and job logs appear here.']
        visible=max(1,height-row-2);scroll=min(scroll,max(0,len(entries)-visible));end=max(0,len(entries)-scroll)
        for i,text in enumerate(entries[max(0,end-visible):end]):line(row+i,' '+text,4 if '##[error]' in text else 5)
        if state.get('error'):line(height-2,' Collector error: '+state['error'],4)
        line(height-1,' O overview   S steps   L logs   Up/Down/PgUp scroll   F follow   UTC',1)
        screen.refresh()

