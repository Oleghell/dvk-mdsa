"""One existing semantic profile/chat cycle, with explicit per-message host consent.

No automatic approval, no batch loop, no new RPC accepting code or arbitrary ADB.
The native side rechecks the same identity and fully loaded empty history after
approval; its send latch still precedes the handler invocation.
"""
import json
import threading
import time

import chat_batch
import cohort_pass
from assistant_config import check_text
from assistant_store import StateError
from uikit_profile_navigation import replace_once

APPROVAL_SECONDS = 60
CYCLE_TIMEOUT_MS = 90000
FINALIZE_RPC_SECONDS = 60
# Reports 410-432: one ~120KB history RPC destroyed the MuMu gadget session on
# every port and every retry, while small RPCs on the same session always pass.
# The snapshot now streams in bounded pieces of the same magnitude as the
# inbox payloads that reliably survive that transport.
HISTORY_UPLOAD_CHUNK = 1000
# 1.3.78: raised together with mumu_store.VISITED_SNAPSHOT_LIMIT (pinned equal
# by test; duplicated so the JS contract never imports the store layer) so the
# FULL shared claims registry fits in one uploaded snapshot - the native
# selection-time pre-filter (batchSeen) then skips already-greeted peers
# BEFORE their profile or chat is ever opened. Pieces stay at
# HISTORY_UPLOAD_CHUNK; only the cumulative ceiling moved.
SNAPSHOT_VISITED_LIMIT = 100000

# Reports 449-454: a single failed pooler connect during a READ-ONLY
# shared-registry check cancelled a live cycle and stopped the whole profile
# pass on every 1.3.68 port. peer_claimed() and peer_terminal() run before
# approval, reservation and ACK, and visited_peers() runs before any script
# exists: nothing is sent or written for the peer yet, and the native cycle
# waits on its own budget. Those three reads retry transient transport and
# capacity failures with a bounded budget; Stop and every other failure keep
# the existing hard cancel path.
# Reports 458-461 (v1.3.69): with only two short pauses a pooler outage
# outlasted the whole retry window and still cancelled a live batch
# (profile-peer-check exhaustion). The pauses now span a wider window while
# staying inside the native cycle budget: 4 attempts, 17s of total pause,
# each attempt bounded by the existing connect timeout.
# Reports 468-470 (v1.3.70, two laptops running the same ports): the 17s
# window still exhausted while both installations retried in lockstep. The
# fifth attempt adds one more 20s span (37s of pause in total, still inside
# the 90s native cycle budget), and the DEFAULT pause is jittered so the two
# machines stop retrying as one synchronized wave against the pooler.
SHARED_READ_RETRY_DELAYS = (2.0, 5.0, 10.0, 20.0)
# Reports 498-507 (v1.3.74, dropmefiles W8VPRYkX): seven ports died at
# prepare-greeting with transition-timeout and two more hard-stopped at
# profile-peer-check. The pauses above are 37s nominal, but the jitter
# multiplier (x1.6) stretches them to ~59s, and each attempt itself spends
# seconds in connect retries - so a saturated pooler pushed the pre-send
# window past the native cycle's ABSOLUTE 90s deadline. The script then died
# waiting for its own approval (transition-timeout), the port entered blind
# screen repair for ~two minutes and finally stopped with
# recovery-unfinished. The window is now bounded by wall clock: exhaustion
# surfaces as the same transient error by 40s, which leaves ~50s of the
# native budget for the verified no-send Back of the deferred skip. This is
# strictly better than a longer window that kills the cycle it protects.
SHARED_READ_DEADLINE_SECONDS = 40.0
# 1.3.81: releasing a committed-but-never-ACKed reservation is a best-effort
# single-transaction delete (device-scoped, idempotent). It runs on teardown
# paths where drain_threads() bounds the whole monitor thread at 30s, so its
# own window stays far below that budget; a refused release merely keeps the
# pre-1.3.81 behaviour (claim held, finish() records 'not-invoked').
RELEASE_RETRY_DELAYS = (2.0, 5.0)
RELEASE_DEADLINE_SECONDS = 12.0


