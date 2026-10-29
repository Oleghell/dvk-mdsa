"""One explicit OnlineOnly operation. No city guessing, profile or message action.

Definitions are from the user's pinned metadata report. Every native method,
field, visible controller, and post-apply model is independently checked at runtime. A failure after a setter is not a rollback; reports make this explicit.
"""
import copy
import json
import threading

import uikit_navigation as navigation
from uikit_profile_navigation import replace_once

DEFAULTS = dict(online_before=None, online_set_attempted=False,
                online_set_completed=False, form_refreshed=False,
                online_verified=False, location_preserved=False,
                settings_checkpoint='not-checked')
CHECKPOINTS = {'not-checked', 'search-model', 'people-view', 'form-model',
               'set-online', 'refresh-form', 'apply-card', 'verify-search', 'complete'}

PREPARE = r'''
 function onlineSignature(f,e,m){
  if(m.isNull()||f.arity(m)!==e.arity)return false;
  const flags=Memory.alloc(4);flags.writeU32(0);
  if((f.flags(m,flags)&(16|1024))!==0)return false;
  const owner=f.methodClass(m);if(owner.isNull()||!f.assignable(e.klass,owner))return false;
  const t=f.returnType(m);if(t.isNull()||f.byref(t)||f.typeKind(t)!==e.kind)return false;
  if(e.result&&!f.classFromType(t).equals(e.result))return false;
  if(e.arity===1){const p=f.param(m,0);if(p.isNull()||f.byref(p)||f.typeKind(p)!==e.paramKind)return false;
   if(e.paramClass&&!f.classFromType(p).equals(e.paramClass))return false;}
  return true;
 }
 function prepareOnline(f,s,getClass){
  for(const [key,ns,name] of [['people','DV','SearchPeopleFilterViewController'],
   ['filterBase','DV.Search','SearchFilterBaseViewController'],['filterModel','DV.Search','SearchFilter'],
   ['searchCM','DV.CMs','SearchCM']]){
   s[key]=getClass('DV.Search.dll',ns,name);if(s[key].isNull()||f.isValueType(s[key]))throw new Error('metadata');
  }
  if(!f.assignable(s.filterBase,s.people)||!f.assignable(s.vc,s.people))throw new Error('hierarchy');
  const checked=(klass,name,kind,result=null,paramKind=null,paramClass=null)=>{
   const e={klass,kind,result,paramKind,paramClass,arity:paramKind===null?0:1,onlineChecked:true};
   e.m=f.method(klass,Memory.allocUtf8String(name),e.arity);
   if(!onlineSignature(f,e,e.m)||!f.methodClass(e.m).equals(klass))throw new Error('signature');return e;
  };
  s.cmFilter=checked(s.searchCM,'get_SearchFilter',18,s.filterModel);
  s.formFilter=checked(s.filterBase,'get_SearchFilter',18,s.filterModel);
  s.formReady=checked(s.people,'get_IsSearchFilterReady',2);
  s.formValid=checked(s.people,'get_IsSearchFilterValid',2);
  s.onlineGet=checked(s.filterModel,'get_OnlineOnly',2);
  s.onlineSet=checked(s.filterModel,'set_OnlineOnly',1,null,2);
  s.geoGet=checked(s.filterModel,'get_GeoCode',14);
  s.regionGet=checked(s.filterModel,'get_RegionCode',14);
  s.distanceGet=checked(s.filterModel,'get_ByDistance',2);
  s.refreshForm=checked(s.filterBase,'ApplySearchFilter',1,null,18,s.filterModel);
  s.apply=checked(s.filters,'OnApplyButton',1);
  const field=(klass,name,type)=>{
   const p=f.field(klass,Memory.allocUtf8String(name));
   if(p.isNull()||!f.fieldOwner(p).equals(klass)||(f.fieldFlags(p)&16))throw new Error('signature');
   const t=f.fieldType(p);if(t.isNull()||f.byref(t)||f.typeKind(t)!==18||!f.classFromType(t).equals(type))throw new Error('signature');return p;
  };
  s.cmField=field(s.search,'m_SearchCM',s.searchCM);
  s.peopleField=field(s.filters,'m_PeopleFilterViewController',s.people);
 }
'''
UTILS = r'''
  const saveOnline=(key,obj)=>{const h=own(obj);held.splice(held.indexOf(h),1);state[key]=h;};
  const fieldObject=(obj,field,klass)=>{
   if(fixedCancellationRequested)fail('cancelled');if(Date.now()>deadline)fail('frame-budget');
   const out=Memory.alloc(Process.pointerSize);out.writePointer(ptr(0));f.fieldValue(obj,field,out);
   const value=out.readPointer();if(value.isNull()||!f.objectClass(value).equals(klass))fail('unexpected-object');own(value);return value;
  };
  const filter=(entry,obj)=>{const value=call(entry,obj);if(value.isNull()||!f.objectClass(value).equals(s.filterModel))fail('unexpected-object');own(value);return value;};
  // Read only location codes, not names/phone/age/nickname or chat data. Values
  // live inside this script and never enter reports or RPC results.
  const code=entry=>model=>{
   const str=call(entry,model);if(str.isNull())return null;own(str);
   const length=f.stringLength(str);if(length<0||length>128)fail('signature-mismatch');
   const chars=f.stringChars(str);if(chars.isNull())fail('signature-mismatch');
   return length===0?'':chars.readUtf16String(length);
  };
  const location=model=>[code(s.geoGet)(model),code(s.regionGet)(model),bool(s.distanceGet,model)];
  const sameLocation=model=>JSON.stringify(location(model))===JSON.stringify(state.location);
'''
SEARCH = r'''
    n.settings_checkpoint='search-model';
    const cm=fieldObject(current,s.cmField,s.searchCM);saveOnline('onlineCM',cm);
    const model=filter(s.cmFilter,cm);n.online_before=bool(s.onlineGet,model);state.location=location(model);
'''
FORM = r'''
    n.settings_checkpoint='people-view';
    const people=fieldObject(current,s.peopleField,s.people);
    if(!checkView(people)||!bool(s.formReady,people)||!bool(s.formValid,people))fail('screen-not-ready');
    n.settings_checkpoint='form-model';const model=filter(s.formFilter,people);
    if(!sameLocation(model))fail('identity-changed');
    n.settings_checkpoint='set-online';
    if(!bool(s.onlineGet,model)){
     const value=Memory.alloc(1);value.writeU8(1);const args=Memory.alloc(Process.pointerSize);args.writePointer(value);
     n.online_set_attempted=true;call(s.onlineSet,model,args);n.online_set_completed=true;
    }
    if(!bool(s.onlineGet,model))fail('screen-not-ready');
    n.settings_checkpoint='refresh-form';
    const args=Memory.alloc(Process.pointerSize);args.writePointer(model);call(s.refreshForm,people,args);n.form_refreshed=true;
    // Refresh may replace the model. Re-read and check the actual form, not the
    // previously-held object. Only a visible valid people tab can be applied.
    const actual=filter(s.formFilter,people);
    if(!bool(s.onlineGet,actual)||!sameLocation(actual)||!bool(s.formReady,people)||!bool(s.formValid,people)||!checkView(people))fail('screen-not-ready');
    n.settings_checkpoint='apply-card';
'''
VERIFY = r'''
    n.settings_checkpoint='verify-search';
    const cm=fieldObject(current,s.cmField,s.searchCM);
    if(!cm.equals(target(state.onlineCM)))fail('identity-changed');
    const actual=filter(s.cmFilter,cm);
    if(!bool(s.onlineGet,actual)||!sameLocation(actual))fail('screen-not-ready');
    n.online_verified=true;n.location_preserved=true;n.settings_checkpoint='complete';
'''


