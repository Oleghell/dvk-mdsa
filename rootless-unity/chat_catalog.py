"""Offline definitions only: profile -> chat route and loaded/empty history.

Never invokes a method, attaches to MuMu, reads chat data or prepares/sends text.
"""
import json,struct
from pathlib import Path
from offline_metadata import MetadataError
from friends_catalog import inspect_bundle as inspect_definitions,definition_fields,label

VERSION='0.3.13'
MAX_TYPES=32
MAX_DEPTH=3
MAX_METHODS=512
MAX_FIELDS=128
MAX_PARAMETERS=64
MAX_TOTAL_METHODS=4096
MAX_TOTAL_FIELDS=2048
MAX_TOTAL_PARAMETERS=4096
ROOTS=(('DV.Profile.dll','DV.Profiles','ProfileViewController'),
       ('DV.Profile.dll','DV.Profiles','ProfilesQueueViewController'),
       ('DV.Messages.dll','DV.Messages','MessagesViewController'),
       ('DV.Messages.dll','DV.Messages','ChatsViewController'))
WORDS=('chat','message','history','dialog','conversation')
STATE_WORDS=('load','ready','actual','state','count','empty','hasmore','complete','initial','cache','page','cursor')


def parameter_layout(metadata):
    """Verified v31 <name:uint, token:uint, typeIndex:int>; no defaults/values."""
    h=struct.unpack_from('<64I',metadata.data);offset,size=h[22:24]
    if not size:
        if any(m['parameter_count'] for m in metadata.methods):raise MetadataError('Missing parameters')
        return offset,0
    metadata._section(offset,size,12)
    sections=(metadata.strings,metadata._method_bytes,metadata._type_bytes,metadata._image_bytes,(h[24],h[25]))
    if any(n and offset<o+n and o<offset+size for o,n in sections):raise MetadataError('Overlapping parameters')
    count=size//12;seen=bytearray(count)
    for m in metadata.methods:
        first,n=m['parameter_start'],m['parameter_count']
        if n and not 0<=first<=count-n:raise MetadataError('Invalid parameter ownership')
        if not n and not -1<=first<=count:raise MetadataError('Invalid empty parameters')
        for index in range(first,first+n):
            if seen[index]:raise MetadataError('Duplicate parameters')
            seen[index]=1
            if struct.unpack_from('<i',metadata.data,offset+index*12+8)[0]<0:raise MetadataError('Invalid parameter type')
    if sum(seen)!=count:raise MetadataError('Unowned parameters')
    return offset,count


