"""One random configured city + online. Real returned visible GeoRecords only.

Unknown/incomplete/offscreen/ambiguous results STOP; no guessed geo IDs, screen
coordinates, device geolocation, broad object search, profiles or message action.
"""
import copy
import json
from assistant_config import ConfigError
import search_online as online
import uikit_navigation as navigation
from uikit_profile_navigation import replace_once as replace

MAX_FRAMES = 900
ERRORS = navigation.ERRORS | {'city-ambiguous', 'city-results-incomplete', 'city-not-found', 'city-query-changed'}
PHASES = navigation.PHASES | {'wait-city', 'query-city', 'scan-city', 'wait-city-return'}
KINDS = navigation.KINDS | {'city'}
DEFAULTS = dict(city_open_attempted=False, city_open_completed=False, city_query_attempted=False,
                city_query_completed=False, city_result_verified=False, city_select_attempted=False,
                city_select_completed=False, city_form_verified=False, city_verified=False,
                city_scan_samples=0, city_visible_rows=0, city_total_rows=0,
                city_matches=0, city_checkpoint='not-checked', city_prepare='not-checked')
PREPARE_STEPS = None  # filled below from the native source (fixed labels only)
CHECKPOINTS = {'not-checked', 'open-picker', 'query', 'results', 'select', 'form', 'complete'}

