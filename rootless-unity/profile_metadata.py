"""Read-only, finite profile-metadata preflight, no UI observer or action execution.

0.3.0 real report failed before observer installation. This probe identifies the
closed metadata checkpoint without exposing raw errors, objects or user data.
The existing 0.2.3 and 0.3.0 workflows remain unchanged.
"""
import copy,json
import uikit_root as root
import uikit_navigation as base
from uikit_profile_navigation import EXTRA_APIS

VERSION='0.3.1'
CHECKPOINTS={'base-method:lastView', 'profile-class:cell', 'resolve-api', 'base-class:dv', 'base-class:vc', 'base-class:uiNav', 'base-method:hasPresented', 'profile-method:childCount', 'base-method:dvTransition', 'profile-method:entryItem', 'base-method:dismissing', 'base-method:uiCurrent', 'base-method:cancel', 'base-method:hidden', 'base-method:interactive', 'base-class:appRoot', 'profile-class:table', 'base-method:isPresented', 'base-class:view', 'profile-method:children', 'base-class:profile', 'base-method:top', 'modal-item', 'profile-method:visibleItem', 'assemblies', 'base-method:nearestPresenter', 'profile-class:resource', 'profile-method:cellEntry', 'profile-method:enumerator', 'profile-nested', 'base-method:tabCurrent', 'base-hierarchy', 'base-method:presenting', 'visible-list-class', 'base-method:windowRoot', 'base-method:presented', 'profile-method:next', 'profile-method:visibleCount', 'profile-class:user', 'base-class:tabs', 'profile-method:visible', 'base-class:uiContainer', 'base-method:parent', 'profile-method:selfUser', 'profile-class:searchTable', 'profile-method:contentUser', 'iterator-class', 'profile-class:tableCell', 'base-method:loading', 'profile-method:promo', 'profile-method:scroll', 'profile-class:entry', 'profile-method:child', 'modal-count', 'profile-class:avatar', 'base-class:dvNav', 'entry-list-class', 'base-method:viewController', 'profile-method:avatarUser', 'base-class:dvContainer', 'base-class:search', 'ready', 'profile-method:recordEntries', 'profile-method:entryCount', 'profile-class:content', 'profile-method:open', 'base-method:rootNav', 'profile-rows', 'base-method:uiTransition', 'base-method:viewOf', 'not-started', 'profile-method:currentContent', 'profile-class:entryInterface', 'base-method:dvCurrent', 'modal-class', 'profile-method:cellAvatar', 'profile-method:rowItems', 'profile-method:profileChecked', 'base-method:hasView', 'base-class:card', 'profile-method:entryUser'}
FAILURES={'none','metadata','signature','hierarchy','return-type','native-call-failed'}
DETAILS={'checkpoint','failure','nested_types_found','method_found','expected_arity','actual_arity',
         'expected_return_kind','actual_return_kind','owner_matches','return_class_matches'}
