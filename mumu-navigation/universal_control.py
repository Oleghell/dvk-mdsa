"""Local opt-in universal control transport. Never expose arbitrary shell commands."""
import base64
import hashlib
import hmac
import json
from pathlib import Path
import re
from control_protocol import *
from mumu_bridge import BridgeError, SERIAL, content_pixel_sha256

DIAGNOSTIC_CODES={'root_not_ready','node_not_ready','wrong_package','screenshot_unavailable','screen_dimensions','internal_error','invalid_editor_guard','editor_changed'}
DIAGNOSTIC_PHASES={'startup','startup_root','arguments','inspect_screen','inspect_field','validate_field','ime_input','gesture_guard','gesture_inject'}
def safe_diagnostic(output):
    pieces=[]
    for key,allowed in (('code',DIAGNOSTIC_CODES),('phase',DIAGNOSTIC_PHASES)):
        values=re.findall(r'^INSTRUMENTATION_RESULT: control_diagnostic_'+key+r'=([a-z_]+)\s*$',output,re.M)
        if len(values)==1 and values[0] in allowed:pieces.append(key+'='+values[0])
    return (' ['+', '.join(pieces)+']') if pieces else ''

class UniversalControl:
    def __init__(self,reader,ledger):self.reader=reader;self.ledger=ledger
    def ready(self):
        self.ledger._no_hold()
        if not getattr(self.reader,'control_enabled',False):raise BridgeError('Расширенный режим не включён локальной кнопкой.')
        if self.reader.action_uncertain:raise BridgeError('Неизвестный исход; только чтение.')
    def instrument(self,request):
        raw=base64.b64encode(json.dumps(request,ensure_ascii=True,separators=(',',':')).encode()).decode()
        args=['-s',SERIAL,'shell','am','instrument','-w','-r','-e','request_b64',raw,COMPONENT]
        if not args_allowed(args,getattr(self.reader,'control_enabled',False)):raise BridgeError('Control command refused')
        self.reader._foreground()
        out=self.reader._run(args).decode('utf-8','replace')
        states=re.findall(r'^INSTRUMENTATION_RESULT: control_status=([a-z_]+)\s*$',out,re.M)
        if len(states)!=1:raise BridgeError('Control outcome unknown; no retry')
        return states[0],out
    def inspect(self):
        if not getattr(self.reader,'control_enabled',False):raise BridgeError('Расширенный режим не включён локально.')
        state,out=self.instrument({'op':'inspect'})
        if state!='inspection_ok':raise BridgeError('Android inspection refused: '+state+safe_diagnostic(out))
        data=re.findall(r'^INSTRUMENTATION_RESULT: report_b64=([A-Za-z0-9+/=]+)\s*$',out,re.M)
        try:
            if state!='inspection_ok' or len(data)!=1:raise ValueError()
            d=json.loads(base64.b64decode(data[0],validate=True).decode())
            if not isinstance(d,dict) or type(d.get('focused')) is not bool or not valid_hash(d.get('content_sha256')):raise ValueError()
            if 'gesture_editor_guard_supported' in d and type(d['gesture_editor_guard_supported']) is not bool:raise ValueError()
            if d['focused']:
                a={'action_id':'a'*32,'expected_field_context_sha256':d.get('field_context_sha256'),'bounds':d.get('bounds'),'expected_text':d.get('text'),'mode':'clear','text':'','delay_ms':343}
                if not valid_call('mumu_control_text',a):raise ValueError()
            return d
        except (ValueError,UnicodeError,TypeError):raise BridgeError('Invalid control inspection') from None
    def execute(self,name,args):
        request=native_request(name,args);self.ready()
        if name=='mumu_control_text':
            d=self.inspect()
            if not d.get('focused') or d['bounds']!=args['bounds'] or d['text']!=args['expected_text'] or d['field_context_sha256']!=args['expected_field_context_sha256']:
                raise BridgeError('Поле изменилось. Действие не начато.')
        elif name=='mumu_control_gesture' and 'editor_guard' in args:
            d=self.inspect();guard=args['editor_guard']
            if d.get('gesture_editor_guard_supported') is not True:
                raise BridgeError('Нужна новая подписанная сборка Android-помощника; нажатие не начато.')
            if (not d.get('focused') or d['bounds']!=guard['bounds']
                    or d['text']!=guard['expected_text']
                    or not hmac.compare_digest(d['field_context_sha256'],args['expected_content_sha256'])):
                raise BridgeError('Поле или контекст изменились. Действие не начато.')
        elif not hmac.compare_digest(content_pixel_sha256(self.reader.screen()),args['expected_content_sha256']):
            raise BridgeError('Экран изменился. Действие не начато.')
        # Immutable per-action receipt; no text/screenshots/coordinates stored.
        with self.ledger.transaction():
            self.ledger._no_hold()
            if self.ledger.db.execute('SELECT COUNT(*) FROM control_actions').fetchone()[0]>=500:raise BridgeError('500 control actions used; no remote reset')
            if self.ledger.db.execute('SELECT 1 FROM control_actions WHERE id=?',(args['action_id'],)).fetchone():raise BridgeError('action_id already used; no replay')
            self.ledger.db.execute('INSERT INTO control_actions VALUES (?,?)',(args['action_id'],'reserved'))
        self.reader.action_uncertain=True
        try:
            state,out=self.instrument(request)
            if state in ('denied_arguments','denied_field','denied_screen_changed','denied_context','denied_ime'):
                self.finish(args['action_id'],'refused');self.reader.action_uncertain=False
                raise BridgeError('Android refused before action: '+state+safe_diagnostic(out))
            if state!=('text_verified' if name=='mumu_control_text' else 'input_injected'):raise BridgeError('Unknown control outcome; no retry')
        except BaseException:
            if self.reader.action_uncertain:self.finish(args['action_id'],'unknown')
            raise
        self.finish(args['action_id'],'succeeded');self.reader.action_uncertain=False
        return {'action_id':args['action_id'],'native_status':state,'result_screen_verified':False,
                'message_sent_verified':False,'warning':'Read the resulting screen. Native injection/readback does not prove search, navigation or sending.'}
    def finish(self,ident,state):
        with self.ledger.transaction():
            self.ledger.db.execute('UPDATE control_actions SET state=? WHERE id=? AND state=\'reserved\'',(state,ident))
            if state=='unknown':
                self.ledger.db.execute("INSERT OR IGNORE INTO holds VALUES ('unknown_device_action')")
                self.ledger.db.execute("UPDATE runs SET state='stopped' WHERE state='active'")


