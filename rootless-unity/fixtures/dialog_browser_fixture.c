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
#define il2cpp_object_unbox browser_base_unbox
#define il2cpp_type_is_byref browser_base_byref
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
#undef il2cpp_object_unbox
#undef il2cpp_type_is_byref
static Image messages_image={"DV.Messages.dll"},system_image={"mscorlib.dll"};
static Class message_tab={"DV","MessagesTabController"},chats_class={"DV.Messages","ChatsViewController"};
static Class system_type={"System","Type"},runtime_type={"System","RuntimeType"};
static Object message_tab_obj={&message_tab,0},chats_obj={&chats_class,0};
static Object type_search={&runtime_type,0},type_messages={&runtime_type,0};
static Type search_type={18,&nc[4]},message_type={18,&message_tab},type_type={18,&system_type};
static Method route={"DV.IMainTabsController.SwitchToTab",&nc[8],64,&tbool,700,2,&type_type};
static Method bad_route;
static int route_calls,route_bad;

static Class bc[]={
 {"DV.Messages","MessagesViewController"},{"DV.Messages","Chat"},{"DV.Messages","MessagesManager"},{"DV.Models","User"},
 {"DV.Messages","ChatCell"},{"UIKit","TableView"},{"UIKit","TableCell"},{"UIKit","ScrollView"},{"Core.Collections","CoreList`1"},{"Fixture","BoundChatCell"}};
static Type bt[10],blong={10},bvisible={21,&bc[8]},bcellref={18,&bc[6]};
static Method bm[]={
 {"get_ScrollView",&chats_class,0,&bt[7],800},
 {"get_VisibleCells",&bc[5],0,&bvisible,801},
 {"get_Count",&bc[8],0,&tint,802},
 {"get_Item",&bc[8],64,&bcellref,803,1,&tint},
 {"get_Item",&bc[9],0,&bt[1],804},
 {"get_DialogOpponent",&bc[1],0,&bt[3],805},
 {"get_Dialog",&bc[1],0,&tbool,806},
 {"get_IsActual",&bc[1],0,&tbool,807},
 {"get_IsDraftChat",&bc[1],0,&tbool,808},
 {"get_MessagesManager",&bc[1],0,&bt[2],809},
 {"get_CurrentUserId",&bc[2],0,&blong,810},
 {"get_Id",&bc[3],0,&blong,811},
 {"get_Id",&bc[1],0,&blong,812},
 {"get_Chat",&bc[0],0,&bt[1],813},
 {"get_User",&bc[0],0,&bt[3],814},
 {"OnCellDidClicked",&chats_class,64,&tvoid,815,2,&bt[4]},
 {"DV.Messages.BottomBarView.IDelegate.OnBackButton",&bc[0],0,&tvoid,816}};
