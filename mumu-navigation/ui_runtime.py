"""Hierarchy-first runtime. No screenshot/OCR on a successful native lookup.

Waits poll read-only observations. Actions are NEVER retried or failed-over after
an injection attempt. The mutation callback owns authorization and journalling.
"""
from dataclasses import dataclass
import logging,time
from ui_model import (Tree,selector,rank,UIError,ElementNotFound,AmbiguousElement,
                      IncompleteHierarchy,StaleElement,UnsupportedUI,detect_screen)
LOG=logging.getLogger('dvk.ui')

@dataclass(frozen=True)
class Element:
    runtime: object
    query: dict
    node: dict
    context: str
    method: str='hierarchy'
    frame: object=None

    def click(self,*,action_id,purpose):
        return self.runtime.mutate(self,'click',action_id=action_id,purpose=purpose)
    def set_text(self,value,*,action_id,purpose,expected_text=''):
        if self.method!='hierarchy' or not self.node.get('editable'):raise UnsupportedUI('Text requires a real editable Android node')
        return self.runtime.mutate(self,'set_text',action_id=action_id,purpose=purpose,text=value,expected_text=expected_text)

class AndroidUI:
    def __init__(self,backend,mutation=None,ocr=None,vision=None,clock=time.monotonic,pause=time.sleep):
        self.backend=backend;self.mutation=mutation;self.ocr=ocr;self.vision=vision
        self.clock=clock;self.pause=pause
    def inspect(self):
        tree=self.backend.snapshot()
        return tree,detect_screen(tree)
    def find_element(self,*,alternatives=None,timeout=0,allow_fallback=False,**attrs):
        if not isinstance(timeout,(int,float)) or isinstance(timeout,bool) or not 0<=timeout<=10:raise UIError('Timeout must be 0..10 seconds')
        queries=[selector(attrs)] if attrs else []
        if alternatives is not None:
            if not isinstance(alternatives,(list,tuple)) or not 1<=len(alternatives)<=8:raise UIError('Invalid selector alternatives')
            queries.extend(selector(s) for s in alternatives)
        if not queries:raise UIError('No selector')
        queries=sorted(queries,key=rank);deadline=self.clock()+timeout
        LOG.info('[UI] Searching element: strategies=%d',len(queries))
        while True:
            tree=self.backend.snapshot()
            for query in queries:
                try:
                    node=tree.find(query)
                    LOG.info('[UI] Element found: method=hierarchy strategy=%d',rank(query))
                    return Element(self,query,node,tree.context)
                except ElementNotFound:continue
                # Ambiguous/incomplete/stale/foreign data never triggers OCR.
            remaining=deadline-self.clock()
            if remaining<=0:break
            self.pause(min(.15,remaining))
        if allow_fallback:
            for label,provider in (('OCR',self.ocr),('CV',self.vision)):
                if provider is None:continue
                LOG.info('[%s] Fallback activated',label)
                for query in queries:
                    try:return provider.find(self,query,tree)
                    except (ElementNotFound,UnsupportedUI):continue
        LOG.warning('[ERROR] Element not found')
        raise ElementNotFound('No unique element; hierarchy unavailable or fallback did not match')
    def wait_for_element(self,timeout=10,**kwargs):
        return self.find_element(timeout=timeout,**kwargs)
    def wait_for_screen(self,state,timeout=10):
        if state not in ('city_search','search_filters','profile','message_editor'):raise UIError('Unknown screen state')
        if type(timeout) not in (int,float) or not 0<=timeout<=10:raise UIError('Invalid timeout')
        LOG.info('[UI] Waiting for screen state: %s',state);deadline=self.clock()+timeout
        while True:
            tree,result=self.inspect()
            if result['state']==state:return tree,result
            remaining=deadline-self.clock()
            if remaining<=0:raise ElementNotFound('Expected state did not appear before timeout')
            self.pause(min(.15,remaining))
    def mutate(self,element,operation,**kwargs):
        if self.mutation is None:raise UnsupportedUI('Read-only runtime; a supervised action policy is required')
        LOG.info('[UI] Performing action: %s method=%s',operation,element.method)
        return self.mutation(element,operation,**kwargs)