PREPARE = r'''
 function prepareCity(f,s,getClass){
  const mark=v=>{r.navigation.city_prepare=v;};
  for(const [key,image,ns,name] of [
   ['city','DV.dll','DV','CityFinderViewController'],['cityCell','DV.dll','DV','CityFinderCell'],
   ['geoRecord','DV.dll','DV.Models','GeoRecord'],['searchField','DV.dll','DV','SearchField'],
   ['table','Core.dll','UIKit','TableView'],['tableCell','Core.dll','UIKit','TableCell']]){
   mark('class:'+key);s[key]=getClass(image,ns,name);if(s[key].isNull())throw new Error('metadata');
  }
  mark('hierarchy');
  if(!f.assignable(s.card,s.city)||!f.assignable(s.tableCell,s.cityCell)||!f.assignable(s.view,s.searchField))throw new Error('hierarchy');
  const name=p=>{if(p.isNull())throw new Error('signature');let v='';for(let i=0;i<96;i++){const c=p.add(i).readU8();if(c===0)return v;if(c<32||c>126)throw new Error('signature');v+=String.fromCharCode(c);}throw new Error('signature');};
  const checked=(klass,label,kind,result=null,params=[],inherited=false,byref=false)=>{
   const e={klass,kind,result,params,arity:params.length,cityChecked:true,allowByref:byref};
   e.m=f.method(klass,Memory.allocUtf8String(label),e.arity);
   if(!citySignature(f,e,e.m))throw new Error('signature');
   if(!inherited&&!f.methodClass(e.m).equals(klass))throw new Error('signature');return e;
  };
  mark('method:cityOpen');s.cityOpen=checked(s.people,'ShowRegionPicker',1);
  mark('method:cityTextGet');s.cityTextGet=checked(s.searchField,'get_Text',14);
  mark('method:cityTextSet');s.cityTextSet=checked(s.searchField,'set_Text',1,null,[{kind:14}]);
  mark('method:cityQuery');s.cityQuery=checked(s.city,'get_QueryString',14);
  mark('method:citySearch');s.citySearch=checked(s.city,'OnSearch',1);
  mark('method:citySelect');s.citySelect=checked(s.city,'OnCellSelected',1,null,[{kind:18,klass:s.cityCell},{kind:18,klass:s.geoRecord}]);
  mark('method:geoID');s.geoID=checked(s.geoRecord,'get_GeoID',14);mark('method:geoName');s.geoName=checked(s.geoRecord,'get_Name',14);
  mark('method:geoKind');s.geoKind=checked(s.geoRecord,'get_RecordType',17);
  // GeoType is nested inside GeoRecord, so it cannot be found by namespace/name; take it from the real return type.
  mark('geotype-class');s.geoType=f.classFromType(f.returnType(s.geoKind.m));
  if(s.geoType.isNull()||name(f.className(s.geoType))!=='GeoType'||name(f.classNamespace(s.geoType))!=='')throw new Error('signature');
  s.geoKind.result=s.geoType;
  mark('method:geoFilterName');s.geoFilterName=checked(s.filterModel,'get_GeoRecordName',14);
  mark('method:distanceSet');s.distanceSet=checked(s.filterModel,'set_ByDistance',1,null,[{kind:2}]);
  mark('method:cityItem');s.cityItem=checked(s.cityCell,'get_Item',18,s.geoRecord,[],true);
  mark('item-owner');const owner=f.methodClass(s.cityItem.m);
  if(name(f.imageName(f.classImage(owner)))!=='Core.dll')throw new Error('signature');
  mark('method:cityVisible');s.cityVisible=checked(s.table,'get_VisibleCells',21);
  mark('list-class');s.cityList=f.classFromType(f.returnType(s.cityVisible.m));
  if(s.cityList.isNull()||f.isValueType(s.cityList)||name(f.className(s.cityList))!=='CoreList`1'||
   name(f.classNamespace(s.cityList))!=='Core.Collections'||name(f.imageName(f.classImage(s.cityList)))!=='Core.dll')throw new Error('signature');
  mark('method:cityCount');s.cityCount=checked(s.cityList,'get_Count',8);
  // This exact CoreList<TableCell> indexer is already exercised by profile navigation.
  mark('method:cityAt');s.cityAt=checked(s.cityList,'get_Item',18,s.tableCell,[{kind:8}],false,true);
  mark('method:sectionCount');s.sectionCount=checked(s.table,'get_SectionsCount',8);
  mark('method:sectionRows');s.sectionRows=checked(s.table,'GetSectionItemsCount',8,null,[{kind:8}]);
  mark('method:canSelect');s.canSelect=checked(s.tableCell,'get_CanSelect',2);mark('method:nonSelectable');s.nonSelectable=checked(s.tableCell,'get_NonSelectable',2);
  const field=(klass,label,expected=null)=>{
   const p=f.field(klass,Memory.allocUtf8String(label));
   if(p.isNull()||!f.fieldOwner(p).equals(klass)||(f.fieldFlags(p)&16))throw new Error('signature');
   const t=f.fieldType(p);if(t.isNull()||f.byref(t))throw new Error('signature');
   if(expected&&(f.typeKind(t)!==18||!f.classFromType(t).equals(expected)))throw new Error('signature');return p;
  };
  mark('field:cityInputField');s.cityInputField=field(s.city,'m_SearchField',s.searchField);
  mark('field:cityTableField');s.cityTableField=field(s.city,'m_TableView');
  mark('table-field-type');const tt=f.fieldType(s.cityTableField);s.cityTableClass=f.classFromType(tt);
  if(![18,21].includes(f.typeKind(tt))||s.cityTableClass.isNull()||f.isValueType(s.cityTableClass)||!f.assignable(s.table,s.cityTableClass))throw new Error('signature');
  mark('field:lastCityQuery');s.lastCityQuery=field(s.city,'m_LastSearchText');if(f.typeKind(f.fieldType(s.lastCityQuery))!==14)throw new Error('signature');
  mark('enum-base');const basetype=f.enumBase(s.geoType);
  if(basetype.isNull()||f.typeKind(basetype)!==8)throw new Error('signature');
  mark('enum-city');const city=f.field(s.geoType,Memory.allocUtf8String('CITY'));
  if(city.isNull()||!f.fieldOwner(city).equals(s.geoType)||(f.fieldFlags(city)&(16|64))!==(16|64)||
   f.byref(f.fieldType(city))||f.typeKind(f.fieldType(city))!==17||!f.classFromType(f.fieldType(city)).equals(s.geoType))throw new Error('signature');
  const val=Memory.alloc(4);val.writeS32(-1);f.staticFieldValue(city,val);s.cityEnum=val.readS32();
  if(s.cityEnum<0||s.cityEnum>32767)throw new Error('signature');
  mark('ready');
 }
 function citySignature(f,e,m){
  if(m.isNull()||f.arity(m)!==e.arity)return false;
  const flags=Memory.alloc(4);flags.writeU32(0);if((f.flags(m,flags)&(16|1024))!==0)return false;
  const owner=f.methodClass(m);if(owner.isNull()||(!f.assignable(owner,e.klass)&&!f.assignable(e.klass,owner)))return false;
  const t=f.returnType(m);if(t.isNull()||f.typeKind(t)!==e.kind||
   (f.byref(t)&&!e.allowByref)||(e.result&&!f.classFromType(t).equals(e.result)))return false;
  for(let i=0;i<e.arity;i++){const p=f.param(m,i),a=e.params[i];
   if(p.isNull()||f.byref(p)||f.typeKind(p)!==a.kind||(a.klass&&!f.classFromType(p).equals(a.klass)))return false;}
  return true;
 }
'''
import re as _re
PREPARE_STEPS = {'not-checked'} | set(_re.findall(r"mark\('([^'+]+)'\)", PREPARE)) | {'class:' + k for k in
    ('city', 'cityCell', 'geoRecord', 'searchField', 'table', 'tableCell')}