def build():
    s = navigation.FUNCTION
    s = replace_once(s, ' function prepareNavigation(', PREPARE + '\n function prepareNavigation(')
    s = replace_once(s, 'r.navigation=emptyNavigation();',
                     'r.navigation=emptyNavigation();Object.assign(r.navigation,' + json.dumps(DEFAULTS) + ');')
    s = replace_once(s, 'setup.navigation=prepareNavigation(f,getClass,get,signature);',
                     'setup.navigation=prepareNavigation(f,getClass,get,signature);prepareOnline(f,setup.navigation,getClass);')
    apis = ['il2cpp_class_get_field_from_name', 'il2cpp_field_get_parent', 'il2cpp_field_get_type',
            'il2cpp_field_get_flags', 'il2cpp_field_get_value', 'il2cpp_string_length', 'il2cpp_string_chars']
    anchor = json.dumps(navigation.APIS[-1])
    # Source is generated using json.dumps; expand only the single API list.
    s = replace_once(s, anchor + ']', anchor + ',' + ','.join(json.dumps(a) for a in apis) + ']')
    s = replace_once(s, navigation.BINDINGS, navigation.BINDINGS + '''
 Object.assign(f,{
 field:bind('class_get_field_from_name','pointer',['pointer','pointer']),
 fieldOwner:bind('field_get_parent','pointer',['pointer']),fieldType:bind('field_get_type','pointer',['pointer']),
 fieldFlags:bind('field_get_flags','int',['pointer']),fieldValue:bind('field_get_value','void',['pointer','pointer','pointer']),
 stringLength:bind('string_length','int',['pointer']),stringChars:bind('string_chars','pointer',['pointer'])});''')
    s = replace_once(s, '   if(entry.arity===1){',
                     "   if(entry.onlineChecked){if(!onlineSignature(f,entry,m))fail('signature-mismatch');}\n   else if(entry.arity===1){")
    s = replace_once(s, '  const kind=obj=>{', UTILS + '\n  const kind=obj=>{')
    s = replace_once(s, '    n.search_verified=true;', SEARCH + '\n    n.search_verified=true;')
    s = replace_once(s, "    n.cancel_attempted=true;call(s.cancel,current);n.cancel_completed=true;", FORM +
                     '\n    n.apply_attempted=true;call(s.apply,current);n.apply_completed=true;')
    s = replace_once(s, "    n.return_verified=true;n.phase='done';", VERIFY + "\n    n.return_verified=true;n.phase='done';")
    s = s.replace('cancel_attempted', 'apply_attempted').replace('cancel_completed', 'apply_completed')
    s = replace_once(s, "['card','origin']", "['card','origin','onlineCM']")
    return s


