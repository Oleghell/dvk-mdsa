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


# Reports 484-489 (v1.3.72): twelve ports started from the GUI at the same
# instant all opened their journal, ran the first list navigation and the
# first profile batch in the same minutes. The shared session pooler then
# refused connects longer than every retry window (cloud-database-unavailable
# at profile-peer-check), and the native cycles burned their call budgets
# waiting for host approval. One worker process per port means the STARTS can
# be spaced: each port waits a jittered multiple of this spacing, so the
# journal/inbox/profile bursts never land as one wave. A Stop during the wait
# still aborts that port cleanly; single-port runs and manual restarts
# (run_one) never wait.
STARTUP_STAGGER_SECONDS = 27.0


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


def run_many(values,settings,mode,fresh,stopped,progress,*,worker=run_one,controls=None,spacing=None,jitter=None):
    values=parse('\n'.join(str(port(x)) for x in values))
    if spacing is None:spacing=STARTUP_STAGGER_SECONDS
    if jitter is None:
        from random import uniform
        def jitter():return uniform(0.8,1.4)
    results={};guard=threading.Lock()
    def run(n,index):
        try:
            value=None
            if stopped.is_set():value='Остановлено до запуска.'
            elif index and spacing:
                # Only the simultaneous multi-port start is spaced; the port
                # list order is the visible GUI order. The wait observes Stop
                # immediately, and the first port (index 0) never waits.
                delay=spacing*index*jitter()
                progress(n,'Ожидаю очередь запуска ~{} с: порты стартуют по одному, чтобы не перегружать общую базу одним мгновенным запуском.'.format(int(delay)))
                if stopped.wait(delay):value='Остановлено до запуска.'
            if value is None:
                kwargs={} if controls is None else dict(control=controls[n])
                value=worker(n,settings,mode,fresh,stopped,progress,**kwargs)
        except Exception:
            value='Ошибка запуска рабочего процесса. См. папку отчётов этого порта.'
            progress(n,value)
        finally:
            if controls is not None:controls[n].finish()
        with guard:results[n]=value
    threads=[threading.Thread(target=run,args=(n,index),daemon=True) for index,n in enumerate(values)]
    for thread in threads:thread.start()
    for thread in threads:thread.join()
    return results
