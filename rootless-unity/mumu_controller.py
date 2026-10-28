"""GUI controller: independent processes; failure of one does not stop siblings."""
from dataclasses import asdict
import json
import os
import queue
from pathlib import Path
import subprocess
import sys
import threading
import time
from mumu_common import port,parse,MumuError


def command():
    if getattr(sys,'frozen',False):
        worker=Path(sys.executable).resolve().parent/'DvkMumuWorker.exe'
        if not worker.is_file():raise MumuError('Распакуй весь архив: отсутствует DvkMumuWorker.exe.')
        return [str(worker),'--mumu-worker']
    return [sys.executable,str(Path(__file__).with_name('mumu_worker.py')),'--mumu-worker']


def run_one(value,settings,mode,fresh,stopped,progress,*,popen=subprocess.Popen,control=None):
    n=port(value)
    spec=dict(port=n,settings=asdict(settings),mode=mode,fresh=fresh)
    options=dict(stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                 creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    process=popen(command(),**options)
    ended=threading.Event()
    outcome=['Рабочий процесс завершился без отчёта.']
    def send_command(text):
        process.stdin.write(text.encode('ascii')+b'\n');process.stdin.flush()
    def cancel():
        while not ended.wait(.1):
            if stopped.is_set():
                try:
                    send_command('stop')
                except (OSError,ValueError):pass
                # No restart/replay. A committed unknown reservation stays held.
                if not ended.wait(45):
                    try:process.kill()
                    except OSError:pass
                return
            if control is not None:
                try:send_command(control.commands.get_nowait())
                except queue.Empty:pass
                except (OSError,ValueError):return
    try:
        process.stdin.write(json.dumps(spec,ensure_ascii=True).encode()+b'\n');process.stdin.flush()
        threading.Thread(target=cancel,daemon=True).start()
        while True:
            raw=process.stdout.readline(16385)
            if not raw:break
            if len(raw)>16384:raise MumuError('Некорректный отчёт процесса.')
            event=json.loads(raw)
            if (type(event) is not dict or set(event)!={'kind','value'} or
                event['kind'] not in ('progress','result','error','control') or type(event['value']) is not str or len(event['value'])>12000):
                raise MumuError('Некорректный отчёт процесса.')
            if event['kind']=='control':
                if control is not None:control.observe(event['value'])
                labels={'pause-requested':'Пауза запрошена • завершаю текущую задачу',
                    'resume-requested':'Возобновляю работу', 'paused':'На паузе', 'resumed':'Продолжаю работу'}
                if event['value'] not in labels:raise MumuError('Некорректный статус паузы.')
                progress(n,labels[event['value']]);continue
            progress(n,event['value'])
            if event['kind'] in ('result','error'):outcome[0]=event['value']
        process.wait(timeout=10)
        return outcome[0]
    finally:
        ended.set()
        # Single-port callers (manual port resume) rely on the same finished
        # latch run_many sets; finishing twice is idempotent.
        if control is not None:control.finish()
        process.stdin.close();process.stdout.close()
        if process.poll() is None:
            process.kill();process.wait(timeout=10)


def run_many(values,settings,mode,fresh,stopped,progress,*,worker=run_one,controls=None):
    values=parse('\n'.join(str(port(x)) for x in values))
    results={};guard=threading.Lock()
    def run(n):
        try:
            if stopped.is_set():value='Остановлено до запуска.'
            else:
                kwargs={} if controls is None else dict(control=controls[n])
                value=worker(n,settings,mode,fresh,stopped,progress,**kwargs)
        except Exception:
            value='Ошибка запуска рабочего процесса. См. папку отчётов этого порта.'
            progress(n,value)
        finally:
            if controls is not None:controls[n].finish()
        with guard:results[n]=value
    threads=[threading.Thread(target=run,args=(n,),daemon=True) for n in values]
    for thread in threads:thread.start()
    for thread in threads:thread.join()
    return results