UTILS = r'''
  const cityArgs=values=>{const p=Memory.alloc(Process.pointerSize*values.length);values.forEach((v,i)=>p.add(i*Process.pointerSize).writePointer(v));return p;};
  const cityInt=(entry,obj,args=ptr(0))=>{const box=call(entry,obj,args);if(box.isNull())fail('signature-mismatch');own(box);const p=f.unbox(box);if(p.isNull())fail('signature-mismatch');return p.readS32();};
  const cityIndex=(entry,obj,i)=>{const p=Memory.alloc(4);p.writeS32(i);return call(entry,obj,cityArgs([p]));};
  const cityString=obj=>{if(obj.isNull())return null;own(obj);const length=f.stringLength(obj);if(length<0||length>256)fail('signature-mismatch');const p=f.stringChars(obj);if(p.isNull())fail('signature-mismatch');return length===0?'':p.readUtf16String(length);};
  const cityNorm=text=>text===null?'':text.normalize('NFC').trim().toLowerCase().replace(/ё/g,'е');
  const cityLike=text=>{const a=cityNorm(text),b=cityNorm(cityWanted);return b.length>0&&a.startsWith(b);};
  const cityScoped=body=>{const start=held.length;try{return body();}finally{
   for(const h of held.splice(start)){try{f.release(h);n.handles_released++;}catch(_){n.cleanup_failed=true;}}
   if(n.cleanup_failed)fail('cleanup-failed');
  }};
  const cityAttached=(view,table)=>cityScoped(()=>{
   if(view.isNull()||!f.assignable(s.view,f.objectClass(view))||bool(s.hidden,view)||!bool(s.interactive,view))return false;
   let cursor=view,seenTable=false;const seen=new Set();
   for(let i=0;i<32;i++){
    if(cursor.isNull())return false;const key=cursor.toString();if(seen.has(key))fail('view-parent-cycle');seen.add(key);own(cursor);
    if(cursor.equals(table))seenTable=true;if(cursor.equals(window))return seenTable;
    cursor=call(s.parent,cursor);
   }fail('view-parent-depth-limit');
  });
  const cityRawField=(obj,field)=>{if(fixedCancellationRequested)fail('cancelled');if(Date.now()>deadline)fail('frame-budget');const p=Memory.alloc(Process.pointerSize);p.writePointer(ptr(0));f.fieldValue(obj,field,p);return p.readPointer();};
  const cityRows=table=>{
   const sections=cityInt(s.sectionCount,table);if(sections<1||sections>8)fail('city-results-incomplete');
   let total=0;for(let i=0;i<sections;i++){const p=Memory.alloc(4);p.writeS32(i);const c=cityInt(s.sectionRows,table,cityArgs([p]));if(c<0||c>500)fail('city-results-incomplete');total+=c;}
   return Math.min(total,200);
  };
  const citySnapshot=current=>{
   const input=fieldObject(current,s.cityInputField,s.searchField);
   if(cityString(call(s.cityTextGet,input))!==cityWanted||cityString(call(s.cityQuery,current))!==cityWanted)fail('city-query-changed');
   const last=cityString(cityRawField(current,s.lastCityQuery));if(last!==cityWanted)return null;
   const table=cityRawField(current,s.cityTableField);if(table.isNull())return null;own(table);
   if(!f.assignable(s.cityTableClass,f.objectClass(table))||!cityAttached(table,table))fail('screen-not-ready');
   const list=call(s.cityVisible,table);if(list.isNull())return null;own(list);
   if(!f.objectClass(list).equals(s.cityList))fail('unexpected-object');
   const count=cityInt(s.cityCount,list),total=cityRows(table);
   if(count<0)fail('city-results-incomplete');n.city_visible_rows=Math.min(count,12);n.city_total_rows=total;
   if(count===0)return null;const scan=Math.min(count,12);
   const records=[],matches=[];const seen=new Set();
   for(let i=0;i<scan;i++)cityScoped(()=>{
    const cell=cityIndex(s.cityAt,list,i);if(cell.isNull()||!f.objectClass(cell).equals(s.cityCell))fail('city-results-incomplete');own(cell);
    if(!cityAttached(cell,table)||!bool(s.canSelect,cell)||bool(s.nonSelectable,cell))fail('screen-not-ready');
    const record=call(s.cityItem,cell);if(record.isNull()||!f.objectClass(record).equals(s.geoRecord))fail('unexpected-object');own(record);
    const id=cityString(call(s.geoID,record)),name=cityString(call(s.geoName,record)),kind=cityInt(s.geoKind,record);
    if(!id||seen.has(id))fail('city-results-incomplete');seen.add(id);
    const item={cell:cell.toString(),record:record.toString(),id,name,kind,index:i};records.push(item);
    if(cityLike(name)&&kind===s.cityEnum)matches.push(item);
    if(!call(s.cityItem,cell).equals(record)||!cityIndex(s.cityAt,list,i).equals(cell))fail('identity-changed');
   });
   if(cityInt(s.cityCount,list)!==count||cityRows(table)!==total||!call(s.cityVisible,table).equals(list))fail('identity-changed');
   n.city_matches=Math.min(matches.length,8);
   if(matches.length<1)return null;
   return {fingerprint:JSON.stringify(records),match:matches[0],table,list};
  };
'''
PHASE_CODE = r'''
   if(n.phase==='wait-city'){
    if(k==='filters'){if(!current.equals(target(state.card)))fail('identity-changed');return;}
    if(k!=='city')fail('unexpected-screen');saveOnline('cityFinder',current);n.phase='query-city';return;
   }
   if(n.phase==='query-city'){
    if(k!=='city'||!current.equals(target(state.cityFinder)))fail('identity-changed');
    n.city_checkpoint='query';const input=fieldObject(current,s.cityInputField,s.searchField);
    if(!cityAttached(input,input))fail('screen-not-ready');
    const text=f.newString(Memory.allocUtf8String(cityWanted));if(text.isNull())fail('unexpected-object');own(text);
    n.city_query_attempted=true;call(s.cityTextSet,input,cityArgs([text]));
    n.ui_text_read=true;if(cityString(call(s.cityTextGet,input))!==cityWanted)fail('city-query-changed');
    call(s.citySearch,current);n.city_query_completed=true;state.cityNext=Date.now()+1000;n.phase='scan-city';return;
   }
   if(n.phase==='scan-city'){
    if(k!=='city'||!current.equals(target(state.cityFinder)))fail('identity-changed');
    n.city_checkpoint='results';if(Date.now()<state.cityNext)return;
    const found=citySnapshot(current);
    if(found===null){state.cityFingerprint=null;state.cityNext=Date.now()+1000;return;}
    if(state.cityFingerprint!==found.fingerprint){state.cityFingerprint=found.fingerprint;n.city_scan_samples=1;state.cityNext=Date.now()+1000;return;}
    n.city_scan_samples=2;n.city_result_verified=true;
    const cell=cityIndex(s.cityAt,found.list,found.match.index);own(cell);const record=call(s.cityItem,cell);own(record);
    if(cell.toString()!==found.match.cell||record.toString()!==found.match.record||
     cityString(call(s.geoID,record))!==found.match.id||!cityLike(cityString(call(s.geoName,record)))||
     cityInt(s.geoKind,record)!==s.cityEnum||!cityAttached(cell,found.table))fail('identity-changed');
    state.cityID=found.match.id;n.city_checkpoint='select';n.city_select_attempted=true;
    call(s.citySelect,current,cityArgs([cell,record]));n.city_select_completed=true;n.phase='wait-city-return';return;
   }
   if(n.phase==='wait-city-return'){
    if(k==='city'){if(!current.equals(target(state.cityFinder)))fail('identity-changed');return;}
    if(k!=='filters'||!current.equals(target(state.card)))fail('identity-changed');
    n.city_checkpoint='form';
    const people=fieldObject(current,s.peopleField,s.people);if(!people.equals(target(state.cityPeople))||!checkView(people)||!bool(s.formReady,people)||!bool(s.formValid,people))fail('screen-not-ready');
    const model=filter(s.formFilter,people);
    if(code(s.geoGet)(model)!==state.cityID||!cityLike(cityString(call(s.geoFilterName,model))))fail('identity-changed');
    if(bool(s.distanceGet,model)){
     const value=Memory.alloc(1);value.writeU8(0);call(s.distanceSet,model,cityArgs([value]));
    }
    if(bool(s.distanceGet,model))fail('screen-not-ready');
    state.location=location(model);state.cityDone=true;n.city_form_verified=true;n.phase='confirm-filters';return;
   }
'''
OPEN = r'''
    if(!state.cityDone){
     n.city_checkpoint='open-picker';const people=fieldObject(current,s.peopleField,s.people);
     if(!checkView(people)||!bool(s.formReady,people)||!bool(s.formValid,people))fail('screen-not-ready');
     saveOnline('cityPeople',people);n.city_open_attempted=true;call(s.cityOpen,people);n.city_open_completed=true;n.phase='wait-city';return;
    }
'''


