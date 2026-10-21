/* Owned synthetic ABI fixture: no APKs, accounts, contacts or messages. */
#define il2cpp_domain_get_assemblies old_assemblies
#define il2cpp_class_from_name old_class
#define il2cpp_class_get_method_from_name old_method
#define il2cpp_method_get_param old_param
#define il2cpp_object_get_virtual_method old_virtual
#define il2cpp_class_is_assignable_from old_assignable
#define il2cpp_runtime_invoke old_invoke
#define fixture_init old_init
#define fixture_tick old_tick
#include "navigation_fixture.c"
#undef il2cpp_domain_get_assemblies
#undef il2cpp_class_from_name
#undef il2cpp_class_get_method_from_name
#undef il2cpp_method_get_param
#undef il2cpp_object_get_virtual_method
#undef il2cpp_class_is_assignable_from
#undef il2cpp_runtime_invoke
#undef fixture_init
#undef fixture_tick
static Image messages_image={"DV.Messages.dll"},system_image={"mscorlib.dll"};
static Class message_tab={"DV","MessagesTabController"},chats_class={"DV.Messages","ChatsViewController"};
static Class system_type={"System","Type"},runtime_type={"System","RuntimeType"};
static Object message_tab_obj={&message_tab,0},chats_obj={&chats_class,0};
static Object type_search={&runtime_type,0},type_messages={&runtime_type,0};
static Type search_type={18,&nc[4]},message_type={18,&message_tab},type_type={18,&system_type};
static Method route={"DV.IMainTabsController.SwitchToTab",&nc[8],64,&tbool,700,2,&type_type};
static Method bad_route;
static int route_calls,route_bad;
API void fixture_init(int m){old_init(m);route_calls=route_bad=0;}
API int fixture_route_calls(void){return route_calls;}
API int fixture_route_bad(void){return route_bad;}
API Image **il2cpp_domain_get_assemblies(void *d,size_t *n){
 static Image *all[]={&images[0],&images[1],&images[2],&images[3],&nav_image,&messages_image,&system_image};
 (void)d;*n=7;return all;
}
API Class *il2cpp_class_from_name(Image *im,const char *ns,const char *name){
 if(im==&messages_image&&!strcmp(ns,message_tab.ns)&&!strcmp(name,message_tab.name))return &message_tab;
 if(im==&messages_image&&!strcmp(ns,chats_class.ns)&&!strcmp(name,chats_class.name))return &chats_class;
 if(im==&system_image&&!strcmp(ns,system_type.ns)&&!strcmp(name,system_type.name))return &system_type;
 return old_class(im,ns,name);
}
API unsigned char il2cpp_class_is_assignable_from(Class *a,Class *b){
 if(a==&nc[1]&&(b==&message_tab||b==&chats_class))return 1;
 if(a==&system_type&&b==&runtime_type)return 1;
 if(b==&message_tab&&((mode==715&&a==&nc[10])||(mode==716&&a==&nc[9])))return 1;
 return old_assignable(a,b);
}
API Method *il2cpp_class_get_method_from_name(Class *k,const char *name,int arity){
 if(k==&nc[8]&&arity==2&&!strcmp(name,route.name))return &route;
 return old_method(k,name,arity);
}
API Type *il2cpp_method_get_param(Method *m,unsigned int i){
 if(m==&route||m==&bad_route)return i==0?&type_type:i==1?((mode==701||m==&bad_route)?&tint:&tbool):NULL;
 return old_param(m,i);
}
API Method *il2cpp_object_get_virtual_method(Object *obj,Method *m){
 if(mode==710&&m==&route){bad_route=route;return &bad_route;}
 return old_virtual(obj,m);
}
API Type *il2cpp_class_get_type(Class *k){return k==&nc[4]?&search_type:k==&message_tab?&message_type:NULL;}
API Object *il2cpp_type_get_object(Type *t){return t==&search_type?&type_search:t==&message_type?&type_messages:NULL;}
API Object *il2cpp_runtime_invoke(Method *m,void *obj,void **args,void **exc){
 if(exc)*exc=NULL;
 if(m->action<10)return old_invoke(m,obj,args,exc);
 managed_calls++;if(TID()!=main_id)off_thread_calls++;
 switch(m->action){
 case 10:return &app_root;
 case 11:return NULL;
 case 12:if(obj==&message_tab_obj)return mode==712?&message_tab_obj:&chats_obj;return obj==&app_root?&ui_nav:NULL;
 case 14:boolbox.value=1;return &boolbox;
 case 15:return &view;
 case 16:case 17:case 26:case 30:case 31:case 32:boolbox.value=0;return &boolbox;
 case 18:return mode==711&&phase==1?NULL:&window;
 case 19:boolbox.value=mode==706&&phase==1;return &boolbox;
 case 20:case 24:boolbox.value=1;return &boolbox;
 case 25:return &ui_nav;
 case 27:if(phase==1)return mode==707?&other:&message_tab_obj;return mode==705&&phase==2?&replacement:&search;
 case 28:return &chats_obj;
 case 29:return obj==&message_tab_obj?&chats_obj:&tabs;
 case 33:return mode==708?&modal_list:NULL;
 case 34:return &app_root;
 case 35:modal_count=1;return &countbox;
 case 36:return &other;
 case 700:
  route_calls++;if(obj!=&tabs||!args||!args[1]||*(unsigned char *)args[1]!=0)route_bad++;
  if(!args||args[0]!=(phase==0?&type_messages:&type_search))route_bad++;
  if((mode==702&&phase==0)||(mode==713&&phase==1)){*exc=&exception;return NULL;}
  boolbox.value=!((mode==703&&phase==0)||(mode==704&&phase==1));
  if(boolbox.value)phase=phase==0?1:2;
  if(mode==714&&phase==1)slow();
  return &boolbox;
 }
 /* The fixed workflow must never invoke either old filter action. */
 route_bad++;return NULL;
}
API void fixture_tick(void){void *exc=NULL;il2cpp_runtime_invoke(&methods[3],&runtime,NULL,&exc);}