FUNCTION = build()


def validate(value, **navigation_options):
    checked = copy.deepcopy(value)
    n = checked['navigation']
    if any(k not in n for k in DEFAULTS):
        raise ValueError('Missing online evidence')
    extra = {k: n.pop(k) for k in DEFAULTS}
    if extra['online_before'] is not None and type(extra['online_before']) is not bool:
        raise ValueError('Invalid original online flag')
    for k in DEFAULTS:
        if k not in ('online_before', 'settings_checkpoint') and type(extra[k]) is not bool:
            raise ValueError('Invalid online flag')
    if extra['settings_checkpoint'] not in CHECKPOINTS:
        raise ValueError('Invalid online checkpoint')
    n['cancel_attempted'] = n.pop('apply_attempted')
    n['cancel_completed'] = n.pop('apply_completed')
    navigation.validate(checked, **navigation_options)
    if extra['online_set_completed'] and not extra['online_set_attempted']:
        raise ValueError('Setter completed without attempt')
    mutated = extra['online_set_attempted'] or extra['form_refreshed'] or n['cancel_attempted']
    if mutated and (extra['online_before'] is None or not n['filters_verified']):
        raise ValueError('Mutation without original model and verified settings')
    if extra['form_refreshed'] and extra['online_set_attempted'] and not extra['online_set_completed']:
        raise ValueError('Refreshed after an incomplete setter')
    if n['cancel_attempted'] and not extra['form_refreshed']:
        raise ValueError('Applied without checking the form')
    success = n['stage'] == 'navigation-ready'
    if success != (extra['online_verified'] and extra['location_preserved'] and extra['settings_checkpoint'] == 'complete'):
        raise ValueError('Invalid post-apply evidence')
    if success and extra['online_before'] is None:
        raise ValueError('Missing original model')
    return value


