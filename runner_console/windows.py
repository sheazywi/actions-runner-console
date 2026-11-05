from .common import *
import platform

def cpu():
    idle=ctypes.c_ulonglong();kernel=ctypes.c_ulonglong();user=ctypes.c_ulonglong()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle),ctypes.byref(kernel),ctypes.byref(user)):raise ctypes.WinError()
    return kernel.value+user.value,idle.value

class Memory(ctypes.Structure):
    _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(x,ctypes.c_ulonglong) for x in ('total','available','page_total','page_available','virtual_total','virtual_available','extended')]

def memory():
    result=Memory();result.length=ctypes.sizeof(result)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(result)):raise ctypes.WinError()
    return result.total-result.available,result.total

def human(value):return f'{value/1024**3:.1f} GB'

def display():
    import msvcrt
    kernel=ctypes.windll.kernel32
    handle=kernel.GetStdHandle(-11);mode=ctypes.c_ulong()
    if not kernel.GetConsoleMode(handle,ctypes.byref(mode)):raise ctypes.WinError()
    kernel.SetConsoleMode(handle,mode.value|4)
    kernel.SetConsoleTitleW(TITLE)
    os.system('mode con cols=125 lines=42 >nul')
    window=kernel.GetConsoleWindow()
    if window:ctypes.windll.user32.ShowWindow(window,3)
    mode_name='overview';scroll=0;previous=cpu();percent=0;sample=0;last_state={};read_error=''
    print('\x1b[?25l\x1b[2J',end='',flush=True)
    try:
        while True:
            if msvcrt.kbhit():
                key=msvcrt.getwch().lower()
                if key in ('\x00','\xe0'):
                    key=msvcrt.getwch();scroll=max(0,scroll+({'H':1,'P':-1,'I':10,'Q':-10}.get(key,0)))
                elif key in ('o','s','l'):mode_name={'o':'overview','s':'steps','l':'logs'}[key];scroll=0
                elif key=='f':scroll=0
                elif key=='q':return
            if time.monotonic()-sample>=1:
                current=cpu();delta=current[0]-previous[0]
                percent=100*(1-(current[1]-previous[1])/delta) if delta else 0
                previous=current;sample=time.monotonic()
            try:
                state=read_json('status.json');last_state=state;read_error=''
            except (OSError,ValueError) as exc:
                state=last_state;read_error='Status read failed: '+str(exc)
            job=state.get('job',{});used,total=memory();disk=shutil.disk_usage('C:\\')
            width,height=shutil.get_terminal_size((125,42));rows=[]
            def row(text='',color='37',bold=False):
                rows.append('\x1b[2K\x1b['+('1;' if bold else '')+color+'m'+clean(text)[:max(1,width-1)]+'\x1b[0m')
            def bar(value):
                n=round(min(100,max(0,value))/5)
                return '['+'#'*n+'-'*(20-n)+']'
            status=state.get('status','STARTING');color='33' if status=='BUILDING' else '32' if status=='READY' else '31'
            row('  '+TITLE.upper()+'   /   WINDOWS                      '+datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M:%S UTC'),'36',True)
            row('  '+'='*max(1,width-5),'36')
            if mode_name!='logs':
                row(f'  {socket.gethostname()}  |  {platform.system()} {platform.release()}  |  {os.cpu_count()} vCPU')
                row(f'  CPU  {bar(percent)} {percent:5.1f}%','32')
                row(f'  RAM  {bar(100*used/total)} {human(used)} / {human(total)}','33')
                row(f'  SSD  {human(disk.used)} used / {human(disk.total)}  |  runner volume')
            age=time.time()-state.get('updated',0)
            row(f'  RUNNER: {status}   Listener: {state.get("service","starting")}' + ('  [TELEMETRY STALE]' if age>5 else ''),color,True)
            row()
            if job:
                row(f'  Workflow: {job.get("workflow","-")}  /  Job: {job.get("job","-")}','36')
                row(f'  Branch: {job.get("ref_name","-")}  Commit: {job.get("sha","")[:8]}  Run: {job.get("run_id","-")}')
                elapsed=max(0,int((time.time() if job.get('status')=='started' else job.get('updated',0))-job.get('started',time.time())))
                result=job.get('result','running' if job.get('status')=='started' else 'pending')
                row(f'  Duration: {elapsed//60:02d}:{elapsed%60:02d}  |  Steps observed: {len(state.get("steps",[]))}  |  Result: {result}')
                row(f'  {"CURRENT" if job.get("status")=="started" else "LAST"} STEP: {state.get("step","waiting")}','33',True)
            else:row('  Ready for work. Waiting for the first GitHub Actions job.')
            row()
            if mode_name=='steps':
                row('  JOB STEPS  /  chronological; actual output contains step results','36',True)
                entries=[f'  {step["time"]}  {">>" if step["state"]=="running" and job.get("status")=="started" else "--"}  {step["name"]}' for step in state.get('steps',[])]
            else:
                row('  '+('LIVE JOB OUTPUT' if not scroll else 'JOB OUTPUT / SCROLLED')+'  [GitHub-masked log stream]','36',True)
                entries=tail(BASE/'live.log',300000)[-2000:]
                if not entries:entries=state.get('events',[])[-8:]+['','Waiting for job output.']
            visible=max(1,height-len(rows)-3);scroll=min(scroll,max(0,len(entries)-visible));end=max(0,len(entries)-scroll)
            for entry in entries[max(0,end-visible):end]:row('  '+entry,'31' if '##[error]' in entry else '37')
            while len(rows)<height-2:row()
            row('  '+('Collector error: '+state['error'] if state.get('error') else read_error if read_error else '-'*max(1,width-5)),'31' if state.get('error') or read_error else '36')
            row('  O overview   S steps   L logs   Arrows/PgUp/PgDn scroll   F follow   Q console','36')
            sys.stdout.write('\x1b[H'+'\n'.join(rows[:height]));sys.stdout.flush();time.sleep(.5)
    finally:print('\x1b[0m\x1b[?25h\x1b[2J\x1b[H',end='',flush=True)