MARK=r"""
 function mark(value){r.profile_metadata.checkpoint=value;Object.assign(r.profile_metadata,{method_found:null,expected_arity:null,actual_arity:null,expected_return_kind:null,actual_return_kind:null,owner_matches:null,return_class_matches:null});}
"""
PREPARE=r'''

 function prepareProfile(f,s,getClass,get,signature){
  const required={table:['Core.dll','UIKit','TableView'],tableCell:['Core.dll','UIKit','TableCell'],
   searchTable:['DV.Search.dll','DV.Search','SearchTableView'],cell:['DV.Search.dll','DV','SearchCell'],
   entry:['DV.Search.dll','DV.Search','SearchEntry'],entryInterface:['DV.Search.dll','DV.Search','ISearchEntry'],
   avatar:['DV.dll','DV','AvatarView'],resource:['DV.dll','DV.Common','ResourceImageView'],
   user:['DV.dll','DV.Models','User'],content:['DV.Profile.dll','DV.Profiles','ProfileViewController']};
  for(const [key,args] of Object.entries(required)){mark('profile-class:'+key);s[key]=getClass(...args);if(s[key].isNull())throw new Error('metadata');}
  const name=p=>{if(p.isNull())throw new Error('metadata');let out='';for(let i=0;i<96;i++){const c=p.add(i).readU8();if(c===0)return out;if(c<32||c>126)throw new Error('metadata');out+=String.fromCharCode(c);}throw new Error('metadata');};
  const typeName=(k,ns,n)=>!k.isNull()&&name(f.className(k))===n&&name(f.classNamespace(k))===ns&&name(f.imageName(f.classImage(k)))==='Core.dll';
  mark('profile-nested');const nested={};const cursor=Memory.alloc(Process.pointerSize);cursor.writePointer(ptr(0));
  for(let i=0;i<64;i++){const k=f.nested(s.searchTable,cursor);if(k.isNull())break;
   const label=name(f.className(k));if(['LineCell','BlockACell','BlockBCell','LineRecord','BlockARecord','BlockBRecord','RowRecord'].includes(label)){
    if(!f.declaring(k).equals(s.searchTable)||name(f.classNamespace(k))!=='')throw new Error('metadata');nested[label]=k;r.profile_metadata.nested_types_found=Object.keys(nested).length;
   }
   if(i===63)throw new Error('metadata');
  }
  mark('profile-rows');if(Object.keys(nested).length!==7)throw new Error('metadata');s.rows=[nested.LineCell,nested.BlockACell,nested.BlockBCell];
  s.rowRecords=[nested.LineRecord,nested.BlockARecord,nested.BlockBRecord];s.record=nested.RowRecord;
  const checked=(klass,label,kind,result=null,args=[],unboxed=false,ownerExact=true)=>{
   const m=f.method(klass,Memory.allocUtf8String(label),args.length),bits=Memory.alloc(4);bits.writeU32(0);
   r.profile_metadata.method_found=!m.isNull();if(!m.isNull()){r.profile_metadata.actual_arity=f.arity(m);r.profile_metadata.actual_return_kind=f.typeKind(f.returnType(m));}r.profile_metadata.expected_arity=args.length;r.profile_metadata.expected_return_kind=kind;
   if(m.isNull()||f.arity(m)!==args.length||(f.flags(m,bits)&(16|1024))!==0||f.typeKind(f.returnType(m))!==kind||f.byref(f.returnType(m)))throw new Error('signature');
   const owner=f.methodClass(m);r.profile_metadata.owner_matches=!owner.isNull()&&(ownerExact?owner.equals(klass):!!f.assignable(owner,klass));if(owner.isNull()||(ownerExact?!owner.equals(klass):!f.assignable(owner,klass)))throw new Error('signature');
   if(result)r.profile_metadata.return_class_matches=f.classFromType(f.returnType(m)).equals(result);
   if(result&&!f.classFromType(f.returnType(m)).equals(result))throw new Error('signature');
   for(let i=0;i<args.length;i++){const t=f.param(m,i);if(t.isNull()||f.byref(t)||f.typeKind(t)!==args[i].kind||(args[i].klass&&!f.classFromType(t).equals(args[i].klass)))throw new Error('signature');}
   return {m,klass,kind,arity:args.length,params:args,result,unboxed};
  };
  mark('profile-method:profileChecked');s.profileChecked=checked;
  mark('profile-method:scroll');s.scroll=checked(s.search,'get_ScrollView',18);
  mark('profile-method:visible');s.visible=checked(s.table,'get_VisibleCells',21);
  s.visibleClass=f.classFromType(f.returnType(s.visible.m));
  mark('visible-list-class');if(f.isValueType(s.visibleClass)||!typeName(s.visibleClass,'Core.Collections','CoreList`1'))throw new Error('signature');
  mark('profile-method:visibleCount');s.visibleCount=checked(s.visibleClass,'get_Count',8);
  mark('profile-method:visibleItem');s.visibleItem=checked(s.visibleClass,'get_Item',18,s.tableCell,[{kind:8}]);
  mark('profile-method:children');s.children=checked(s.view,'get_Subviews',21);
  s.iterator=f.classFromType(f.returnType(s.children.m));const owner=f.declaring(s.iterator);
  mark('iterator-class');if(!f.isValueType(s.iterator)||!typeName(s.iterator,'','Iterator')||!typeName(owner,'Core.Collections.StructBased','ShortList`1')||!f.isValueType(owner))throw new Error('signature');
  mark('profile-method:enumerator');s.enumerator=checked(s.iterator,'GetEnumerator',21,s.iterator,[],true);
  mark('profile-method:childCount');s.childCount=checked(s.iterator,'get_Count',8,null,[],true);
  mark('profile-method:next');s.next=checked(s.iterator,'MoveNext',2,null,[],true);mark('profile-method:child');s.child=checked(s.iterator,'get_Current',18,s.view,[],true);
  mark('profile-method:rowItems');s.rowItems=s.rows.map((row,i)=>checked(row,'get_Item',18,s.rowRecords[i],[],false,false));
  mark('profile-method:recordEntries');s.recordEntries=checked(s.record,'get_Items',21);s.entryList=f.classFromType(f.returnType(s.recordEntries.m));
  mark('entry-list-class');if(f.isValueType(s.entryList)||!typeName(s.entryList,'Core.Collections','CoreList`1'))throw new Error('signature');
  mark('profile-method:entryCount');s.entryCount=checked(s.entryList,'get_Count',8);mark('profile-method:entryItem');s.entryItem=checked(s.entryList,'get_Item',18,s.entry,[{kind:8}]);
  mark('profile-method:promo');s.promo=checked(s.record,'IsPromoEntry',2,null,[{kind:18,klass:s.entryInterface}]);
  mark('profile-method:cellEntry');s.cellEntry=checked(s.cell,'get_Entry',18,s.entry);mark('profile-method:cellAvatar');s.cellAvatar=checked(s.cell,'get_AvatarView',18,s.avatar);
  mark('profile-method:entryUser');s.entryUser=checked(s.entry,'get_User',18,s.user);mark('profile-method:avatarUser');s.avatarUser=checked(s.avatar,'get_User',18,s.user);
  mark('profile-method:selfUser');s.selfUser=checked(s.user,'get_IsCurrentUser',2);
  mark('profile-method:currentContent');s.currentContent=checked(s.profile,'get_CurrentProfileController',18,s.content);
  mark('profile-method:contentUser');s.contentUser=checked(s.content,'get_User',18,s.user);
  mark('profile-method:open');s.open=checked(s.search,'DV.Search.SearchTableView.IDelegate.OnUserSelected',1,null,
   [{kind:18,klass:s.entry},{kind:2},{kind:18,klass:s.resource}]);
  return s;
 }
 function prepareNavigation(f,getClass,get,signature){
  const spec={view:['Core.dll','UIKit','UIView'],vc:['Core.dll','UIKit','UIViewController'],
   dv:['DV.dll','DV.Common','DVViewController'],card:['DV.dll','DV','CardViewController'],
   search:['DV.Search.dll','DV.Search','SearchTabController'],
   profile:['DV.Profile.dll','DV.Profiles','ProfilesQueueViewController'],
   appRoot:['DV.dll','DV','RootViewController'],tabs:['DV.dll','DV','MainTabsController'],
   dvContainer:['DV.dll','DV.Common','DVContainerViewController'],
   uiContainer:['Core.dll','UIKit','UIContainerViewController'],
   dvNav:['DV.dll','DV.Common','DVNavigationController'],
   uiNav:['Core.dll','UIKit','UINavigationController']};
  const s={};for(const [key,args] of Object.entries(spec)){
   mark('base-class:'+key);s[key]=getClass(...args);if(s[key].isNull())throw new Error('metadata');
  }
  mark('base-hierarchy');if(!f.assignable(s.vc,s.search)||!f.assignable(s.vc,s.profile)||
     !f.assignable(s.dv,s.search))throw new Error('hierarchy');
  const specs=[['windowRoot','window','get_RootViewController',18,'vc'],
   ['lastView','window','GetLastPresentedView',18,'view'],
   ['top','vc','get_TopViewController',18,'vc'],
   ['viewController','view','get_ViewController',18,'vc'],
   ['hasView','vc','get_HasView',2],['viewOf','vc','get_View',18,'view'],
   ['presenting','vc','get_IsBeingPresented',2],['dismissing','vc','get_IsBeingDismissed',2],['isPresented','vc','get_IsPresented',2],
   ['parent','view','get_Parent',18,'view'],
   ['hidden','view','get_EffectivelyHidden',2],['interactive','view','get_UserInteractionEnabled',2],
   
   ['rootNav','appRoot','get_MainNavigationController',18,'vc'],
   ['loading','appRoot','get_IsShowingLoadingView',2],
   ['tabCurrent','tabs','get_CurrentViewController',18,'vc'],
   ['dvCurrent','dvContainer','get_CurrentViewController',18,'vc'],
   ['uiCurrent','uiContainer','get_CurrentViewController',18,'vc'],
   ['dvTransition','dvNav','get_InTransition',2],['uiTransition','uiNav','get_InTransition',2],
   ['hasPresented','vc','HasPresentedViewControllers',2],
   ['presented','vc','get_PresentedViewControllers',21],
   ['nearestPresenter','vc','get_NearestPresentingViewController',18,'vc'],
   ['cancel','profile','DV.Profiles.ProfileViewController.IDelegate.OnCloseRequested',1]];
  for(const [key,owner,name,kind,result] of specs){
   mark('base-method:'+key);const klass=owner==='window'?getClass('Core.dll','UIKit','UIWindow'):s[owner];
   const m=get(klass,name);
   if(!signature(m,false,kind)||!f.methodClass(m).equals(klass)||f.byref(f.returnType(m)))throw new Error('signature');
   if(result&&!f.assignable(s[result],f.classFromType(f.returnType(m))))throw new Error('return-type');
   s[key]={m,klass,kind,arity:0};
  }
  // Exact declared reference collection; never treat it as a boxed iterator.
  mark('modal-class');const klass=f.classFromType(f.returnType(s.presented.m));
  const small=p=>{if(p.isNull())return '';let value='';for(let i=0;i<96;i++){const c=p.add(i).readU8();if(c===0)return value;if(c<32||c>126)throw new Error('signature');value+=String.fromCharCode(c);}throw new Error('signature');};
  if(klass.isNull()||f.isValueType(klass)||small(f.className(klass))!=='ReadOnlyList`1'||
     small(f.classNamespace(klass))!=='Core.Collections'||small(f.imageName(f.classImage(klass)))!=='Core.dll')throw new Error('signature');
  s.modalClass=klass;
  mark('modal-count');const count=f.method(klass,Memory.allocUtf8String('get_Count'),0);
  const item=f.method(klass,Memory.allocUtf8String('get_Item'),1);
  if(!signature(count,false,8)||!f.methodClass(count).equals(klass)||f.byref(f.returnType(count)))throw new Error('signature');
  mark('modal-item');const bits=Memory.alloc(4);bits.writeU32(0);
  if(item.isNull()||f.arity(item)!==1||(f.flags(item,bits)&(16|1024))!==0||!f.methodClass(item).equals(klass)||
     f.typeKind(f.returnType(item))!==18||f.byref(f.returnType(item))||!f.classFromType(f.returnType(item)).equals(s.vc))throw new Error('signature');
  const param=f.param(item,0);if(param.isNull()||f.typeKind(param)!==8||f.byref(param))throw new Error('signature');
  s.modalCount={m:count,klass,kind:8,arity:0};s.modalItem={m:item,klass,kind:18,arity:1};
  return prepareProfile(f,s,getClass,get,signature);
 }
'''