def check_city(city):
    if not isinstance(city,str) or not 1<=len(city)<=80 or city!=city.strip() or any(ord(c)<32 or 127<=ord(c)<160 or 0xD800<=ord(c)<=0xDFFF for c in city):
        raise ConfigError('Недопустимое название города.')
    return city


def build(city):
    city = check_city(city)
    s = online.FUNCTION
    s = replace(s, ' function prepareNavigation(', PREPARE + '\n function prepareNavigation(')
    s = replace(s, 'r.navigation=emptyNavigation();', 'r.navigation=emptyNavigation();Object.assign(r.navigation,' + json.dumps(DEFAULTS) + ');const cityWanted='+json.dumps(city)+';')
    s = replace(s, 'prepareOnline(f,setup.navigation,getClass);', 'prepareOnline(f,setup.navigation,getClass);prepareCity(f,setup.navigation,getClass);')
    s = replace(s, '"il2cpp_string_chars"]', '"il2cpp_string_chars","il2cpp_string_new","il2cpp_field_static_get_value","il2cpp_class_enum_basetype"]')
    s = replace(s, "stringLength:bind('string_length'", "newString:bind('string_new','pointer',['pointer']),staticFieldValue:bind('field_static_get_value','void',['pointer','pointer']),enumBase:bind('class_enum_basetype','pointer',['pointer']),\n stringLength:bind('string_length'")
    s = replace(s, 'if(entry.onlineChecked){', "if(entry.cityChecked){if(!citySignature(f,entry,m))fail('signature-mismatch');}\n   else if(entry.onlineChecked){")
    # The base virtual check rejects byref except the already-confirmed exact CoreList indexer.
    s = replace(s, '||f.byref(f.returnType(m)))fail', '||(f.byref(f.returnType(m))&&!entry.allowByref))fail')
    s = replace(s, '  const kind=obj=>{', UTILS + '\n  const kind=obj=>{')
    s = replace(s, "if(!ex.readPointer().isNull())fail('managed-exception');return out;",
                "if(!ex.readPointer().isNull())fail('managed-exception');if(fixedCancellationRequested)fail('cancelled');if(Date.now()>deadline)fail('frame-budget');return out;")

    # The real picker is presented by the people form (a child controller), not by the card/root list.
    s = replace(s, "   const current=resolve(candidate);if(current.isNull())return;\n   const k=kind(current);",
                "   let current=resolve(candidate);if(current.isNull())return;\n   let k=kind(current);\n"
                "   if(['wait-city','query-city','scan-city','wait-city-return'].includes(n.phase)&&k==='filters'&&current.equals(target(state.card))&&!state.cityPeople.isNull()){\n"
                "    const hosted=modal(target(state.cityPeople));\n"
                "    if(!hosted.isNull()&&f.objectClass(hosted).equals(s.city)){current=hosted;k='city';n.controller_path.push('city');}\n   }")
    s = replace(s, '   const root=call(s.windowRoot,window);', "   if(n.phase==='scan-city'&&Date.now()<state.cityNext)return;\n   const root=call(s.windowRoot,window);")
    s = replace(s, "if(klass.equals(s.search))return 'search';", "if(klass.equals(s.city))return 'city';if(klass.equals(s.search))return 'search';")
    s = replace(s, "if(k==='search'||k==='filters'){", "if(k==='search'||k==='filters'||k==='city'){")
    s = replace(s, "!['search','filters'].includes(k)", "!['search','filters','city'].includes(k)")
    s = replace(s, "   if(n.phase==='confirm-filters'){", PHASE_CODE + "\n   if(n.phase==='confirm-filters'){")
    s = replace(s, "    n.settings_checkpoint='people-view';", OPEN + "\n    n.settings_checkpoint='people-view';")
    s = replace(s, "n.online_verified=true;n.location_preserved=true;n.settings_checkpoint='complete';", "if(code(s.geoGet)(actual)!==state.cityID||!cityLike(cityString(call(s.geoFilterName,actual)))||bool(s.distanceGet,actual))fail('identity-changed');\n    n.online_verified=true;n.location_preserved=true;n.settings_checkpoint='complete';n.city_verified=true;n.city_checkpoint='complete';")
    s = replace(s, "['card','origin','onlineCM']", "['card','origin','onlineCM','cityFinder','cityPeople']")
    s = replace(s, json.dumps(sorted(navigation.ERRORS)), json.dumps(sorted(ERRORS)))
    s = replace(s, 'r.navigation.frames>=180', 'r.navigation.frames>=900')
    s = replace(s, '},16000);', '},30000);')
    return s