def shared_registry_read(action, stopped, *, delays=None, pause=None,
                          deadline=SHARED_READ_DEADLINE_SECONDS, clock=time.monotonic):
    """Bounded retry for read-only pre-send shared-registry reads.

    Bounded twice: by attempts (delays) and by wall clock (deadline). The
    deadline includes the pauses and the attempts themselves, so exhaustion
    can never outlast the native cycle budget that waits on this read.
    """
    from cloud_database import CloudDatabaseError, TRANSIENT_CODES
    if delays is None: delays = SHARED_READ_RETRY_DELAYS
    if pause is None:
        # Two installations share one session pooler; identical fixed pauses
        # make every port on both laptops reconnect in the same instant. The
        # jitter only spreads the retry inside its own slot (never beyond the
        # window); injected test pauses keep receiving the exact delay.
        from random import uniform
        def pause(seconds): time.sleep(seconds * uniform(1.0, 1.6))
    started = clock()
    for delay in (*delays, None):
        try:
            return action()
        except CloudDatabaseError as error:
            if delay is None or stopped() or error.code not in TRANSIENT_CODES:
                raise
            # The default pause may sleep up to delay*1.6; account for the
            # worst case so the deadline is a hard bound, not a hope.
            if clock() - started + delay * 1.6 >= deadline:
                raise
            pause(delay)
            # A pause can outlive the native cycle that waits on this read
            # (its own absolute deadline). Do not start another database
            # attempt after the caller is already done: raise the same
            # transient error and let the pre-send defer path decide.
            if stopped():
                raise


# Reports 433-447: the bootstrap wrapper still dropped the second RPC argument,
# so every streamed piece finalized immediately and the SECOND piece was
# rejected (assistantVisited already set) -> authored StateError on all 15
# ports. The wrapper must forward `final` exactly like the JS contract below;
# smoke and unit tests exercise THIS string, never a hand-copied twin.
BOOTSTRAP_EXPORTS = '''rpc.exports={runtime(){return {frida_version:Frida.version,arch:Process.arch,platform:Process.platform};},
 root(){return assistantPreparedRoot();},preparevisited(values,final){return assistantPrepareVisited(values,final);},cancel(){cancelNavigation();},
 selectedpeer(){return assistantSelectedPeer;},cohortpending(){return cohortReservation();},cohortack(value){return cohortAcknowledge(value);}};
'''


def host_worker(target,args):
    """Native callback threads must not leave idle database sessions behind."""
    try:target(*args)
    finally:
        from cloud_database import close_idle_connections
        close_idle_connections()


def build(text, visited=()):
    text = check_text(text)
    from conversation_engine import identifier
    if not isinstance(visited, (list, tuple)) or len(visited) > SNAPSHOT_VISITED_LIMIT:
        raise ValueError('Invalid visited profiles')
    visited = [identifier(peer) for peer in visited]
    source = cohort_pass.build([0] * 10)
    source = replace_once(source, 'let batchSeen=new Set(),',
                          'let batchSeen=new Set(' + json.dumps(visited) + '),')
    source = replace_once(source, 'batchSeen.size>=10', 'batchAttempts>1')
    source = replace_once(source, 'batchCandidateKey=identityKey;',
                          'batchCandidateKey=identityKey;assistantSelectedPeer=identityKey;')
    source = replace_once(source, 'const batchGreetings=' + json.dumps([cohort_pass.get_greeting(0)] * 10),
                          'const batchGreetings=' + json.dumps([text] * 10))
    # This is a single cycle, not a longer automatic pass. Existing per-frame,
    # managed-call, handle and identity budgets remain unchanged.
    source = replace_once(source, 'batchAttempts>=10', 'batchAttempts>=1')
    source = replace_once(source, 'finish(\'callback-timeout\');},30000);',
                          'finish(\'callback-timeout\');},90000);')
    source = replace_once(source, '"cycle_timeout_ms":30000', '"cycle_timeout_ms":90000')
    from assistant_profile_read import specialize
    source = specialize(source)
    import os
    if os.environ.get('DVK_MUMU_MULTI') == '1':
        from mumu_claims import specialize
        source = specialize(source)
    # Unready profile/return views used to spin on every Unity callback,
    # burning frame/call budgets before the next UI update. Throttle only
    # observations; existing action latches, 100ms frame and total budgets stay.
    source = replace_once(source, 'const deadline=Date.now()+100;',
        "const deadline=Date.now()+100;\n  if(n.phase==='wait-profile'||n.phase==='confirm-profile'||n.phase==='wait-return')state.nextActionAt=Date.now()+100;")
    return 'let assistantSelectedPeer=null;\n' + source


