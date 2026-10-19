"""Strict, read-only IL2CPP v31 definition reader. No code/pointer resolution.

Reads metadata names, image/type ownership and method names/arity only. Does not
read managed string literals, user data, method bodies, process memory or an APK
signature/key. Supports v31 exclusively; unknown layouts fail closed.

Layout reference (consulted, not vendored):
https://github.com/Perfare/Il2CppDumper/blob/master/Il2CppDumper/Il2Cpp/MetadataClass.cs
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct

MAX_BYTES=128*1024*1024
MAX_RECORDS=1_000_000
HEADER_BYTES=256


class MetadataError(ValueError):
    pass


class Metadata31:
    def __init__(self,data:bytes):
        if not HEADER_BYTES<=len(data)<=MAX_BYTES:
            raise MetadataError('Metadata size outside supported bounds')
        self.data=data
        if struct.unpack_from('<II',data)!=(0xFAB11BAF,31):
            raise MetadataError('Only standard IL2CPP metadata v31 is supported')
        h=struct.unpack_from('<64I',data)
        self.strings=self._section(h[6],h[7],1)
        self._method_bytes=self._section(h[12],h[13],36)
        self._type_bytes=self._section(h[40],h[41],88)
        self._image_bytes=self._section(h[42],h[43],40)
        occupied=sorted((off,off+size) for off,size in (self.strings,self._method_bytes,self._type_bytes,self._image_bytes) if size)
        if any(right[0]<left[1] for left,right in zip(occupied,occupied[1:])):
            raise MetadataError('Overlapping definition sections')
        self.methods=[]
        for row in self._rows(self._method_bytes,'<IiiiiiI4H'):
            self.methods.append({'name':self._string(row[0]),'declaring_type':row[1],
                                 'return_type_index':row[2],'parameter_start':row[4],'method_flags':row[7],
                                 'parameter_count':row[-1],'static':bool(row[7]&0x10)})
        self.types=[]
        for row in self._rows(self._type_bytes,'<II14i8HII'):
            first,n=row[9],row[16]
            if n and not 0<=first<=len(self.methods)-n:
                raise MetadataError('Method ownership range outside table')
            if not n and not -1<=first<=len(self.methods):
                raise MetadataError('Invalid empty method range')
            self.types.append({'name':self._string(row[0]),'namespace':self._string(row[1]),
                               'byval_type_index':row[2],'declaring_type_index':row[3],'parent_type_index':row[4],
                               'method_start':first,'method_count':n,'image':None})
        self.images=[]
        for row in self._rows(self._image_bytes,'<IiiIiIiIiI'):
            first,n=row[2],row[3]
            if not 0<=first<=len(self.types)-n:
                raise MetadataError('Type ownership range outside table')
            image=self._string(row[0]);self.images.append(image)
            for t in self.types[first:first+n]:
                if t['image'] is not None:
                    raise MetadataError('Overlapping type ownership')
                t['image']=image
        if len(self.images)!=len(set(self.images)) or any(t['image'] is None for t in self.types):
            raise MetadataError('Ambiguous image ownership')
        owners=set()
        for index,t in enumerate(self.types):
            for mi in range(t['method_start'],t['method_start']+t['method_count']):
                if mi in owners or self.methods[mi]['declaring_type']!=index:
                    raise MetadataError('Invalid method declaring type')
                owners.add(mi)
        if len(owners)!=len(self.methods):
            raise MetadataError('Unowned method definitions')

    @classmethod
    def load(cls,path):
        path=Path(path)
        if path.stat().st_size>MAX_BYTES:
            raise MetadataError('Metadata file too large')
        with path.open('rb') as f:
            data=f.read(MAX_BYTES+1)
        return cls(data)

    def _section(self,offset,size,stride):
        if offset<HEADER_BYTES or offset>len(self.data) or size>len(self.data)-offset or size%stride or (stride>1 and size//stride>MAX_RECORDS):
            raise MetadataError('Invalid definition section')
        return offset,size

    def _rows(self,section,fmt):
        offset,size=section;stride=struct.calcsize(fmt)
        for pos in range(offset,offset+size,stride):
            yield struct.unpack_from(fmt,self.data,pos)

    def _string(self,index):
        off,size=self.strings
        if not 0<=index<size:
            raise MetadataError('String index outside metadata name table')
        end=self.data.find(b'\0',off+index,min(off+size,off+index+1025))
        if end<0:
            raise MetadataError('Unterminated or overlong metadata name')
        try:
            return self.data[off+index:end].decode('utf-8',errors='strict')
        except UnicodeDecodeError as e:
            raise MetadataError('Invalid metadata name encoding') from e

    def check_catalog(self,types,methods):
        # Return fixed requested labels only; never dump all application types.
        hits={key:[i for i,t in enumerate(self.types) if (t['image'],t['namespace'],t['name'])==(image,ns,name)]
              for key,image,ns,name in types}
        result={'metadata_version':31,'sha256':hashlib.sha256(self.data).hexdigest(),
                'image_count':len(self.images),'type_count':len(self.types),'method_count':len(self.methods),
                'known_types':{k:len(v)==1 for k,v in hits.items()},'known_methods':{},'method_static':{}}
        for key,name,arity in methods:
            label=f'{key}.{name}/{arity}';matches=[]
            if key not in hits:
                raise MetadataError('Method references unknown catalog type')
            if len(hits[key])==1:
                t=self.types[hits[key][0]]
                matches=[m for m in self.methods[t['method_start']:t['method_start']+t['method_count']]
                         if m['name']==name and m['parameter_count']==arity]
            result['known_methods'][label]=len(matches)==1
            result['method_static'][label]=matches[0]['static'] if len(matches)==1 else None
        result['catalog_complete']=all(result['known_types'].values()) and all(result['known_methods'].values())
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('metadata',type=Path)
    parser.add_argument('--out',type=Path,required=True,help='Local report with fixed catalog names only')
    args=parser.parse_args()
    from uikit_profile import TYPES,METHODS,PROFILE_ID
    report=Metadata31.load(args.metadata).check_catalog(TYPES,METHODS)
    report['profile_id']=PROFILE_ID
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Fixed catalog complete:',report['catalog_complete'])
    return 0 if report['catalog_complete'] else 1


if __name__=='__main__':
    raise SystemExit(main())
