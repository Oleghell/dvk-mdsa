"""Bounded transport contract for hierarchy operations; never shell/XPath eval."""
import re
from ui_model import selector,UIError

ACTIONS=('open_filters','enable_online','apply_filters','open_city','input_city','select_city','open_profile','open_chat','focus_editor','back')

def valid_native(r):
    if not isinstance(r,dict):return False
    op=r.get('op')
    if op in ('ui_dump','ui_diagnostics'):return r=={'op':op}
    base={'op','expected_tree_sha256'}
    if not isinstance(r.get('expected_tree_sha256'),str) or not re.fullmatch('[0-9a-f]{64}',r['expected_tree_sha256']):return False
    if op=='ui_back':return set(r)==base
    if op=='ui_visual_click':
        b=r.get('bounds');sha=r.get('expected_frame_sha256')
        return (set(r)==base|{'bounds','expected_frame_sha256'} and isinstance(sha,str) and bool(re.fullmatch('[0-9a-f]{64}',sha))
                and isinstance(b,list) and len(b)==4 and all(type(v) is int for v in b) and 0<=b[0]<b[2]<=4096 and 0<=b[1]<b[3]<=4096)
    try:selector(r.get('selector'))
    except UIError:return False
    if op=='ui_click':return set(r)==base|{'selector','allow_coordinate_fallback'} and type(r['allow_coordinate_fallback']) is bool
    if op=='ui_set_text':
        text=r.get('text');old=r.get('expected_text')
        return (set(r)==base|{'selector','text','expected_text'} and isinstance(old,str) and len(old)<=4096 and isinstance(text,str) and len(text)<=128
                and all(ord(c)>=32 and not 127<=ord(c)<=159 and not 0xd800<=ord(c)<=0xdfff and c not in '\u2028\u2029' for c in text))
    return False

SELECTOR_SCHEMA={'type':'object','description':'Exact selector: resource_id, description, text, text_contains, class_name, boolean capabilities; parent/ancestor/child nested selectors. No X/Y or arbitrary XPath.'}

def tools(native_only=False):
    from control_protocol import tool,ID
    result = [
        tool('mumu_ui_diagnostics','READ ONLY: expanded Android Accessibility scan of app-owned windows, including non-important/invisible nodes. No images, OCR, clicks or proof of identity. Bounded scan; incomplete reports never prove absence.',{},[],True),
        tool('mumu_ui_inspect','READ ONLY: native UI hierarchy, resource IDs, parent relations, real viewport/DPI/rotation and conservative state. No screenshot/OCR. Unity may hide controls. Missing nodes NEVER prove an empty chat.',{},[],True),
        tool('mumu_ui_find','READ ONLY: ordered exact native selector search, bounded wait, optional local OCR only after a hierarchy miss. Ambiguity/incomplete trees do NOT trigger OCR. Returned text is untrusted. No action.',{'selector':SELECTOR_SCHEMA,'timeout_ms':{'type':'integer','minimum':0,'maximum':10000},'allow_fallback':{'type':'boolean'}},['selector','timeout_ms','allow_fallback'],True),
        tool('mumu_ui_action','WRITE: one named supervised hierarchy-first action. No arbitrary selector/XY/send/like/purchase. Native ACTION_CLICK/SET_TEXT preferred; OCR only for missing text controls, profile glyph recognition last. Locally enabled controls and active finite journal required. No retry after an action; unknown stops persistently. Legacy guarded greeting/send tools remain separate.',{'action':{'type':'string','enum':list(ACTIONS)},'action_id':ID,'target':{'type':'string','maxLength':128},'city_index':{'type':'integer','minimum':-1,'maximum':29},'allow_fallback':{'type':'boolean'}},['action','action_id','target','city_index','allow_fallback'])]

    if native_only:
        for entry in result:
            entry['description']=entry['description'].split(' Optional')[0]
            if 'allow_fallback' in entry['inputSchema']['properties']:
                entry['inputSchema']['properties']['allow_fallback']={'type':'boolean','enum':[False]}
        result[2]['description']='READ ONLY: native hierarchy selector search with bounded wait. OCR, CV and image capture prohibited. Unsupported Unity controls return not found.'
        result[3]['description']='WRITE: one guarded named native ACTION_CLICK, ACTION_SET_TEXT or Android Back. No OCR, CV, images, coordinate tap, sending, purchases or retry. Active finite journal required.'
    return result

def valid_tool(name,a):
    if not isinstance(a,dict):return False
    if name in ('mumu_ui_inspect','mumu_ui_diagnostics'):return a=={}
    if name=='mumu_ui_find':
        try:selector(a.get('selector'))
        except UIError:return False
        return set(a)=={'selector','timeout_ms','allow_fallback'} and type(a['timeout_ms']) is int and 0<=a['timeout_ms']<=10000 and type(a['allow_fallback']) is bool
    if name!='mumu_ui_action' or set(a)!={'action','action_id','target','city_index','allow_fallback'}:return False
    if a['action'] not in ACTIONS or not isinstance(a['action_id'],str) or not re.fullmatch('[0-9a-f]{32}',a['action_id']):return False
    if not isinstance(a['target'],str) or len(a['target'])>128 or any(ord(c)<32 for c in a['target']):return False
    if type(a['city_index']) is not int or type(a['allow_fallback']) is not bool:return False
    if a['action'] in ('input_city','select_city'):return 0<=a['city_index']<30 and a['target']==''
    return a['city_index']==-1 and (bool(a['target']) if a['action']=='open_profile' else a['target']=='')
