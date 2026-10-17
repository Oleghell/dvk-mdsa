"""Coordinate-free selectors and conservative screen-state inference.

App strings are data, never commands. Ambiguity/incomplete trees fail closed.
"""
from dataclasses import dataclass
import re

class UIError(RuntimeError):pass
class ElementNotFound(UIError):pass
class AmbiguousElement(UIError):pass
class StaleElement(UIError):pass
class IncompleteHierarchy(UIError):pass
class UnsupportedUI(UIError):pass

TEXT_KEYS={'resource_id','description','text','text_contains','class_name'}
BOOL_KEYS={'clickable','enabled','editable','focused','checked','checkable','selected'}
RELATIONS={'parent','ancestor','child','below'}

def selector(value,depth=0):
    if not isinstance(value,dict) or not value or len(value)>15 or depth>2:raise UIError('Invalid selector')
    if set(value)-TEXT_KEYS-BOOL_KEYS-RELATIONS-{'first'}:raise UIError('Unsupported selector property')
    for key,v in value.items():
        if key=='first':
            if v is not True:raise UIError('first must be explicitly true')
        elif key in TEXT_KEYS:
            if not isinstance(v,str) or not 1<=len(v)<=256 or any(ord(c)<32 for c in v):raise UIError('Invalid selector text')
        elif key in BOOL_KEYS:
            if type(v) is not bool:raise UIError('Invalid selector boolean')
        else:selector(v,depth+1)
    if depth==0 and not set(value)&(TEXT_KEYS|RELATIONS) and not value.get('editable'):raise UIError('Selector needs a semantic attribute')
    return value

def rank(s):
    for i,k in enumerate(('resource_id','description','text','text_contains','class_name','parent','ancestor','child')):
        if k in s:return i
    return 8

@dataclass(frozen=True)
class Tree:
    nodes: tuple
    context: str
    width: int
    height: int
    rotation: int=0
    density_dpi: int=0
    truncated: bool=False

    @classmethod
    def parse(cls,d):
        if not isinstance(d,dict) or d.get('package')!='drug.vokrug':raise UnsupportedUI('Wrong foreground package')
        if d.get('truncated') is not False:raise IncompleteHierarchy('Hierarchy incomplete; absence is not proven')
        if not re.fullmatch('[0-9a-f]{64}',str(d.get('tree_sha256',''))):raise UIError('Invalid tree context')
        w,h=d.get('width'),d.get('height')
        if type(w) is not int or type(h) is not int or not 200<=w<=4096 or not 200<=h<=4096 or w*h>10000000:raise UIError('Unsupported viewport')
        ns=d.get('nodes')
        if not isinstance(ns,list) or not 1<=len(ns)<=1000:raise IncompleteHierarchy('Missing hierarchy')
        for i,n in enumerate(ns):
            if not isinstance(n,dict) or n.get('index')!=i or type(n.get('parent')) is not int or not -1<=n['parent']<i:raise UIError('Invalid hierarchy structure')
            b=n.get('bounds')
            if not isinstance(b,list) or len(b)!=4 or any(type(v) is not int for v in b):raise UIError('Invalid node bounds')
            if n.get('visible') is not True:raise UIError('Invisible node in visible hierarchy')
            for k in BOOL_KEYS|{'password'}:
                if type(n.get(k)) is not bool:raise UIError('Invalid node capabilities')
            for k in ('resource_id','description','text','class_name','package'):
                if not isinstance(n.get(k),str):raise UIError('Invalid node attribute')
            if n['package']!='drug.vokrug' or (n['password'] and n['text']):raise UIError('Foreign or unredacted password node')
        return cls(tuple(ns),d['tree_sha256'],w,h,d.get('rotation',0),d.get('density_dpi',0))

    def matches(self,node,s):
        if node['password'] or not node.get('visible'):return False
        for key,value in s.items():
            if key=='first':continue
            if key=='below':
                anchors=[n for n in self.nodes if self.matches(n,value)]
                if len(anchors)>1:raise AmbiguousElement('Multiple structural anchors')
                if not anchors or node['bounds'][1]<anchors[0]['bounds'][3]:return False
            elif key in TEXT_KEYS:
                if key=='text_contains':
                    if value not in node['text']:return False
                elif node.get(key)!=value:return False
            elif key in BOOL_KEYS:
                if node.get(key) is not value:return False
            elif key=='parent':
                p=node['parent']
                if p<0 or not self.matches(self.nodes[p],value):return False
            elif key=='ancestor':
                p=node['parent'];found=False
                for _ in range(32):
                    if p<0:break
                    if self.matches(self.nodes[p],value):found=True;break
                    p=self.nodes[p]['parent']
                if not found:return False
            elif key=='child':
                if not any(c['parent']==node['index'] and self.matches(c,value) for c in self.nodes):return False
        return True

    def find(self,s):
        selector(s)
        if self.truncated:raise IncompleteHierarchy('Incomplete hierarchy')
        found=[n for n in self.nodes if self.matches(n,s)]
        if not found:raise ElementNotFound('No matching visible element')
        if s.get('first') and found:found=sorted(found,key=lambda n:(n['bounds'][1],n['bounds'][0]))[:1]
        if len(found)!=1:raise AmbiguousElement('Multiple elements; refine selector')
        n=found[0];l,t,r,b=n['bounds']
        if not (0<=l<r<=self.width and 0<=t<b<=self.height):raise UnsupportedUI('Element is clipped or outside viewport')
        return n

# These are conservative evidence patterns, NOT claims about every app version.
# A generic EditText is only an editor; never proof of an empty conversation.
SCREEN_RULES={
    'city_search':({'text':'Поиск города'},{'editable':True,'class_name':'android.widget.EditText'}),
    'search_filters':({'text':'Только онлайн','checkable':True},),
    'profile':({'text':'Друзья'},{'description':'Открыть чат'}),
    'message_editor':({'editable':True,'class_name':'android.widget.EditText'},),
}
def detect_screen(tree,rules=None):
    matched=[]
    for name,checks in (rules or SCREEN_RULES).items():
        try:
            for s in checks:tree.find(s)
        except (ElementNotFound,AmbiguousElement,UnsupportedUI):continue
        matched.append(name)
    specific=[s for s in matched if s!='message_editor']
    return {'state':specific[0] if len(specific)==1 else ('ambiguous' if len(specific)>1 else ('message_editor' if matched else 'unknown')),
            'evidence':matched,'identity_verified':False,'empty_chat_verified':False,
            'unity_surface':any(n['resource_id']=='drug.vokrug:id/unitySurfaceView' for n in tree.nodes)}