def build():
    init="r.profile_metadata={checkpoint:'not-started',failure:'none',nested_types_found:0,method_found:null,expected_arity:null,actual_arity:null,expected_return_kind:null,actual_return_kind:null,owner_matches:null,return_class_matches:null};"
    bindings=base.BINDINGS+"\nObject.assign(f,{nested:bind('class_get_nested_types','pointer',['pointer','pointer']),declaring:bind('class_get_declaring_type','pointer',['pointer'])});"
    result=root.build_function(extra_apis=base.APIS+EXTRA_APIS,helpers=MARK+PREPARE,init=init,bindings=bindings,
        setup="prepareNavigation(f,getClass,get,signature);mark('ready');r.stage='profile-metadata-ready';")
    # Hard stop after thread-detach finally; no observer, runtime_invoke, action or GC handle.
    result=result.split(' if(setup===null)return Promise.resolve(r);',1)[0]+" return Promise.resolve(r);\n}"
    result=result.replace("['Core.dll','UIKit.Unity.dll','UnityEngine.CoreModule.dll']", "['Core.dll','DV.dll','DV.Search.dll','DV.Profile.dll','UIKit.Unity.dll','UnityEngine.CoreModule.dll']")
    result=result.replace("r.step='resolve-api';", "r.step='resolve-api';mark('resolve-api');")
    result=result.replace("r.step='metadata';", "r.step='metadata';mark('assemblies');")
    result=result.replace("} catch(_) {setup=null;r.stage='native-call-failed';}", "} catch(e) {setup=null;r.stage='native-call-failed';const label=e instanceof Error?e.message:'';r.profile_metadata.failure="+json.dumps(sorted(FAILURES-{'none','native-call-failed'}))+".includes(label)?label:'native-call-failed';}")
    return result

