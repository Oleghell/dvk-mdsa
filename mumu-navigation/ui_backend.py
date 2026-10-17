"""Reuse the signed Android instrumentation and existing strict ADB transport."""
import base64,json,re
from ui_model import Tree,UIError,StaleElement,UnsupportedUI

class NativeBackend:
    def __init__(self,reader,ledger):
        from universal_control import UniversalControl
        self.reader=reader;self.control=UniversalControl(reader,ledger)
    @staticmethod
    def report(out):
        reports=re.findall(r'^INSTRUMENTATION_RESULT: report_b64=([A-Za-z0-9+/=]+)\s*$',out,re.M)
        if len(reports)!=1:raise UIError('Missing native report; install the hierarchy branch helper locally')
        try:
            raw=base64.b64decode(reports[0],validate=True)
            if len(raw)>2000000:raise ValueError()
            data=json.loads(raw)
            if not isinstance(data,dict):raise ValueError()
            return data
        except (ValueError,TypeError):raise UIError('Invalid native report') from None
    def snapshot(self):
        if not self.reader.control_enabled:raise UnsupportedUI('Enable signed controls locally first')
        status,out=self.control.instrument({'op':'ui_dump'})
        if status!='inspection_ok':raise UnsupportedUI('UI hierarchy unavailable or helper is outdated; no OCR/action attempted')
        return Tree.parse(self.report(out))
    def diagnostics(self):
        if not self.reader.control_enabled:raise UnsupportedUI('Enable signed controls locally first')
        status,out=self.control.instrument({'op':'ui_diagnostics'})
        if status!='inspection_ok':raise UnsupportedUI('Expanded native diagnostics unavailable; install beta.2 helper. No visual fallback attempted')
        from ui_diagnostics import validate
        return validate(self.report(out))
    def unity_diagnostics(self):
        if not self.reader.control_enabled:raise UnsupportedUI('Enable signed controls locally first')
        status,out=self.control.instrument({'op':'ui_unity_diagnostics'})
        if status!='inspection_ok':raise UnsupportedUI('Unity package diagnostics unavailable; install beta.3 helper. No root or visual fallback attempted')
        from unity_diagnostics import validate
        return validate(self.report(out))
    def perform(self,element,operation,**args):
        strict=getattr(self.reader,'native_only',False) is True
        if strict and element.method!='hierarchy':raise UnsupportedUI('Strict native mode forbids OCR/CV elements')
        if element.method=='profile_cv':
            payload={'op':'click_profile_chat','expected_target_sha256':element.frame['context_sha256']}
        elif element.method=='ocr':
            if operation!='click':raise UnsupportedUI('OCR cannot authorize native text input')
            payload={'op':'ui_visual_click','expected_tree_sha256':element.context,'expected_frame_sha256':element.frame['sha256'],'bounds':element.node['bounds']}
        else:
            payload={'op':'ui_'+operation,'selector':element.query,'expected_tree_sha256':element.context}
            if operation=='click':payload['allow_coordinate_fallback']=not strict
            else:payload.update(text=args['text'],expected_text=args['expected_text'])
        state,out=self.control.instrument(payload)
        return state, self.report(out) if 'report_b64=' in out else {}
    def back(self,context):
        return self.control.instrument({'op':'ui_back','expected_tree_sha256':context})[0],{}

class ProfileVisionFallback:
    def __init__(self,backend):self.backend=backend
    def find(self,runtime,query,tree):
        from ui_model import ElementNotFound
        from ui_runtime import Element
        if query not in ({'description':'Открыть чат'},{'text':'Открыть чат'},{'text':'Написать'}):raise ElementNotFound('No approved CV model for this target')
        state,out=self.backend.control.instrument({'op':'find_profile_chat'})
        if state!='inspection_ok':raise ElementNotFound('Profile panel not recognized')
        from semantic_profile import SemanticProfile
        # Use the same validated report contract, not a guessed screen point.
        data=SemanticProfile.report(None,out)
        return Element(runtime,query,{'bounds':data['bounds']},tree.context,'profile_cv',data)