def collect(metadata):
    po,pc=parameter_layout(metadata)
    all_fields={}
    for owner,name,ti in definition_fields(metadata):all_fields.setdefault(owner,[]).append((name,ti))
    byval={}
    for index,t in enumerate(metadata.types):
        ti=t['byval_type_index']
        if ti>=0:byval.setdefault(ti,[]).append(index)
    def identity(t):
        if not label(t['image']) or not label(t['name']) or (t['namespace'] and not label(t['namespace'])):return None
        return {'image':t['image'],'namespace':t['namespace'],'type':t['name']}
    def resolve(ti):
        result={'type_index':ti}
        if type(ti) is not int or ti<0:return {**result,'status':'invalid-index'}
        hits=byval.get(ti,[])
        if len(hits)!=1:return {**result,'status':'unresolved' if not hits else 'ambiguous'}
        target=identity(metadata.types[hits[0]])
        return {**result,'status':'resolved','target':target} if target else {**result,'status':'unsupported-name'}
    def app(t):return t['image'].startswith('DV') and t['image'].endswith('.dll') and identity(t) is not None
    queued=set();queue=[];truncated=False
    def enqueue(owner,depth,role):
        nonlocal truncated
        if owner in queued or not app(metadata.types[owner]):return
        if depth>MAX_DEPTH or len(queued)>=MAX_TYPES:truncated=True;return
        queued.add(owner);queue.append((owner,depth,role))
    def follow(ti,depth):
        hits=byval.get(ti,[]) if type(ti) is int and ti>=0 else []
        if len(hits)==1:enqueue(hits[0],depth,'linked')
    roots=[]
    for image,ns,name in ROOTS:
        hits=[i for i,t in enumerate(metadata.types) if (t['image'],t['namespace'],t['name'])==(image,ns,name)]
        roots.append({'image':image,'namespace':ns,'type':name,'status':'found' if len(hits)==1 else 'missing' if not hits else 'ambiguous'})
        if len(hits)==1:enqueue(hits[0],0,'controller')
    # Bounded supplemental discovery prevents dependence on guessed model names.
    candidates=[]
    for index,t in enumerate(metadata.types):
        if not app(t) or t['name'].startswith('<'):continue
        text=(t['namespace']+'.'+t['name']).lower()
        if not any(w in text for w in WORDS):continue
        if not (any(w in t['namespace'].lower() for w in ('model','registry','cm')) or t['name'].endswith('CM')):continue
        priority=0 if t['name'].lower() in ('chat','message','messagescm','chatcm','chatsregistry','messagesregistry') else 1
        candidates.append((priority,t['image'],t['namespace'],t['name'],index))
    candidates.sort()
    for *_,index in candidates[:12]:enqueue(index,0,'candidate')
    nodes=[];method_count=field_count=parameter_count=0
    for owner,depth,role in queue:
        t=metadata.types[owner];node={**identity(t),'type_definition_index':owner,'byval_type_index':t['byval_type_index'],
              'declaring_type_index':t['declaring_type_index'],'role':role,'depth':depth,'parent':resolve(t['parent_type_index']),
              'methods':[],'fields':[],'method_total':0,'field_total':0,'truncated':False}
        methods=[m for m in metadata.methods[t['method_start']:t['method_start']+t['method_count']] if label(m['name'])]
        # Route/getter/readiness definitions before unrelated helpers if capped.
        methods.sort(key=lambda m:(not (m['name'].startswith('get_') or any(w in m['name'].lower() for w in WORDS+STATE_WORDS+('close','back'))),m['name'],m['parameter_count']))
        node['method_total']=len(methods)
        exported_methods=methods[:min(MAX_METHODS,max(0,MAX_TOTAL_METHODS-method_count))]
        for m in exported_methods:
            parameters=[]
            for i in range(min(m['parameter_count'],MAX_PARAMETERS,max(0,MAX_TOTAL_PARAMETERS-parameter_count))):
                ti=struct.unpack_from('<i',metadata.data,po+(m['parameter_start']+i)*12+8)[0]
                parameters.append(resolve(ti));parameter_count+=1
            node['methods'].append({'method':m['name'],'arity':m['parameter_count'],'static':m['static'],
                 'virtual':bool(m['method_flags']&64),'abstract':bool(m['method_flags']&1024),
                 'return_type':resolve(m['return_type_index']),'parameters':parameters,
                 'parameters_truncated':m['parameter_count']>len(parameters)})
            method_count+=1
            if m['name'].startswith('get_') and m['parameter_count']==0 and not m['static']:
                if any(w in m['name'].lower() for w in WORDS+STATE_WORDS+('delegate',)):
                    follow(m['return_type_index'],depth+1)
        fields=[(name,ti) for name,ti in all_fields.get(owner,[]) if label(name)]
        fields.sort(key=lambda f:(not any(w in f[0].lower() for w in WORDS+STATE_WORDS),f[0]))
        node['field_total']=len(fields)
        exported_fields=fields[:min(MAX_FIELDS,max(0,MAX_TOTAL_FIELDS-field_count))]
        for name,ti in exported_fields:
            node['fields'].append({'field':name,'declared_type':resolve(ti)});field_count+=1
            if any(w in name.lower() for w in WORDS+STATE_WORDS):follow(ti,depth+1)
        follow(t['parent_type_index'],depth+1)
        node['truncated']=len(methods)>len(exported_methods) or len(fields)>len(exported_fields) or any(m['parameters_truncated'] for m in node['methods'])
        nodes.append(node)
    return {'purpose':'chat-route-and-loaded-empty-history-definitions','roots':roots,'types':nodes,
            'candidate_total':len(candidates),'candidates_truncated':len(candidates)>12,
            'truncated':truncated or any(n['truncated'] for n in nodes)}


def inspect_bundle(folder,cancelled=lambda:False,expected_hashes=None):
    out=inspect_definitions(folder,cancelled,expected_hashes,collector=collect)
    out.update(tool_version=VERSION,mode='offline-chat-catalog',chat_opened=False,history_read=False,draft_prepared=False)
    return out


def write_report(folder,cancelled=lambda:False):
    out=inspect_bundle(folder,cancelled)
    target=Path(folder).parent/f'rootless-chat-metadata-{VERSION}.json'
    target.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return out,target