def inspect(port, token, cancelled, expected=None, *, frida_api=None, source_function=FUNCTION, validator=validate, timeout=25, navigation_targets=None, navigation_hidden=None):
    from startup_failure import checkpoint, record
    with checkpoint('gadget-import'):
        if frida_api is None:
            import frida as frida_api
    from diagnose_device import cleanup_frida, validate_runtime
    from one_chat_device import ReadStopped
    from test_device import PACKAGE
    f = frida_api
    with checkpoint('runtime-check'):
        if f.__version__ != '17.24.1':
            raise ReadStopped('client-version')
    source = source_function + '''
rpc.exports={runtime(){return {frida_version:Frida.version,arch:Process.arch,platform:Process.platform};},
 root(){return probeUIKitRoot();},cancel(){cancelNavigation();}};
'''
    if navigation_targets is not None:
        from dialog_browser import targets
        navigation_targets=targets(navigation_targets)
        source += '\nrpc.exports.preparetargets=function(values){return prepareNavigationTargets(values);};\n'
    if navigation_hidden is not None:
        # v1.3.88: deny-only row exclusions ride the same fresh-script upload as
        # the journal targets; the native scan refuses them BEFORE adoption.
        from dialog_browser import hidden_peers
        navigation_hidden=hidden_peers(navigation_hidden)
        source += '\nrpc.exports.preparehidden=function(values){return prepareNavigationHidden(values);};\n'
    with checkpoint('gadget-manager'):
        manager = f.get_device_manager()
    address = '127.0.0.1:' + str(port)
    device = session = script = None
    guard = f.Cancellable()
    timer = threading.Timer(timeout, guard.cancel)
    timer.daemon = True
    done = threading.Event()
    monitor = None
    timer.start()
    stage = 'gadget-connect'
    try:
        with guard:
            if cancelled():
                raise ReadStopped('cancelled')
            device = manager.add_remote_device(address, token=token)
            stage = 'gadget-process'
            processes = device.enumerate_processes()
            if (len(processes) != 1 or type(processes[0].pid) is not int or processes[0].pid <= 0
                    or processes[0].name not in ('Gadget', PACKAGE)):
                raise ReadStopped('unexpected-process')
            stage = 'gadget-attach'
            session = device.attach(processes[0].pid)
            stage = 'script-create'
            script = session.create_script(source, name='dvk-online-only')
            stage = 'script-load'
            script.load()
            stage = 'runtime-check'
            runtime = validate_runtime(script.exports_sync.runtime())
            if runtime['arch'] != 'arm64' or runtime['platform'] != 'linux':
                raise ReadStopped('unsupported-runtime')
            if cancelled():raise ReadStopped('cancelled')
            if navigation_targets is not None:
                stage = 'navigation-targets-upload'
                if script.exports_sync.preparetargets(navigation_targets) is not True:
                    raise ReadStopped('navigation-targets-rejected')
            if navigation_hidden is not None:
                stage = 'navigation-hidden-upload'
                if script.exports_sync.preparehidden(navigation_hidden) is not True:
                    raise ReadStopped('navigation-hidden-rejected')
            if cancelled():raise ReadStopped('cancelled')
            def watch():
                while not done.wait(.1):
                    if cancelled():
                        try:
                            script.exports_sync.cancel()
                        except Exception:
                            pass
                        return
            monitor = threading.Thread(target=watch, daemon=True)
            monitor.start()
            stage = 'script-run'
            result = script.exports_sync.root()
            stage = 'result-validation'
            return validator(result)
    except Exception as error:
        # Nothing is loaded at this point, even when compilation loses its reply.
        # Never extend this proof to script-load, runtime, upload, root or validation.
        error._dvk_navigation_not_loaded=(navigation_targets is not None and stage=='script-create'
            and script is None and type(error).__name__ in {'TransportError','ServerNotRunningError','TimedOutError'})
        record(error, stage)
        raise
    finally:
        done.set()
        timer.cancel()
        if monitor:
            monitor.join(timeout=2)
        cleanup_frida(f, manager, address, script, session, device)


def run(executable, folder, cancelled=lambda: False):
    from assistant_lock import operation_lock
    from one_chat_device import capture
    with operation_lock():
        return capture(executable, folder, cancelled, inspector=inspect)