FUNCTION=build()

def validate(value):
    if not isinstance(value,dict) or 'profile_metadata' not in value:raise ValueError('Missing profile metadata details')
    details=value['profile_metadata']
    if not isinstance(details,dict) or set(details)!=DETAILS:raise ValueError('Unexpected profile metadata details')
    if details['checkpoint'] not in CHECKPOINTS or details['failure'] not in FAILURES:raise ValueError('Unexpected metadata category')
    if type(details['nested_types_found']) is not int or not 0<=details['nested_types_found']<=7:raise ValueError('Invalid nested type count')
    for key in ('method_found','owner_matches','return_class_matches'):
        if details[key] is not None and type(details[key]) is not bool:raise ValueError('Invalid method fact')
    for key,limit in (('expected_arity',16),('actual_arity',255),('expected_return_kind',255),('actual_return_kind',255)):
        if details[key] is not None and (type(details[key]) is not int or not 0<=details[key]<=limit):raise ValueError('Invalid signature fact')
    checked={k:copy.deepcopy(v) for k,v in value.items() if k!='profile_metadata'}
    if checked.get('stage')=='profile-metadata-ready':
        if details['checkpoint']!='ready' or details['failure']!='none' or not checked.get('metadata_ready') or details['nested_types_found']!=7:raise ValueError('Inconsistent metadata success')
        checked['stage']='metadata-not-ready' # Root schema has no metadata-only success stage.
    root.validate(checked)
    if checked['metadata_thread_attached'] and not checked['metadata_thread_detached'] and not checked['cleanup_failed']:raise ValueError('Unreported metadata thread leak')
    for key in ('observer_installed','observed_callback','main_thread_confirmed','runtime_available','window_available','object_classes_validated','runtime_handle_acquired','window_handle_acquired','runtime_handle_released','window_handle_released'):
        if checked[key]:raise ValueError('Forbidden UI/object access in metadata-only mode')
    if checked['managed_calls'] or checked['observed_calls']:raise ValueError('Forbidden invocation in metadata-only mode')
    return value