static Method browser_bad_method;
static Object browser_vc={&bc[0],0},browser_table={&bc[5],0},browser_list={&bc[8],0};
static Object browser_cells[]={{&bc[4],0},{&bc[4],1}},browser_chats[]={{&bc[1],0},{&bc[1],1}},browser_users[]={{&bc[3],0},{&bc[3],1}};
static Object browser_manager={&bc[2],0},browser_long_box={NULL,0};
static int64_t browser_long;
static int browser_clicks,browser_backs,browser_cell_reads,browser_count_reads,browser_start;
static Object *browser_selected;
static void browser_init(void){int i;for(i=0;i<10;i++){bt[i].kind=18;bt[i].klass=&bc[i];}browser_clicks=browser_backs=browser_cell_reads=browser_count_reads=0;browser_start=0;browser_selected=&browser_chats[1];}
API int fixture_browser_clicks(void){return browser_clicks;}
API int fixture_browser_backs(void){return browser_backs;}
API void fixture_browser_entry(int entry){phase=entry;browser_start=entry;}
API void fixture_init(int m){old_init(m);route_calls=route_bad=0;browser_init();}
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
 for(int i=0;i<10;i++){Image *want=i==3?&images[3]:(i>=5?&images[0]:&messages_image);if(im==want&&!strcmp(ns,bc[i].ns)&&!strcmp(name,bc[i].name))return &bc[i];}
 return old_class(im,ns,name);
}
API unsigned char il2cpp_class_is_assignable_from(Class *a,Class *b){
 if(a==&nc[1]&&(b==&message_tab||b==&chats_class))return 1;
 if(a==&system_type&&b==&runtime_type)return 1;
 if(b==&message_tab&&((mode==715&&a==&nc[10])||(mode==716&&a==&nc[9])))return 1;
 if(a==b)return 1;
 if(a==&nc[1]&&b==&bc[0])return 1;
 if((a==&bc[6]||a==&bc[9])&&b==&bc[4])return 1;
 if(a==&bc[7]&&b==&bc[5])return 1;
 if(a==&nc[0]&&(b==&bc[4]||b==&bc[5]||b==&bc[6]||b==&bc[7]))return 1;
 return old_assignable(a,b);
}
API Method *il2cpp_class_get_method_from_name(Class *k,const char *name,int arity){
 if(k==&nc[8]&&arity==2&&!strcmp(name,route.name))return &route;
 for(int i=0;i<17;i++)if(arity==(int)bm[i].arity&&!strcmp(name,bm[i].name)&&(k==bm[i].klass||(i==4&&k==&bc[4]))){if(mode==801&&i==4)return NULL;return &bm[i];}
 return old_method(k,name,arity);
}
API Type *il2cpp_method_get_param(Method *m,unsigned int i){
 if(m==&route||m==&bad_route)return i==0?&type_type:i==1?((mode==701||m==&bad_route)?&tint:&tbool):NULL;
 if(m==&bm[15]||m==&browser_bad_method)return i==0?&bt[4]:i==1?(m==&browser_bad_method?&bt[3]:&bt[1]):NULL;
 if(mode==804&&m==&bm[3])return &tbool;
 return old_param(m,i);
}
API Method *il2cpp_object_get_virtual_method(Object *obj,Method *m){
 if(mode==710&&m==&route){bad_route=route;return &bad_route;}
 if(mode==812&&m==&bm[15]){browser_bad_method=*m;return &browser_bad_method;}
 return old_virtual(obj,m);
}
API Class *il2cpp_class_get_parent(Class *k){return k==&bc[4]?&bc[9]:NULL;}
API void *il2cpp_object_unbox(Object *obj){return obj==&browser_long_box?&browser_long:browser_base_unbox(obj);}
API unsigned char il2cpp_type_is_byref(Type *t){return mode==817&&t==&bcellref;}
API Type *il2cpp_class_get_type(Class *k){return k==&nc[4]?&search_type:k==&message_tab?&message_type:NULL;}
API Object *il2cpp_type_get_object(Type *t){return t==&search_type?&type_search:t==&message_type?&type_messages:NULL;}
API Object *il2cpp_runtime_invoke(Method *m,void *obj,void **args,void **exc){
 if(exc)*exc=NULL;
 if(m->action<10)return old_invoke(m,obj,args,exc);
 managed_calls++;if(TID()!=main_id)off_thread_calls++;
 switch(m->action){
 case 800:return &browser_table;
 case 801:return &browser_list;
 case 802:browser_count_reads++;modal_count=mode==818?129:mode==811&&browser_count_reads>=2?1:2;return &countbox;
 case 803:if(!args||!args[0]||*(int *)args[0]<0||*(int *)args[0]>1){route_bad++;return NULL;}return &browser_cells[*(int *)args[0]];
 case 804:browser_cell_reads++;return mode==802&&((Object *)obj)->value==1&&browser_cell_reads>=3?&browser_chats[0]:&browser_chats[((Object *)obj)->value];
 case 805:return &browser_users[((Object *)obj)->value];
 case 806:boolbox.value=!(mode==810&&((Object *)obj)->value==1);return &boolbox;
 case 807:boolbox.value=1;return &boolbox;
 case 808:boolbox.value=0;return &boolbox;
 case 809:return &browser_manager;
 case 810:browser_long=mode==805?101:100;return &browser_long_box;
 case 811:browser_long=((Object *)obj)->value==1?200:201;return &browser_long_box;
 case 812:browser_long=((Object *)obj)->value==1?300:301;return &browser_long_box;
 case 813:return mode==803?&browser_chats[0]:browser_selected;
 case 814:return mode==814?&browser_users[0]:&browser_users[browser_selected->value];
 case 815:
  browser_clicks++;if(obj!=&chats_obj||!args||args[0]!=&browser_cells[1]||args[1]!=&browser_chats[1])route_bad++;
  if(mode==807){*exc=&exception;return NULL;}browser_selected=args[1];phase=3;if(mode==815)slow();return NULL;
 case 816:
  browser_backs++;if(obj!=&browser_vc)route_bad++;
  if(mode==808){*exc=&exception;return NULL;}phase=1;return NULL;
 case 10:return &app_root;
 case 11:return NULL;
 case 12:if(obj==&message_tab_obj)return mode==712?&message_tab_obj:&chats_obj;return obj==&app_root?&ui_nav:NULL;
 case 14:boolbox.value=1;return &boolbox;
 case 15:return &view;
 case 16:case 17:case 26:case 30:case 31:case 32:boolbox.value=0;return &boolbox;
 case 18:
  if(obj==&browser_table)return mode==813?NULL:&view;
  if(obj==&browser_cells[0]||obj==&browser_cells[1])return &browser_table;
  return mode==711&&phase==1?NULL:&window;
 case 19:boolbox.value=mode==706&&phase==1;return &boolbox;
 case 20:case 24:boolbox.value=1;return &boolbox;
 case 25:return &ui_nav;
 case 27:if(phase==3)return &browser_vc;if(phase==1)return mode==707?&other:&message_tab_obj;return mode==705&&phase==2?&replacement:&search;
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
