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
from mumu_common import port,parse,MumuError,device_directory
from mumu_pause import PortControl


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


# Reports 508-510 (v1.3.76, dropmefiles vYCRUyXNE): twelve ports started over
# the 1.3.73 queue; the first nine came up, the LAST three died inside their
# own stagger slots. 5577/5579 burned the worker's whole journal-start retry
# ladder (5 attempts, ~1.5-4 minutes) on cloud-database-unavailable (connect):
# by the time their slots arrived, the first nine ports were deep in their
# first journal/inbox/profile storm against the same ~45-slot session pooler,
# and the refusal outlasted every retry window. 5575 died silently right after
# its initial report (status=starting, stage=worker-bootstrap, never advanced)
# and stayed a dead row until a human pressed "Перезапустить порт". Both
# shapes are PROVABLY PRE-SEND: the journal bootstrap block is idempotent
# (CREATE IF NOT EXISTS, OR IGNORE backfill, policy inserts) and a report that
# never advanced past worker-bootstrap means no ADB/journal action ran at all,
# so a fresh worker process replays nothing. The controller therefore
# re-queues such a port automatically - bounded, jittered, Stop-aware -
# instead of leaving it dead for the whole run.
STARTUP_REQUEUE_LIMIT = 2
STARTUP_REQUEUE_DELAYS = (20.0, 45.0)
# Pinned to cloud_database.TRANSIENT_CODES by test; duplicated so the GUI
# controller itself never imports the engine's database layer.
REQUEUE_DATABASE_CODES = frozenset({'cloud-database-unavailable', 'cloud-database-capacity'})


def startup_requeue_reason(n, since):
    """Closed evidence check on this port's own last-startup.json.

    Returns a short reason line only when the report PROVES a pre-send,
    requeueable startup death that was written after `since` (the failing
    attempt's launch time): either a transient pooler-connect refusal at
    journal bootstrap, or a worker that died silently at worker-bootstrap.
    Everything else - reports from earlier runs, later stages, non-transient
    database codes, user cancellations, missing or unreadable files -
    returns None and keeps the hard stop untouched.
    """
    try:
        path = device_directory(n) / 'last-startup.json'
        if path.stat().st_mtime < since - 5.0:
            return None  # A report left by an earlier run never requeues.
        report = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None
    if type(report) is not dict or report.get('device_port') != n:
        return None
    # The worker re-writes last-startup.json at every stage transition, so a
    # report still at the INITIAL write after the process ended is a silent
    # death before any stage completed (no ADB, no journal, no send).
    if report.get('status') == 'starting' and report.get('stage') == 'worker-bootstrap':
        return 'рабочий процесс молча завершился при подготовке порта'
    database = report.get('database')
    if (report.get('status') == 'stopped' and report.get('reason') == 'startup-failed'
            and report.get('stage') == 'journal-initialization'
            and report.get('error_type') == 'CloudDatabaseError'
            and type(database) is dict
            and set(database) == {'code', 'operation', 'automatic_retry'}
            and database.get('operation') == 'connect'
            and database.get('code') in REQUEUE_DATABASE_CODES
            and database.get('automatic_retry') is False):
        return 'общая база была занята при подключении'
    return None


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
                attempt=0
                while True:
                    launched=time.time()
                    value=worker(n,settings,mode,fresh,stopped,progress,**kwargs)
                    # Reports 508-510: bounded automatic requeue of provably
                    # pre-send startup deaths; see startup_requeue_reason.
                    if stopped.is_set() or attempt>=STARTUP_REQUEUE_LIMIT:break
                    reason=startup_requeue_reason(n,launched)
                    if reason is None:break
                    if controls is not None:
                        # run_one already finished the previous control on its
                        # own exit path; a live requeued attempt needs a fresh
                        # one, exactly like the GUI's manual port resume, so
                        # pause/resume stay usable and the restart button
                        # never races the automatic retry.
                        controls[n]=PortControl();kwargs=dict(control=controls[n])
                    wait=STARTUP_REQUEUE_DELAYS[min(attempt,len(STARTUP_REQUEUE_DELAYS)-1)]*jitter()
                    progress(n,'Автоповтор запуска (попытка {} из {}): {}; отправки не повторяются. Ожидаю ~{} с.'.format(
                        attempt+2,STARTUP_REQUEUE_LIMIT+1,reason,int(wait)))
                    if stopped.wait(wait):break  # Keep the real failure text.
                    attempt+=1
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