def enable_native_locally(reader,ledger,base):
    """Install ONE pinned native helper. Never switch keyboard or capture pixels."""
    from control_release import PACKAGES
    ledger._no_hold()
    p=(Path(base)/'control-helper.apk').resolve()
    try:
        if hashlib.sha256(p.read_bytes()).hexdigest()!=PACKAGES[p.name]:raise ValueError()
    except (OSError,ValueError):raise BridgeError('Pinned native APK missing or corrupt') from None
    reader._local_control_setup=True
    try:
        reader.control_install_paths.add(str(p))
        if b'Success' not in reader._run(['-s',SERIAL,'install','-t','-r',str(p)]):raise BridgeError('Native helper installation failed; no delete/retry')
        reader.control_enabled=True
    except BaseException:
        reader.control_enabled=False;raise
    finally:reader._local_control_setup=False


def enable_locally(reader,ledger,base):
    """Local GUI only. Install two checksum-pinned packages and select this IME."""
    from control_release import PACKAGES
    ledger._no_hold()
    reader._local_control_setup=True
    ime_switch_attempted=False
    try:
        for name,sha in PACKAGES.items():
            p=(Path(base)/name).resolve()
            try:
                if hashlib.sha256(p.read_bytes()).hexdigest()!=sha:raise ValueError()
            except (OSError,ValueError):raise BridgeError('Pinned universal APK missing or corrupt') from None
            reader.control_install_paths.add(str(p))
        # Validate BOTH files before any install.
        for name in ('keyboard-helper.apk','control-helper.apk'):
            p=str((Path(base)/name).resolve())
            if b'Success' not in reader._run(['-s',SERIAL,'install','-t','-r',p]):raise BridgeError('Control APK installation failed; no auto-delete/retry')
        previous=reader._run(['-s',SERIAL,'shell','settings','get','secure','default_input_method']).decode().strip()
        if previous!=IME:
            if re.fullmatch(r'[A-Za-z0-9_.]+/[A-Za-z0-9_.$]+',previous) is None:raise BridgeError('Cannot verify previous keyboard; no IME switch')
            ledger.db.execute("INSERT OR REPLACE INTO control_config VALUES ('previous_ime',?)",(previous,))
        elif ledger.db.execute("SELECT 1 FROM control_config WHERE key='previous_ime'").fetchone() is None:
            raise BridgeError('Previous keyboard unavailable; restore a keyboard in Android settings first')
        reader._run(['-s',SERIAL,'shell','ime','enable',IME])
        ime_switch_attempted=True
        reader._run(['-s',SERIAL,'shell','ime','set',IME])
        now=reader._run(['-s',SERIAL,'shell','settings','get','secure','default_input_method']).decode().strip()
        if now!=IME:raise BridgeError('Keyboard selection not verified')
        reader.control_enabled=True
    except BaseException:
        reader.control_enabled=False
        if ime_switch_attempted:
            try:restore_keyboard_locally(reader,ledger)
            except Exception:pass # GUI explicitly directs manual Android recovery.
        raise
    finally:reader._local_control_setup=False


def restore_keyboard_locally(reader,ledger):
    reader._local_control_setup=True
    try:
        row=ledger.db.execute("SELECT value FROM control_config WHERE key='previous_ime'").fetchone()
        if row is not None:
            previous=row[0]
            if re.fullmatch(r'[A-Za-z0-9_.]+/[A-Za-z0-9_.$]+',previous) is None:raise BridgeError('Invalid saved keyboard')
            now=reader._run(['-s',SERIAL,'shell','settings','get','secure','default_input_method']).decode().strip()
            if now==IME:
                reader.previous_ime=previous
                reader._run(['-s',SERIAL,'shell','ime','set',previous])
                actual=reader._run(['-s',SERIAL,'shell','settings','get','secure','default_input_method']).decode().strip()
                if actual!=previous:raise BridgeError('Previous keyboard restoration not verified')
    finally:reader._local_control_setup=False


def stop_locally(reader,ledger):
    """Local Stop only. Kill pending IME typing; restore only our captured IME."""
    reader.control_enabled=False
    if getattr(reader,'native_only',False) is True:return
    reader._local_control_setup=True
    try:
        reader._run(['-s',SERIAL,'shell','am','force-stop','com.dvk.keyboard.v2'])
        restore_keyboard_locally(reader,ledger)
    finally:reader._local_control_setup=False