def prepared_source(text):
    """Compile fixed code, then configure bounded peer IDs as DATA before root.

    No eval, no code/text setter, and no native/UI work in initialization RPC.
    The existing durable reservation and per-peer native ACK remain mandatory.
    Values may stream in several bounded chunks; the optional second argument
    marks the final piece. Without it a single call finalizes exactly as before.
    """
    source=build(text,[])
    return r"""
let assistantVisited=null,assistantRootStarted=false,assistantVisitedParts=null;
function assistantPrepareVisited(values,final){
 if(assistantVisited!==null||assistantRootStarted||!Array.isArray(values)||values.length>10000)return false;
 const checked=[];
 for(const value of values){
  if(typeof value!=='string'||!/^[1-9][0-9]{0,18}$/.test(value)||value.length===19&&value>'9223372036854775807'){assistantVisitedParts=null;return false;}
  checked.push(value);
 }
 if(assistantVisitedParts===null)assistantVisitedParts=[];
 for(const value of checked)assistantVisitedParts.push(value);
 if(assistantVisitedParts.length>"""+str(SNAPSHOT_VISITED_LIMIT)+r"""){assistantVisitedParts=null;return false;}
 if(final===undefined||final===null||final===true){
  assistantVisited=Object.freeze(assistantVisitedParts);assistantVisitedParts=null;batchSeen=new Set(assistantVisited);
 }
 return true;
}
function assistantPreparedRoot(){
 if(assistantVisited===null||assistantRootStarted)throw new Error('profile-not-prepared');
 assistantRootStarted=true;return probeBatchProfile();
}
"""+source


def validate(value, *, shared_peer_skipped=False):
    # Only normalize the declared timeout for the existing strict validator.
    # Never normalize a send flag, identity, history classification or result.
    import copy
    checked = copy.deepcopy(value)
    from assistant_profile_read import validate as validate_profile_read
    # v1.3.92: the profile-read validator now distinguishes the two verified
    # skip forms - the unready-chat read skip and the chat-not-opened skip.
    skipped_unready, skipped_chat_open = validate_profile_read(checked['navigation'])
    if type(checked['navigation']['cycle_timeout_ms']) is not int or checked['navigation']['cycle_timeout_ms'] != CYCLE_TIMEOUT_MS:
        raise ValueError('Invalid manual-cycle deadline')
    checked['navigation']['cycle_timeout_ms'] = chat_batch.CYCLE_TIMEOUT_MS
    import os
    native_skip = checked['navigation'].pop('shared_peer_skipped', False)
    if type(native_skip) is not bool or type(shared_peer_skipped) is not bool:
        raise ValueError('Unverified shared peer skip')
    n = checked['navigation']
    # The host sets its deny-only latch BEFORE the ACK RPC. Cancellation or a
    # budget stop may occur before native observes it, or during checked Back.
    # Preserve a fully validated STOP, not a fictitious successful skip. Never
    # use host state to rewrite send flags, history, identity or return evidence.
    stopped_skip = (shared_peer_skipped and n.get('stage') == 'navigation-stopped'
        and n.get('send_attempted') is False and n.get('send_handler_returned') is False)
    if native_skip != shared_peer_skipped and not (stopped_skip and not native_skip):
        raise ValueError('Unverified shared peer skip')
    if (native_skip or shared_peer_skipped) and os.environ.get('DVK_MUMU_MULTI') != '1':
        raise ValueError('Shared skip outside MuMu worker')
    if native_skip and not (n.get('send_attempted') is False and n.get('send_handler_returned') is False):
        raise ValueError('Shared skip with submission')
    chat_batch.validate(checked, skipped_empty=native_skip and n.get('stage') == 'navigation-ready',
                        skipped_unready=skipped_unready, skipped_chat_open=skipped_chat_open)
    return value