def validate(value):
    checked = copy.deepcopy(value)
    n = checked['navigation']
    extra = {k:n.pop(k) for k in DEFAULTS}
    for key,default in DEFAULTS.items():
        if type(default) is bool and type(extra[key]) is not bool:
            raise ValueError('Invalid city flag')
    for key,limit in [('city_scan_samples',2),('city_visible_rows',12),('city_total_rows',200),('city_matches',8)]:
        if type(extra[key]) is not int or not 0<=extra[key]<=limit:
            raise ValueError('Invalid city counter')
    if extra['city_checkpoint'] not in CHECKPOINTS or extra['city_prepare'] not in PREPARE_STEPS:
        raise ValueError('Invalid city checkpoint')
    online.validate(checked, max_frames=MAX_FRAMES, phases=PHASES, errors=ERRORS, kinds=KINDS, allow_ui_text=True)
    if extra['city_query_completed'] and not n['ui_text_read']:
        raise ValueError('Missing query text check')
    if n['ui_text_read'] and not extra['city_query_attempted']:
        raise ValueError('UI text read outside city query')
    chain=['city_open_attempted','city_open_completed','city_query_attempted','city_query_completed',
           'city_result_verified','city_select_attempted','city_select_completed','city_form_verified','city_verified']
    for earlier,later in zip(chain,chain[1:]):
        if extra[later] and not extra[earlier]:
            raise ValueError('Out-of-order city operation')
    if extra['city_result_verified'] and (extra['city_scan_samples']!=2 or not 1<=extra['city_matches']<=8 or not 1<=extra['city_visible_rows']<=12 or extra['city_visible_rows']>extra['city_total_rows']):
        raise ValueError('City selected without complete stable unique results')
    if n['stage']=='navigation-ready' and extra['city_prepare']!='ready':
        raise ValueError('City metadata was not ready')
    if n['apply_attempted'] and not extra['city_form_verified']:
        raise ValueError('Applied without checking selected city')
    if (n['stage']=='navigation-ready') != (extra['city_verified'] and extra['city_checkpoint']=='complete'):
        raise ValueError('Missing applied city evidence')
    return value


def run(executable, folder, city, cancelled=lambda: False):
    from assistant_lock import operation_lock
    from one_chat_device import capture
    source = build(city)
    with operation_lock():
        return capture(executable, folder, cancelled,
                       inspector=lambda port,token,cancel,expected: online.inspect(
                           port,token,cancel,source_function=source,validator=validate,timeout=40))
