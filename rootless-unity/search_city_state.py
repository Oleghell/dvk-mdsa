"""Read-only current search filter. Never open settings, Apply, Back or send."""
import copy,json
import search_online as online
import uikit_navigation as navigation
from search_city import check_city
from uikit_profile_navigation import replace_once as replace

DEFAULTS=dict(observed_city=None,online_only=None,by_distance=None,state_samples=0,state_verified=False)

def build():
    source=online.FUNCTION
    source=replace(source,'r.navigation=emptyNavigation();',
        'r.navigation=emptyNavigation();Object.assign(r.navigation,'+json.dumps(DEFAULTS)+');')
    anchor='prepareOnline(f,setup.navigation,getClass);'
    source=replace(source,anchor,anchor+'''
      const cs=setup.navigation;
      cs.geoName={klass:cs.filterModel,kind:14,result:null,arity:0,onlineChecked:true};
      cs.geoName.m=f.method(cs.filterModel,Memory.allocUtf8String('get_GeoRecordName'),0);
      if(!onlineSignature(f,cs.geoName,cs.geoName.m)||!f.methodClass(cs.geoName.m).equals(cs.filterModel))throw new Error('signature');
''')
    # Deny writes at the invocation boundary as well as removing every action
    # branch. Merely having metadata for a setter never authorizes invoking it.
    source=replace(source,'   const out=f.invoke(m,obj,params,ex);',
        "   if([s.open,s.cancel,s.onlineSet,s.refreshForm,s.apply].includes(entry))fail('signature-mismatch');const out=f.invoke(m,obj,params,ex);")
    start=source.index("   if(n.phase==='search'){")
    end=source.index("  } catch(e){n.error=",start)
    source=source[:start]+r'''
   if(n.phase!=='search'||k!=='search')fail('wrong-screen');
   n.search_verified=true;
   const cm=fieldObject(current,s.cmField,s.searchCM),model=filter(s.cmFilter,cm);
   const city=code(s.geoName)(model),geo=code(s.geoGet)(model),region=code(s.regionGet)(model);
   const distance=bool(s.distanceGet,model),only=bool(s.onlineGet,model);
   if(city===null||city.trim()!==city||city.length<1||city.length>80||!geo)fail('screen-not-ready');
   const fingerprint=JSON.stringify([city,geo,region,distance,only]);
   if(state.origin.isNull()){
    saveOnline('origin',current);saveOnline('onlineCM',cm);
   }else if(!current.equals(target(state.origin))||!cm.equals(target(state.onlineCM)))fail('identity-changed');
   if(state.currentFingerprint!==fingerprint){
    state.currentFingerprint=fingerprint;n.state_samples=1;state.currentNext=Date.now()+300;
    state.currentChanges=(state.currentChanges||0)+1;if(state.currentChanges>4)fail('screen-not-ready');return;
   }
   n.state_samples=2;n.observed_city=city;n.online_only=only;n.by_distance=distance;
   n.state_verified=true;n.phase='done';n.stage='navigation-ready';
''' +source[end:]
    source=replace(source,'if(!active)return;\n     r.observed_calls++;',
        'if(!active)return;\n     if(Date.now()<(navState.currentNext||0))return;\n     r.observed_calls++;')
    return source


def validate(value):
    checked=copy.deepcopy(value);n=checked['navigation']
    if any(k not in n for k in DEFAULTS):raise ValueError('Missing current-city evidence')
    extra={k:n.pop(k) for k in DEFAULTS}
    for key,default in online.DEFAULTS.items():
        if key not in n:raise ValueError('Missing filter evidence')
        actual=n.pop(key)
        if type(actual) is not type(default) or actual!=default:raise ValueError('Unexpected mutating filter evidence')
    n['cancel_attempted']=n.pop('apply_attempted');n['cancel_completed']=n.pop('apply_completed')
    if any(n[k] for k in ('open_attempted','open_completed','filters_verified','cancel_attempted','cancel_completed','return_verified','ui_text_read')):
        raise ValueError('Current-city observation attempted a UI action')
    if type(extra['state_verified']) is not bool or type(extra['state_samples']) is not int or not 0<=extra['state_samples']<=2:
        raise ValueError('Invalid current-city samples')
    success=n['stage']=='navigation-ready'
    if success:
        if (not extra['state_verified'] or extra['state_samples']!=2 or not n['search_verified']
                or n['frames']<2 or n['phase']!='done' or n['error']!='none' or value['stage']!='root-ready'
                or value['managed_calls']!=n['frames']*3 or n['readiness_check']!='ready'
                or n['readiness']['has_view'] is not True or n['readiness']['hidden'] is not False
                or n['readiness']['interactive'] is not True or n['readiness']['attached_to_main_window'] is not True):
            raise ValueError('Unverified current city')
        check_city(extra['observed_city'])
        if type(extra['online_only']) is not bool or type(extra['by_distance']) is not bool:raise ValueError('Invalid observed filter')
        # Reuse common schema/thread/resource validation, not its MUTATING
        # workflow success invariant. The original result retains zero actions.
        n.update(stage='navigation-stopped',error='observer-stopped')
    elif extra['state_verified'] or any(extra[k] is not None for k in ('observed_city','online_only','by_distance')):
        raise ValueError('Unverified city data returned')
    navigation.validate(checked)
    return value


def capture(executable,folder,cancelled=lambda:False):
    from one_chat_device import capture as read
    def observer(port,token,cancel,expected):
        try:return online.inspect(port,token,cancel,source_function=build(),validator=validate,timeout=20)
        except Exception as error:
            from startup_failure import clean
            failure=clean(getattr(error,'_dvk_failure',None))
            error._dvk_city_readonly_transport=bool(failure and failure['stage'] in {
                'gadget-connect','gadget-process','gadget-attach','script-create','script-load','runtime-check','script-run'}
                and failure['error_type'] in {'TransportError','ServerNotRunningError','TimedOutError'})
            raise
    return read(executable,folder,cancelled,inspector=observer)
