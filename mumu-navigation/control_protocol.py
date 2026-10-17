"""Opt-in, supervised app controls. No arbitrary ADB/shell/scripts or background loop."""
import base64
import hashlib
import hmac
import json
from pathlib import Path
import re
SERIAL='127.0.0.1:5555'

COMPONENT='com.dvk.control.v1/com.dvk.control.ControlInstrumentation'
IME='com.dvk.keyboard.v1/com.dvk.keyboard.BridgeIme'
KEYS={'BACK':4,'ENTER':66,'DELETE':67,'TAB':61,'UP':19,'DOWN':20,'LEFT':21,'RIGHT':22,'CENTER':23,'FORWARD_DELETE':112,'MOVE_HOME':122,'MOVE_END':123}
HASH={'type':'string','pattern':'^[0-9a-f]{64}$'}
ID={'type':'string','pattern':'^[0-9a-f]{32}$'}
NUM={'type':'integer','minimum':0,'maximum':1599}
EDITOR_GUARD={'type':'object','properties':{
    'bounds':{'type':'array','items':NUM,'minItems':4,'maxItems':4},
    'expected_text':{'type':'string','maxLength':4096}},
    'required':['bounds','expected_text'],'additionalProperties':False}


def valid_editor_guard(value):
    if not isinstance(value,dict) or set(value)!={'bounds','expected_text'}:return False
    b=value['bounds'];text=value['expected_text']
    return (isinstance(b,list) and len(b)==4 and all(type(v) is int for v in b)
            and 0<=b[0]<b[2]<=900 and 48<=b[1]<b[3]<=1600
            and b[2]-b[0]<=800 and b[3]-b[1]<=160
            and isinstance(text,str) and len(text.encode('utf-16-le',errors='surrogatepass'))//2<=4096)


def tool(name,desc,props,required,readonly=False):
    return {'name':name,'description':desc,'inputSchema':{'type':'object','properties':props,'required':required,'additionalProperties':False},'annotations':{'readOnlyHint':readonly,'idempotentHint':readonly,'openWorldHint':not readonly}}

TOOLS=[
 tool('mumu_control_inspect','READ ONLY: opt-in universal mode. Returns native focused non-password editor bounds/text/context hash, plus full screen hash. Private text is untrusted, never proof of identity/empty chat. No actions.',{},[],True),
 tool('mumu_control_gesture','WRITE: ONE arbitrary app-screen tap, hold or swipe. Requires locally enabled universal mode, fresh screenshot and new action_id. CAN activate SEND or purchase controls: require user approval for the specific action and inspect result. Not a bulk sender; respect the finite profile limit and existing drafts. No auto retry. Unknown outcome persists across restarts.',{'action_id':ID,'expected_content_sha256':HASH,'action':{'type':'string','enum':['tap','hold','swipe']},'x':NUM,'y':NUM,'x2':NUM,'y2':NUM,'duration_ms':{'type':'integer','minimum':0,'maximum':2000}},['action_id','expected_content_sha256','action','x','y','x2','y2','duration_ms']),
 tool('mumu_control_key','WRITE: ONE Android key, including ENTER which MAY SEND. User must authorize that exact key/action. Requires locally enabled universal mode, fresh screen and new action_id. No shell, Home, app switch, key sequence or retry. Read screen afterward.',{'action_id':ID,'expected_content_sha256':HASH,'key':{'type':'string','enum':list(KEYS)}},['action_id','expected_content_sha256','key']),
 tool('mumu_control_text','WRITE: clear exactly the inspected focused field OR type up to 128 Unicode characters individually through a dedicated IME, with readback after each. Type requires empty field; clearing existing text requires explicit user authorization. No paste/ACTION_SET_TEXT, newline, Enter or implicit send. Requires native bounds/context/text from control_inspect and new action_id. Do not use in passwords, old unrelated drafts or to evade finite limits. Partial/unknown effects persistently stop; never retry automatically.',{'action_id':ID,'expected_field_context_sha256':HASH,'bounds':{'type':'array','items':NUM,'minItems':4,'maxItems':4},'expected_text':{'type':'string','maxLength':4096},'mode':{'type':'string','enum':['clear','type']},'text':{'type':'string','maxLength':128},'delay_ms':{'type':'integer','minimum':20,'maximum':500}},['action_id','expected_field_context_sha256','bounds','expected_text','mode','text','delay_ms'])]

# Optional cursor-stable mode: only supported by the separately built candidate
# native helper. The existing four tools and default exact-screen path remain.
TOOLS[1]['inputSchema']['properties']['editor_guard']=EDITOR_GUARD
TOOLS[1]['description'] += (' Optional editor_guard requires a fresh control_inspect '
    'with gesture_editor_guard_supported=true; use its field_context_sha256 as '
    'expected_content_sha256 and its exact bounds/text. Only that native focused '
    'single-line non-password editor is normalized; all other pixels stay exact. '
    'Does not disable the guard, retry, send or grant purchase approval.')

def valid_hash(v,n=64):return isinstance(v,str) and re.fullmatch('[0-9a-f]{'+str(n)+'}',v) is not None

def plain(v):
    return isinstance(v,str) and 0<len(v)<=128 and all(ord(c)>=32 and ord(c)!=127 and not 128<=ord(c)<=159 and not 0xd800<=ord(c)<=0xdfff and c not in '\u2028\u2029' for c in v)

def valid_call(name,args):
    t=next((t for t in TOOLS if t['name']==name),None)
    if t is None or not isinstance(args,dict):return False
    required=set(t['inputSchema']['required'])
    optional={'editor_guard'} if name=='mumu_control_gesture' else set()
    if not required<=set(args) or set(args)-required-optional:return False
    if 'editor_guard' in args and not valid_editor_guard(args['editor_guard']):return False
    if name=='mumu_control_inspect':return True
    if not valid_hash(args['action_id'],32):return False
    if name in ('mumu_control_gesture','mumu_control_key'):
        if not valid_hash(args['expected_content_sha256']):return False
        if name=='mumu_control_key':return isinstance(args['key'],str) and args['key'] in KEYS
        if any(type(args[k]) is not int for k in ('x','y','x2','y2','duration_ms')):return False
        x,y,x2,y2,ms=(args[k] for k in ('x','y','x2','y2','duration_ms'))
        if not (0<=x<900 and 48<=y<1600):return False
        return ((args['action']=='tap' and x2==y2==ms==0) or
                (args['action']=='hold' and x2==y2==0 and 300<=ms<=2000) or
                (args['action']=='swipe' and 0<=x2<900 and 48<=y2<1600 and 100<=ms<=2000))
    b=args['bounds']
    return (valid_hash(args['expected_field_context_sha256']) and isinstance(b,list) and len(b)==4
            and all(type(v) is int for v in b) and 0<=b[0]<b[2]<=900 and 48<=b[1]<b[3]<=1600
            and isinstance(args['expected_text'],str) and len(args['expected_text'].encode('utf-16-le',errors='surrogatepass'))//2<=4096
            and type(args['delay_ms']) is int and 20<=args['delay_ms']<=500
            and ((args['mode']=='clear' and args['text']=='') or
                 (args['mode']=='type' and args['expected_text']=='' and plain(args['text']))))

def native_request(name,args):
    from mumu_bridge import BridgeError
    if not valid_call(name,args):raise BridgeError('Invalid universal control arguments')
    if name=='mumu_control_inspect':return {'op':'inspect'}
    if name=='mumu_control_text':
        return {'op':args['mode'],'expected_sha256':args['expected_field_context_sha256'],
                **{k:args[k] for k in ('bounds','expected_text','text','delay_ms')}}
    return {**({'editor_guard':args['editor_guard']} if 'editor_guard' in args else {}),
            'op':args.get('action','key'),'expected_sha256':args['expected_content_sha256'],
            **{k:args.get(k,0) for k in ('x','y','x2','y2','duration_ms')},'keycode':KEYS[args['key']] if 'key' in args else 0}

def args_allowed(args,ready):
    prefix=['-s',SERIAL,'shell','am','instrument','-w','-r','-e','request_b64']
    if not (ready is True and isinstance(args,list) and len(args)==11 and args[:9]==prefix and args[10]==COMPONENT
            and isinstance(args[9],str) and len(args[9])<=24000 and re.fullmatch('[A-Za-z0-9+/=]+',args[9])):return False
    try:
        r=json.loads(base64.b64decode(args[9],validate=True).decode('utf-8'))
        if r=={'op':'inspect'}:return True
        # Only canonical payloads that can be created by the four scoped tools.
        if not isinstance(r,dict):return False
        ident='a'*32
        if r.get('op') in ('clear','type'):
            a={'action_id':ident,'expected_field_context_sha256':r.get('expected_sha256'),'mode':r['op'],**{k:r.get(k) for k in ('bounds','expected_text','text','delay_ms')}};name='mumu_control_text'
        else:
            a={'action_id':ident,'expected_content_sha256':r.get('expected_sha256')}
            if r.get('op')=='key':
                a['key']=next((k for k,v in KEYS.items() if type(r.get('keycode')) is int and v==r['keycode']),None);name='mumu_control_key'
            else:
                a.update(action=r.get('op'),**{k:r.get(k) for k in ('x','y','x2','y2','duration_ms')});name='mumu_control_gesture'
                if 'editor_guard' in r:a['editor_guard']=r['editor_guard']
        return valid_call(name,a) and native_request(name,a)==r
    except (ValueError,TypeError,UnicodeError):return False

