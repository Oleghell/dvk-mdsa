"""Independent phone processes; Stop sends cancellation, never resumes an action."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from morelogin_common import CloudError, phone_id
from morelogin_client import plan, DirectPlan
from morelogin_diagnostics import save_failure


def worker_command():
    if getattr(sys, 'frozen', False):
        return [str(Path(sys.executable).with_name('DvkCloudWorker.exe'))]
    return [sys.executable, str(Path(__file__).with_name('morelogin_app.py')), '--cloud-worker']


def one(spec, stopped, publish, *, spawn=subprocess.Popen, stop_grace=125):
    cloud_id = phone_id(spec['id'])
    process = None
    finished = threading.Event()
    try:
        if stopped.is_set(): return
        environment = os.environ.copy()
        environment['PYTHONIOENCODING'] = 'utf-8'
        environment['DVK_MORELOGIN'] = '1'
        environment.pop('DVK_MORELOGIN_PHONE_ID', None)
        process = spawn(worker_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding='utf-8', errors='strict', bufsize=1,
            env=environment, shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        process.stdin.write(json.dumps(spec, ensure_ascii=True)+'\n')
        process.stdin.flush()
        def cancel():
            while not finished.wait(.2):
                if stopped.is_set():
                    try:
                        process.stdin.write('stop\n')
                        process.stdin.flush()
                    except Exception:
                        pass
                    # Native operation has its own bounded deadlines. If the child
                    # cannot stop, terminate only that child; never replay any send.
                    if not finished.wait(stop_grace):
                        try: process.terminate()
                        except Exception: pass
                    return
        watcher = threading.Thread(target=cancel, daemon=True)
        watcher.start()
        terminal = False
        while True:
            line = process.stdout.readline(16385)
            if not line: break
            if len(line)>16384: raise CloudError('worker-stopped')
            try:
                value=json.loads(line)
                if not isinstance(value,dict): raise ValueError()
                if value.get('kind') in ('progress','finished') and set(value)=={'kind','text'} and isinstance(value['text'],str):
                    publish(cloud_id, value['kind'], value['text'][:4000])
                    terminal |= value['kind']=='finished'
                elif value.get('kind')=='error' and set(value)=={'kind','code'} and value['code'] in CloudError.CODES:
                    publish(cloud_id,'error',value['code'])
                    terminal=True
                else: raise ValueError()
            except Exception:
                raise CloudError('worker-stopped') from None
        process.wait(timeout=10)
        if not terminal: publish(cloud_id,'error','worker-stopped')
    except Exception:
        publish(cloud_id,'error','worker-stopped')
    finally:
        finished.set()
        if process is not None:
            if process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except Exception:
                    try: process.kill()
                    except Exception: pass
            for stream in (process.stdin,process.stdout):
                if stream is not None: stream.close()


def run(settings, ids, pins, entries, mode, stopped, publish, *, target=one):
    threads=[]
    for cloud_id in ids:
        if stopped.is_set(): break
        if not entries.get(cloud_id):
            publish(cloud_id,'error','phone-unavailable')
            continue
        try:
            selected=plan(entries[cloud_id],cloud_id)
        except CloudError as error:
            save_failure([cloud_id],error,entry=entries[cloud_id])
            publish(cloud_id,'error',error.code)
            continue
        direct=isinstance(selected,DirectPlan)
        if not direct and cloud_id not in pins:
            publish(cloud_id,'error','ssh-key-untrusted')
            continue
        spec=dict(id=cloud_id,entry=entries[cloud_id],fingerprint=None if direct else pins[cloud_id],settings=asdict(settings),mode=mode)
        thread=threading.Thread(target=target,args=(spec,stopped,publish),daemon=True)
        thread.start()
        threads.append(thread)
    for thread in threads: thread.join()