PROFILE_DIAGNOSTIC_FIELDS=('stage','error','phase','frames','managed_calls','metadata_checkpoint',
    'selection_check','read_checkpoint','wait_reason','search_verified','open_attempted','open_completed',
    'chat_open_attempted','chat_open_completed','send_attempted','send_handler_returned','return_verified',
    'profile_model_waits','chat_open_waits',
    'profile_read_budget_retries','greeting_frame_splits','profile_ready_waits','profile_read_skipped',
    'profile_read_skip_reason','profile_input_enabled','chat_back_attempted','chat_back_completed',
    'chat_return_verified','chat_identity_verified','chat_return_route','shared_peer_skipped')


def drain_threads(threads,done,*,timeout=30,clock=time.monotonic):
    """Stop authorization before validating its final state. Never start a retry.

    SQL may legitimately take longer than the old two-second join. One shared
    deadline bounds drainage, not thirty seconds for every thread.
    """
    done.set();deadline=clock()+timeout
    for thread in threads:thread.join(timeout=max(0,deadline-clock()))
    if any(thread.is_alive() for thread in threads):
        raise StateError('profile-authorization-pending')


def monitor(script, store, text, approve, done, cancelled, state, failures=None, preclaimed=frozenset()):
    """A successful FULL SQLite commit MUST happen before native authorization."""
    from cloud_database import CloudDatabaseError, TRANSIENT_CODES
    def defer(peer):
        # Reports 491-493 (v1.3.73): pooler pressure outlasted the whole
        # pre-send retry window and killed live batches on all reporting
        # ports. The remaining live check below is read-only and happens
        # before the native ACK: no send was authorized for this peer, so an
        # exhausted transient window costs one verified no-send skip. The
        # claim registry stays authoritative; the port keeps its pass alive
        # instead of stopping.
        state['peer_check_deferred']=True
        from mumu_claims import skip
        skip(script, peer, state)
    def release(pending):
        """v1.3.81: return a committed-but-never-ACKed reservation to the pool.

        Reached only on paths PROVEN to end before any ACK: root() already
        returned (the native cycle is over, its send latch never opened), the
        host stopped before the ACK, or the ACK RPC came back stale. No send
        was authorized or attempted for this peer, so deleting THIS device's
        own claim row keeps the peer eligible instead of permanently
        claimed-but-never-greeted. The release matches the journal row by
        account+peer (not by the insert's rowid) and is idempotent and
        device-scoped: another port's reservation is never touched, an
        uncommitted reservation matches nothing, and a lost COMMIT that landed
        both rows server-side is still found and returned.
        """
        try:
            shared_registry_read(
                lambda: store.release_reservation(pending),
                lambda: cancelled() or done.is_set(),
                delays=RELEASE_RETRY_DELAYS, deadline=RELEASE_DEADLINE_SECONDS)
            state['action_id'] = None  # finish() must not replay a released row.
            state['reservation_released'] = True
        except Exception:
            # Best effort by design: a saturated pooler may refuse the release
            # too. The reservation then stays held exactly as before 1.3.81;
            # finish() records 'not-invoked' and no duplicate send is possible.
            pass
    while not done.wait(.05):
        phase='profile-pending-read'
        try:
            pending = script.exports_sync.cohortpending()
            if pending is None:
                continue
            pending = dict(cohort_pass.Store.check(pending))
            if cancelled() or done.is_set():
                return
            # A terminal global outcome or prior greeting on any port skips before
            # typing; reserve below rechecks atomically after approval.
            # Reports aPYyN7weMm (v1.3.78, «заходит в чат и выходит без
            # приветствия»): the live peer_claimed() read added one pooled
            # cloud roundtrip to EVERY profile cycle, and under 12-port pooler
            # saturation its transient window exhausted into defer() exactly
            # when the chat was ALREADY OPEN - the cycle ended in a verified
            # no-send Back and the peer was left un-greeted. The pass-start
            # visited snapshot (loaded in inspect() and already fed to the
            # native pre-filter) contains every shared claim/block and every
            # own-journal peer, so membership answers the same question
            # instantly with no database dependency. Claims and terminal
            # outcomes added after the snapshot stay caught by reserve()'s
            # live atomic blocked() re-check, which remains the cross-account
            # dedup authority.
            phase='profile-peer-check'
            if getattr(store, 'mumu_shared_claims', False) is True:
                if pending['peer'] in preclaimed:
                    from mumu_claims import skip
                    phase='profile-skip-ack'
                    skip(script, pending, state)
                    return
            # No reservation (and no send authorization) on No, Stop or timeout.
            phase='profile-approval'
            approval=approve(dict(pending),text,lambda:cancelled() or done.is_set())
            if cancelled() or done.is_set():return
            if approval is not True:
                state['declined']=True
                script.exports_sync.cancel()
                return
            phase='profile-reserve'
            try:
                # Reports QZ2X7 (v1.3.79): eight of eleven reporting ports died
                # stopped at prepare-profile-reserve-failed with
                # cloud-database-unavailable/connect - the reservation is the
                # LAST database step before the ACK, so its single attempt met
                # the same synchronized pooler burst the reads survived since
                # 1.3.69, killed the cycle as journal-error (a recovery BLOCK
                # code) and the port never came back. The reservation writes
                # nothing until its own COMMIT: a transport/capacity failure
                # leaves no partial state, and the retry re-runs blocked()
                # first, so a peer claimed by another port while we waited
                # still raises SharedPeerClaimed into the verified skip. The
                # same bounded jittered window as the reads applies; a lost
                # COMMIT ack surfaces on retry as blocked() -> skip, never a
                # duplicate greeting. Exhaustion defers into the verified
                # no-send Back (no reservation, no ACK, peer stays eligible)
                # instead of stopping the port.
                state['action_id'] = shared_registry_read(
                    lambda: store.reserve(pending, text, approved=True),
                    lambda: cancelled() or done.is_set())
            except StateError as error:
                from mumu_store import SharedPeerClaimed
                if not isinstance(error, SharedPeerClaimed):
                    raise
                from mumu_claims import skip
                phase='profile-skip-ack'
                skip(script, pending, state)
                return
            except CloudDatabaseError as error:
                if error.code not in TRANSIENT_CODES or cancelled():
                    raise
                if done.is_set():
                    # Same race as the reads, one reservation window later: the
                    # native report (its own budget stop) already decides the
                    # cycle; never stop the port after root() returned. A lost
                    # COMMIT on the last attempt may still have left OUR claim
                    # row: the device-scoped release is idempotent and safe
                    # either way, so the peer does not stay claimed without a
                    # greeting (v1.3.81).
                    release(pending)
                    state['peer_check_deferred']=True
                    return
                defer(pending)
                return
            if cancelled() or done.is_set():
                # v1.3.81: the reservation committed but no ACK can ever
                # follow (the cycle is over or the host is stopping). The old
                # doctrine kept the claim "durable unknown", which cost one
                # permanently un-greeted peer per occurrence - exactly when the
                # pooler was slowest. Release it; another port (or a later
                # pass on another journal) can still greet this peer.
                release(pending)
                return
            # v1.3.81: the separate post-reserve terminal read is GONE. The
            # atomic blocked() re-check INSIDE reserve() already rejects
            # claimed, blocked, terminally-done and recovery-skipped peers
            # (SharedPeerClaimed into the verified skip), and the pass-start
            # snapshot prefilters every pre-existing terminal peer before its
            # profile is ever opened. The extra pooled roundtrip on EVERY
            # greeting cycle fed the very pooler bursts that deferred open
            # chats with a RETAINED claim - leaving peers permanently
            # un-greeted and the user watching a silent open dialog. The ACK
            # now follows the reservation directly; a terminal outcome
            # committed in the milliseconds between COMMIT and ACK costs one
            # harmless greeting that the reply flow answers anyway.
            phase='profile-ack'
            if not script.exports_sync.cohortack(pending):
                # Stale reservation: the native state moved on and no send
                # latch opened for this authorization. Release the claim so
                # the peer stays eligible instead of silently lost.
                release(pending)
                raise StateError('Подтверждение устарело. Отправка остановлена.')
            return  # Exactly one authorization per host operation.
        except Exception as error:
            from run_preparation import record as prepared
            prepared(error,phase)
            if failures is not None:failures.append(error)
            state['authorization_failure']=getattr(error,'_dvk_preparation',None)
            state['authorization_checkpoint']=phase
            state['error'] = str(error) if isinstance(error, StateError) else 'Не удалось сохранить или проверить разрешение отправки.'
            try:
                script.exports_sync.cancel()
            except Exception:
                pass
            return


