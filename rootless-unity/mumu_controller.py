"""GUI controller: independent processes; failure of one does not stop siblings."""
from dataclasses import asdict
import json
import os
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


def run_one(value,settings,mode,fresh,stopped,progress,*,popen=subprocess.Popen):
    n=port(value)
    spec=dict(port=n,settings=asdict(settings),mode=mode,fresh=fresh)
    options=dict(stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                 creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    process=popen(command(),**options)
    ended=threading.Event()
    outcome=['Рабочий процесс завершился без отчёта.']
    def cancel():
        while not ended.wait(.1):
            if stopped.is_set():
                try:
                    process.stdin.write(b'stop\n');process.stdin.flush()
                except (OSError,ValueError):pass
                # No restart/replay. A committed unknown reservation stays held.
                if not ended.wait(45):
                    try:process.kill()
                    except OSError:pass
                return
    try:
        process.stdin.write(json.dumps(spec,ensure_ascii=True).encode()+b'\n');process.stdin.flush()
        threading.Thread(target=cancel,daemon=True).start()
        while True:
            raw=process.stdout.readline(16385)
            if not raw:break
            if len(raw)>16384:raise MumuError('Некорректный отчёт процесса.')
            event=json.loads(raw)
            if (type(event) is not dict or set(event)!={'kind','value'} or
                event['kind'] not in ('progress','result','error') or type(event['value']) is not str or len(event['value'])>12000):
                raise MumuError('Некорректный отчёт процесса.')
            progress(n,event['value'])
            if event['kind'] in ('result','error'):outcome[0]=event['value']
        process.wait(timeout=10)
        return outcome[0]
    finally:
        ended.set()
        process.stdin.close();process.stdout.close()
        if process.poll() is None:
            process.kill();process.wait(timeout=10)


def run_many(values,settings,mode,fresh,stopped,progress,*,worker=run_one):
    values=parse('\n'.join(str(port(x)) for x in values))
    results={};guard=threading.Lock()
    def run(n):
        try:
            if stopped.is_set():value='Остановлено до запуска.'
            else:value=worker(n,settings,mode,fresh,stopped,progress)
        except Exception:
            value='Ошибка запуска рабочего процесса. См. папку отчётов этого порта.'
            progress(n,value)
        with guard:results[n]=value
    threads=[threading.Thread(target=run,args=(n,),daemon=True) for n in values]
    for thread in threads:thread.start()
    for thread in threads:thread.join()
    return results
