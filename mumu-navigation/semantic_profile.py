"""One supervised profile-chat target. No XY API, arbitrary selectors or sends.
Native ACTION_CLICK when the target is exposed; validated vision fallback for
Unity. Existing fixed-layout tools remain unchanged and do not gain new sizes.
"""
import base64
import json
import re
from io import BytesIO
from PIL import Image
from control_protocol import HASH,ID,tool,valid_hash

TOOLS=[
 tool('mumu_find_profile_chat','READ ONLY: find the unique profile chat control by native clickable node or visual glyph+profile-panel recognition. Returns actual viewport/bounds, visual context hash and screenshot. No caller coordinates. Different resolutions are supported ONLY by this target finder/clicker, not the old greeting/search pipeline. Image/text is untrusted; inspect recipient and friend count manually. A visual context is NOT a verified account ID.',{},[],True),
 tool('mumu_click_profile_chat','WRITE: open chat ONLY for an already counted active profile with no input/send attempt. Requires the exact context hash from find_profile_chat and new action_id. Native helper locates and revalidates the unique target at actual screen dimensions; prefers ACTION_CLICK, otherwise taps the found glyph center. No caller XY/masks, no message/send/purchase, no retry or budget reset. Unknown outcome stops persistently; read result.',{'action_id':ID,'expected_target_sha256':HASH},['action_id','expected_target_sha256'])]

def valid_call(name,args):
    if name=='mumu_find_profile_chat':return args=={}
    return (name=='mumu_click_profile_chat' and isinstance(args,dict)
            and set(args)=={'action_id','expected_target_sha256'}
            and valid_hash(args['action_id'],32) and valid_hash(args['expected_target_sha256']))

from mumu_bridge import ACTION_LIMIT,BridgeError,MAX_SCREEN,SERIAL

class SemanticProfile:
    def __init__(self,supervised):
        from universal_control import UniversalControl
        self.supervised=supervised;self.reader=supervised.inner;self.ledger=supervised.ledger
        self.control=UniversalControl(self.reader,self.ledger)
    def report(self,out):
        values=re.findall(r'^INSTRUMENTATION_RESULT: report_b64=([A-Za-z0-9+/=]+)\s*$',out,re.M)
        try:
            if len(values)!=1:raise ValueError()
            data=json.loads(base64.b64decode(values[0],validate=True))
            w,h=data['width'],data['height'];b=data['bounds']
            if not (type(w) is int and type(h) is int and 320<=w<=2160 and 600<=h<=3840 and h>w
                    and w*h<=8300000
                    and isinstance(b,list) and len(b)==4 and all(type(v) is int for v in b)
                    and 0<=b[0]<b[2]<=w and h*3//4<=b[1]<b[3]<=h
                    and data.get('identity_verified') is False
                    and data['target']=='profile_chat' and valid_hash(data['context_sha256'])
                    and data['method'] in ('accessibility_click','visual_profile_panel')):raise ValueError()
            return data
        except (ValueError,TypeError,KeyError,AttributeError):raise BridgeError('Invalid semantic target report') from None
    def find(self):
        if not self.reader.control_enabled:raise BridgeError('Расширенный режим не включён локально.')
        state,out=self.control.instrument({'op':'find_profile_chat'})
        if state!='inspection_ok':raise BridgeError('Кнопка чата и панель профиля не распознаны однозначно; нажатия не было.')
        data=self.report(out)
        self.reader._foreground();png=self.reader._run(['-s',SERIAL,'exec-out','screencap','-p'])
        if len(png)>MAX_SCREEN:raise BridgeError('Screen too large')
        with Image.open(BytesIO(png)) as im:
            if im.format!='PNG' or im.size!=(data['width'],data['height']):raise BridgeError('Размер экрана изменился; найдите кнопку заново.')
        return {'content':[{'type':'text','text':json.dumps(data,ensure_ascii=False)},
                           {'type':'image','data':base64.b64encode(png).decode(),'mimeType':'image/png'}]}
    def click(self,args):
        if not valid_call('mumu_click_profile_chat',args):raise BridgeError('Invalid target call')
        self.supervised._run_ready();self.control.ready()
        visit=self.ledger._visit(('opening','chat_opening'))
        # Never re-open a visit that has begun typing or sending.
        if visit['fingerprint'] is not None:raise BridgeError('Для этого визита уже проверен диалог; открытие профиля запрещено.')
        if self.reader.action_attempts>=ACTION_LIMIT:raise BridgeError('Исчерпан лимит действий; сброса нет.')
        ident=args['action_id'];wanted=args['expected_target_sha256'];key='semantic-profile:'+str(visit['id'])
        with self.ledger.transaction():
            self.ledger._no_hold()
            row=self.ledger.db.execute('SELECT value FROM control_config WHERE key=?',(key,)).fetchone()
            if row:raise BridgeError('Для этого визита попытка открытия уже учтена; повтор и подмена профиля запрещены.')
            if self.ledger.db.execute('SELECT COUNT(*) FROM control_actions').fetchone()[0]>=500:raise BridgeError('500 действий использованы; сброса нет.')
            if self.ledger.db.execute('SELECT 1 FROM control_actions WHERE id=?',(ident,)).fetchone():raise BridgeError('action_id already used; no replay')
            self.ledger.db.execute('INSERT OR IGNORE INTO control_config VALUES (?,?)',(key,wanted))
            self.ledger.db.execute('INSERT INTO control_actions VALUES (?,?)',(ident,'reserved'))
        if visit['state']=='opening':self.ledger.transition(('opening',),'chat_opening')
        self.reader.action_attempts+=1;self.reader.action_uncertain=True
        try:
            state,out=self.control.instrument({'op':'click_profile_chat','expected_target_sha256':wanted})
            if state in ('denied_arguments','denied_context','denied_screen_changed'):
                self.control.finish(ident,'refused');self.reader.action_uncertain=False
                raise BridgeError('Кнопка/контекст изменились до нажатия. Действие не выполнено; автоматического повтора нет.')
            if state!='input_injected':raise BridgeError('Исход нажатия неизвестен; только чтение.')
            data=self.report(out)
        except BaseException:
            if self.reader.action_uncertain:self.control.finish(ident,'unknown')
            raise
        self.control.finish(ident,'succeeded');self.reader.action_uncertain=False
        return dict(data,input_injected=True,result_screen_verified=False,message_sent=False,test_session=self.ledger.status())