def inspect(port, token, cancelled, text, store, approve, *, frida_api=None):
    if frida_api is None:
        import frida as frida_api
    from diagnose_device import cleanup_frida, validate_runtime
    from one_chat_device import ReadStopped
    from test_device import PACKAGE
    from startup_failure import record
    f = frida_api
    if f.__version__ != '17.24.1':
        raise ReadStopped('client-version')
    # This database read precedes ANY script, RPC or authorization thread.
    try:
        from run_preparation import checkpoint
        with checkpoint('profile-history'):
            visited=shared_registry_read(lambda: store.visited_peers(), cancelled)
    except Exception as error:
        error._dvk_profile_not_executed=True
        raise
    source = prepared_source(text) + BOOTSTRAP_EXPORTS
    try:
        manager = f.get_device_manager()
    except Exception as error:
        record(error,'gadget-manager');raise
    address = '127.0.0.1:' + str(port)
    device = session = script = None
    done = threading.Event()
    state = {};failures=[]
    threads = []
    guard = f.Cancellable()
    timer = threading.Timer(100, guard.cancel)
    timer.daemon = True
    timer.start()
    stage='gadget-connect'
    value=None;threads_drained=False
    setup_started=time.monotonic()
    try:
        with guard:
            if cancelled():
                raise ReadStopped('cancelled')
            device = manager.add_remote_device(address, token=token)
            stage='gadget-process'
            processes = device.enumerate_processes()
            if (len(processes) != 1 or type(processes[0].pid) is not int or processes[0].pid <= 0
                    or processes[0].name not in ('Gadget', PACKAGE)):
                raise ReadStopped('unexpected-process')
            stage='gadget-attach'
            session = device.attach(processes[0].pid)
            stage='script-create'
            script = session.create_script(source, name='dvk-assistant-manual-profile')
            stage='script-load'
            script.load()
            stage='runtime-check'
            runtime = validate_runtime(script.exports_sync.runtime())
            if runtime['arch'] != 'arm64' or runtime['platform'] != 'linux':
                raise ReadStopped('unsupported-runtime')
            stage='profile-history-upload'
            pieces=[visited[index:index+HISTORY_UPLOAD_CHUNK]
                    for index in range(0,len(visited),HISTORY_UPLOAD_CHUNK)] or [[]]
            last=len(pieces)-1
            for position,piece in enumerate(pieces):
                # A bounded history keeps the original one-argument call; larger
                # snapshots stream as pieces of HISTORY_UPLOAD_CHUNK with an
                # explicit final flag. Every piece keeps the same fixed stage,
                # so a destroyed script stays the proven pre-execution retry.
                if last==0:
                    uploaded=script.exports_sync.preparevisited(piece)
                else:
                    uploaded=script.exports_sync.preparevisited(piece,position==last)
                if uploaded is not True:
                    raise StateError('profile-history-not-prepared')
            if cancelled():raise ReadStopped('cancelled')
            def watch():
                while not done.wait(.1):
                    if cancelled():
                        try:
                            script.exports_sync.cancel()
                        except Exception:
                            pass
                        return
            # Same snapshot set that was streamed to the native pre-filter:
            # every shared claim/block plus the port's own journal peers. It
            # answers the claimed-peer pre-check in monitor() without a pooled
            # cloud roundtrip, so a saturated pooler can no longer waste an
            # already-opened chat on a transient defer.
            preclaimed = frozenset(visited)
            for target, args in ((watch, ()), (monitor, (script, store, text, approve, done, cancelled, state, failures, preclaimed))):
                thread = threading.Thread(target=host_worker, args=(target,args), daemon=True)
                threads.append(thread)
                thread.start()
            stage='script-run'
            raw = script.exports_sync.root()
            done.set();timer.cancel()
            # Native root has its own deadline. Give host drainage/final read a
            # separate bounded guard, never an unbounded post-root RPC.
            timer=threading.Timer(FINALIZE_RPC_SECONDS,guard.cancel)
            timer.daemon=True;timer.start()
            stage='profile-thread-drain'
            drain_threads(threads,done)
            threads_drained=True
            stage='result-validation'
            value = validate(raw, shared_peer_skipped=state.get('shared_peer_skipped', False))
            n = value['navigation']
            stage='profile-selected-peer'
            peer = script.exports_sync.selectedpeer()
            if peer is not None:
                stage='profile-record-visit'
                try:
                    store.record_visit(peer, n)
                except Exception as error:
                    from cloud_database import CloudDatabaseError, TRANSIENT_CODES
                    if (state.get('peer_check_deferred') is not True
                            or not isinstance(error, CloudDatabaseError)
                            or error.code not in TRANSIENT_CODES
                            or n['send_attempted'] or n['send_handler_returned']):
                        raise
                    # A deferred no-send cycle may lose its auxiliary visit row
                    # while the pooler is saturated. The claim registry remains
                    # the authoritative dedup and this peer simply stays eligible
                    # for a later verified re-check; the pass must not die here.
                    state['deferred_visit_unrecorded']=True
            stage='profile-finish-journal'
            action_id = state.get('action_id')
            if n['send_attempted'] and action_id is None:
                raise StateError('profile-authorization-missing')
            if action_id is not None:
                store.finish(action_id, n)
            if failures:
                stage='profile-authorization'
                raise failures[0]
            if state.get('error'):
                stage='profile-authorization'
                raise StateError('profile-authorization-failed')
            return dict(navigation=n, declined=state.get('declined', False),
                        reservation_released=state.get('reservation_released', False))
    except Exception as error:
        # This exact host path has not loaded a script, started any RPC or
        # authorization thread. A remote script possibly allocated by a failed
        # create_script call is still NOT loaded and cannot execute the cycle.
        error._dvk_profile_not_executed = ((stage=='script-create' and script is None or stage=='profile-history-upload')
            and not threads and not state)
        if value is not None and threads_drained:
            n=value['navigation']
            error._dvk_profile_diagnostics={k:n[k] for k in PROFILE_DIAGNOSTIC_FIELDS if k in n}
            error._dvk_profile_no_send_verified=(n['send_attempted'] is False and n['send_handler_returned'] is False)
        if state.get('authorization_checkpoint') is not None:
            error._dvk_profile_authorization_checkpoint=state['authorization_checkpoint']
        error._dvk_profile_source_bytes=len(source.encode('utf-8'))
        error._dvk_profile_history_count=len(visited)
        error._dvk_profile_setup_ms=min(1000000,max(0,int((time.monotonic()-setup_started)*1000)))
        if stage in {'profile-thread-drain','profile-selected-peer','profile-record-visit','profile-finish-journal','profile-authorization'}:
            from run_preparation import record as prepared
            prepared(error,stage)
        record(error,stage)
        raise
    finally:
        done.set()
        timer.cancel()
        for thread in threads:
            thread.join(timeout=2)
        cleanup_frida(f, manager, address, script, session, device)


