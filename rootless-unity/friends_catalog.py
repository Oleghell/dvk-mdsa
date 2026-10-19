"""Bounded, offline APK definition catalogue. Never reads app data or invokes code."""
import hashlib,json,re,struct,zipfile
from pathlib import Path
from offline_metadata import Metadata31,MAX_BYTES,MetadataError
from test_device import HASHES

VERSION='0.3.9'
MAX_APK_BYTES=1024**3
MAX_ENTRIES=100000
LIMIT=128
SAFE=re.compile(r'[A-Za-z_<][A-Za-z0-9_.`<>+]*\Z')

class CatalogError(ValueError):pass

def label(value):
    return isinstance(value,str) and len(value)<=128 and bool(SAFE.fullmatch(value))

def definition_fields(metadata):
    # Verified v31 layout: MetadataClass.cs in Perfare/Il2CppDumper.
    # Read definitions only; never read field defaults, literals or app objects.
    h=struct.unpack_from('<64I',metadata.data);offset,size=h[24:26]
    if not size:
        if any(row[18] for row in metadata._rows(metadata._type_bytes,'<II14i8HII')):raise MetadataError('Missing field definitions')
        return
    section=metadata._section(offset,size,12)
    for other in (metadata.strings,metadata._method_bytes,metadata._type_bytes,metadata._image_bytes):
        if other[1] and offset<other[0]+other[1] and other[0]<offset+size:raise MetadataError('Overlapping field definitions')
    field_count=size//12;seen=bytearray(field_count)
    for index,row in enumerate(metadata._rows(metadata._type_bytes,'<II14i8HII')):
        first,count=row[8],row[18]
        if count and not 0<=first<=field_count-count:raise MetadataError('Invalid field ownership')
        if not count and not -1<=first<=field_count:raise MetadataError('Invalid empty field range')
        for fi in range(first,first+count):
            if seen[fi]:raise MetadataError('Duplicate field ownership')
            seen[fi]=1
            name,type_index,token=struct.unpack_from('<IiI',metadata.data,offset+fi*12)
            if type_index<0:raise MetadataError('Invalid field type index')
            yield index,metadata._string(name),type_index
    if sum(seen)!=field_count:raise MetadataError('Unowned field definitions')

def collect(metadata):
    groups={key:{'total':0,'truncated':False,'definitions':[]} for key in ('friend_methods','user_getters','profile_getters','friend_fields','user_fields','profile_fields')}
    def add(key,descriptor):
        group=groups[key];group['total']+=1
        if len(group['definitions'])<LIMIT:group['definitions'].append(descriptor)
        else:group['truncated']=True
    for t in metadata.types:
        image=t['image'];ns=t['namespace'];name=t['name']
        if not image.startswith('DV') or not image.endswith('.dll'):continue
        if not label(image) or not label(name) or (ns!='' and not label(ns)):continue
        user=(image,ns,name)==('DV.dll','DV.Models','User')
        profile=(image,ns,name)==('DV.Profile.dll','DV.Profiles','ProfileViewController')
        for m in metadata.methods[t['method_start']:t['method_start']+t['method_count']]:
            mn=m['name']
            if not label(mn):continue
            descriptor={'image':image,'namespace':ns,'type':name,'method':mn,'arity':m['parameter_count'],'static':m['static']}
            # Only definition names: no literal strings, field values or pointers.
            if 'friend' in (ns+'.'+name+'.'+mn).lower():add('friend_methods',descriptor)
            if mn.startswith('get_') and m['parameter_count']==0 and not m['static']:
                if user:add('user_getters',descriptor)
                if profile:add('profile_getters',descriptor)
    for owner,field,type_index in definition_fields(metadata):
        t=metadata.types[owner];image=t['image'];ns=t['namespace'];name=t['name']
        if not image.startswith('DV') or not image.endswith('.dll'):continue
        if not label(image) or not label(name) or (ns!='' and not label(ns)) or not label(field):continue
        descriptor={'image':image,'namespace':ns,'type':name,'field':field,'type_index':type_index}
        if 'friend' in (ns+'.'+name+'.'+field).lower():add('friend_fields',descriptor)
        if (image,ns,name)==('DV.dll','DV.Models','User'):add('user_fields',descriptor)
        if (image,ns,name)==('DV.Profile.dll','DV.Profiles','ProfileViewController'):add('profile_fields',descriptor)
    for group in groups.values():group['definitions'].sort(key=lambda d:(d['image'],d['namespace'],d['type'],d.get('method',d.get('field','')),d.get('arity',0),d.get('static',False)))
    return groups

def inspect_bundle(folder,cancelled=lambda:False,expected_hashes=None):
    expected=HASHES if expected_hashes is None else expected_hashes
    report={'tool_version':VERSION,'mode':'offline-friends-catalog','status':'not-run','ui_actions_attempted':False,'messages_sent':0,'method_values_read':False,'catalog':None}
    try:
        entries=[]
        for filename,digest in expected.items():
            if cancelled():raise CatalogError('cancelled')
            if filename not in ('base.apk','split-001.apk'):raise CatalogError('invalid-bundle')
            path=Path(folder)/filename
            if not path.is_file() or path.stat().st_size>MAX_APK_BYTES:raise CatalogError('apk-missing-or-too-large')
            h=hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda:stream.read(1024*1024),b''):
                    if cancelled():raise CatalogError('cancelled')
                    h.update(chunk)
            if h.hexdigest()!=digest:raise CatalogError('apk-hash-mismatch')
            with zipfile.ZipFile(path) as archive:
                infos=archive.infolist()
                if len(infos)>MAX_ENTRIES:raise CatalogError('archive-limit')
                for info in infos:
                    if info.filename.rsplit('/',1)[-1]=='global-metadata.dat':
                        if info.is_dir() or not 256<=info.file_size<=MAX_BYTES:raise CatalogError('metadata-size')
                        entries.append((path,info.filename))
        if len(entries)!=1:raise CatalogError('metadata-missing' if not entries else 'metadata-ambiguous')
        if cancelled():raise CatalogError('cancelled')
        path,entry=entries[0]
        with zipfile.ZipFile(path) as archive,archive.open(entry) as stream:data=stream.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES:raise CatalogError('metadata-size')
        metadata=Metadata31(data)
        if cancelled():raise CatalogError('cancelled')
        report['catalog']=collect(metadata)
        if cancelled():raise CatalogError('cancelled')
        report['metadata_version']=31;report['status']='catalog-ready'
    except CatalogError as e:report.update(status='catalog-stopped',reason=str(e),catalog=None)
    except MetadataError:report.update(status='catalog-stopped',reason='metadata-unsupported-or-invalid')
    except (OSError,zipfile.BadZipFile,RuntimeError,ValueError,EOFError):report.update(status='catalog-stopped',reason='apk-or-metadata-unreadable')
    return report

def write_report(folder,cancelled=lambda:False):
    report=inspect_bundle(folder,cancelled)
    target=Path(folder).parent/f'rootless-friends-metadata-{VERSION}.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report,target