def run(executable, folder, text, approve, cancelled=lambda: False, *, store=None):
    from pathlib import Path
    from one_chat_device import capture
    from assistant_lock import operation_lock
    from assistant_store import Store
    folder = Path(folder).resolve(strict=True)
    # Old anonymous locks cannot be safely assigned to a particular recipient.
    for name in ('.dvk-ten-profile-pass.lock', '.dvk-one-greeting.lock'):
        if (folder / name).exists():
            raise StateError('Есть прежний незавершённый резерв отправки. Не удаляй его; сначала нужна сверка старого запуска.')
    text = check_text(text)
    with operation_lock():
        store = Store() if store is None else store
        return capture(executable, folder, cancelled,
                       inspector=lambda port, token, cancel, expected: inspect(port, token, cancel, text, store, approve))


def run_automatic(executable, folder, text, cancelled=lambda: False, *, enabled=False, store=None):
    """Explicit one-run opt-in, ONE profile/greeting, same native checks/journal.

    No modal per-message approval. This is not a background/bulk sender.
    """
    if enabled is not True:
        raise StateError('Сначала явно включи автоматические сообщения в окне режима.')
    return run(executable, folder, text,
               lambda pending, greeting, native_cancelled: not cancelled() and not native_cancelled(),
               cancelled, store=store)
