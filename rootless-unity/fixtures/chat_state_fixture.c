/* Owned semantic navigation fixture; no Android/APKs, accounts or messages. */
#define NAV_FIXTURE
#define TREE_FIXTURE
#define il2cpp_domain_get_assemblies fixture_base_assemblies
#include "root_fixture.c"
#undef il2cpp_domain_get_assemblies
static Image chat_image={"DV.Messages.dll"};
API Image **il2cpp_domain_get_assemblies(void *d,size_t *n){static Image *all[]={&images[0],&images[1],&images[2],&images[3],&nav_image,&chat_image};(void)d;*n=6;return all;}
#ifndef _WIN32
#include <time.h>
#endif
static void slow(void){
#ifdef _WIN32
 Sleep(200);
#else
 struct timespec ts={0,200000000};nanosleep(&ts,NULL);
#endif
}
static Class nc[]={
 {"UIKit","UIView"},{"UIKit","UIViewController"},{"DV.Common","DVViewController"},
 {"DV","CardViewController"},{"DV.Search","SearchTabController"},
 {"DV.Messages","MessagesViewController"},{"Fixture","Other"},
 {"DV","RootViewController"},{"DV","MainTabsController"},{"DV.Common","DVContainerViewController"},
 {"UIKit","UIContainerViewController"},{"DV.Common","DVNavigationController"},{"UIKit","UINavigationController"}};
static Class modal_class={"Core.Collections","ReadOnlyList`1"};
static Type tint={8},tmodal={21,&modal_class};
static Object modal_list={&modal_class,0};
static int modal_reads;
static Type tvc={18,&nc[1]},tview={18,&nc[0]},tnav={18,&nc[12]};
static Method nm[]={
 {"get_RootViewController",&classes[1],0,&tvc,10},
 {"GetLastPresentedView",&classes[1],0,&tview,11},
 {"get_TopViewController",&nc[1],64,&tvc,12},
 {"get_ViewController",&nc[0],0,&tvc,13},
 {"get_HasView",&nc[1],0,&tbool,14},
 {"get_View",&nc[1],0,&tview,15},
 {"get_IsBeingPresented",&nc[1],0,&tbool,16},
 {"get_IsBeingDismissed",&nc[1],0,&tbool,17},
 {"get_Parent",&nc[0],0,&tview,18},
 {"get_EffectivelyHidden",&nc[0],0,&tbool,19},
 {"get_UserInteractionEnabled",&nc[0],0,&tbool,20},
 {"get_CanBeClosedByUser",&nc[3],64,&tbool,21},
 {"ShowSearchSettings",&nc[4],0,&tvoid,22},
 {"DismissWithCancel",&nc[3],64,&tvoid,23},
 {"get_IsPresented",&nc[1],0,&tbool,24},
 {"get_MainNavigationController",&nc[7],0,&tnav,25},
 {"get_IsShowingLoadingView",&nc[7],0,&tbool,26},
 {"get_CurrentViewController",&nc[8],64,&tvc,27},
 {"get_CurrentViewController",&nc[9],0,&tvc,28},
 {"get_CurrentViewController",&nc[10],64,&tvc,29},
 {"get_InTransition",&nc[11],0,&tbool,30},
 {"get_InTransition",&nc[12],0,&tbool,31},
 {"HasPresentedViewControllers",&nc[1],0,&tbool,32},
 {"get_PresentedViewControllers",&nc[1],0,&tmodal,33},
 {"get_NearestPresentingViewController",&nc[1],0,&tvc,34},
 {"get_Count",&modal_class,0,&tint,35},
 {"get_Item",&modal_class,64,&tvc,36,1,&tint}};
static Object search={&nc[4],0},filters={&nc[5],0},other={&nc[6],0},view={&nc[0],0},boolbox={NULL,0},replacement={&nc[4],0};
static Object app_root={&nc[7],0},tabs={&nc[8],0},dv_container={&nc[9],0},ui_container={&nc[10],0},dv_nav={&nc[11],0},ui_nav={&nc[12],0},deep[14];
static Object other_filters={&nc[5],0};
static Object view_chain[35],other_window={&classes[1],0};
static int phase,opens,cancels,virtual_calls,hidden_reads;
static void chat_init(void);
static Class *chat_class(Image *,const char *,const char *);
static Method *chat_method(Class *,const char *,int);
static Method *greeting_method(Class *,const char *,int);
static unsigned char chat_assignable(Class *,Class *);
static void *chat_unbox(Object *);
static Image *chat_class_image(Class *);
static void tree_init(int m){int i;chat_init();modal_reads=0;phase=opens=cancels=virtual_calls=hidden_reads=0;for(i=0;i<35;i++)view_chain[i].klass=&nc[0];for(i=0;i<14;i++)deep[i].klass=&nc[10];if(m==109)nm[26].param=&tbool;if(m==110)nm[25].type=&tbool;if(m==111)nm[26].type=&tbool;if(m==112)nm[26].flags=16;if(m==90)nm[17].type=&tbool;if(m==62)nm[12].flags=16;}
static Class *tree_class(Image *im,const char *ns,const char *name){int i;Class *extra=chat_class(im,ns,name);if(extra)return extra;for(i=0;i<13;i++){
 Image *want=(i<2||i==10||i==12)?&images[0]:(i<4||i>=7)?&images[3]:&nav_image;
 if(i==5)want=&chat_image;
 if(im==want&&!strcmp(ns,nc[i].ns)&&!strcmp(name,nc[i].name))return &nc[i];}return NULL;}
static Method *tree_method(Class *c,const char *name,int arity){int i;Method *extra=greeting_method(c,name,arity);if(extra)return extra;extra=chat_method(c,name,arity);if(extra)return extra;
 for(i=0;i<27;i++)if(arity==nm[i].arity&&c==nm[i].klass&&!strcmp(name,nm[i].name))return &nm[i];return NULL;}
static unsigned char tree_assignable(Class *a,Class *b){
 if(chat_assignable(a,b))return 1;
 if(a==&nc[0])return b==&nc[0]||b==&classes[1];
 if(a==&nc[1])return (uintptr_t)b>=(uintptr_t)&nc[1]&&(uintptr_t)b<=(uintptr_t)&nc[12];
 if(a==&nc[10])return b==&nc[8]||b==&nc[10]||b==&nc[11]||b==&nc[12];
 if(a==&nc[12])return b==&nc[11]||b==&nc[12];
 if(a==&nc[2])return b==&nc[2]||b==&nc[4];
 if(a==&nc[3])return b==&nc[3]||b==&nc[5];return 0;}
static int modal_count;static Object countbox={NULL,0};
static void *tree_unbox(Object *o){void *extra=chat_unbox(o);if(extra)return extra;return o==&countbox?&modal_count:NULL;}
static Class *value_field_class;
API unsigned char il2cpp_class_is_valuetype(Class *c){return (mode==302||mode==336)&&c==value_field_class;}
API const char *il2cpp_class_get_name(Class *c){return mode==114&&c==&modal_class?"OtherList":c->name;}
API const char *il2cpp_class_get_namespace(Class *c){return c->ns;}
API Image *il2cpp_class_get_image(Class *c){return chat_class_image(c);}
API Type *il2cpp_method_get_param(Method *m,unsigned int n){return n==0?m->param:NULL;}
API Class *il2cpp_method_get_class(Method *m){return m->klass;}
static Type *bad_byref_type;
API unsigned char il2cpp_type_is_byref(Type *t){return mode==316&&t==bad_byref_type;}
API Class *il2cpp_class_from_type(Type *t){return t->klass;}
API Method *il2cpp_object_get_virtual_method(Object *o,Method *m){(void)o;virtual_calls++;return m;}
API int fixture_modal_reads(void){return modal_reads;}
API int fixture_opens(void){return opens;}
API int fixture_cancels(void){return cancels;}
API int fixture_virtual_calls(void){return virtual_calls;}
static Object *active(void){return mode==301?&search:&filters;}
static Class cc[]={{"DV.Models","User"},{"DV.Messages","Chat"},{"DV.Messages","Message"},
 {"DV.CMs","MessagesCM"},{"DV.CMs","ContentDataList`1"},{"DataKit","BaseDataList`1"},{"DataKit","DataField`1"},{"DataKit","BaseField`1"},{"Other","Unrelated"}};
static Type ctuser={18,&cc[0]},ctchat={18,&cc[1]},ctmessage={18,&cc[2]},ctcm={18,&cc[3]},ctfield={21,&cc[6]},ctvalue={2};
static Object user={&cc[0],0},other_user={&cc[0],0},chat={&cc[1],0},other_chat={&cc[1],0},cm={&cc[3],0},other_cm={&cc[3],0},loaded_field={&cc[6],1},last_message={&cc[2],0};
static Object integer_box={NULL,0};static int integer_value,count_reads,draft_reads,state_reads,binding_reads,bad_receiver,cm_reads,loading_reads,sample_frames;
static Method cmeth[]={
 {"get_User",&nc[5],0,&ctuser,40},{"get_Chat",&nc[5],0,&ctchat,41},
 {"get_Dialog",&cc[1],0,&tbool,42},{"get_DialogOpponent",&cc[1],0,&ctuser,43},
 {"get_IsActual",&cc[1],0,&tbool,44},{"get_IsDraftChat",&cc[1],0,&tbool,45},
 {"get_HasMessagesCM",&cc[1],0,&tbool,46},{"get_MessagesCM",&cc[1],0,&ctcm,47},
 {"get_LastMessage",&cc[1],0,&ctmessage,48},{"get_LoadInProgress",&cc[4],0,&tbool,49},
 {"get_AllIsLoaded",&cc[4],0,&ctfield,50},{"get_Count",&cc[5],0,&tint,51},
 {"get_Value",&cc[6],0,&ctvalue,52}};
static void chat_init(void){count_reads=draft_reads=state_reads=binding_reads=bad_receiver=cm_reads=loading_reads=sample_frames=0;value_field_class=&cc[6];bad_byref_type=&ctvalue;ctvalue.kind=mode==315?8:2;if(mode==337){cc[8].ns="DataKit";cc[8].name="BaseField`1";}cmeth[12].klass=(mode>=328&&mode<=337)?&cc[7]:&cc[6];cmeth[12].flags=mode==332?16:mode==333?1024:0;cmeth[12].arity=mode==334?1:0;if(mode==318)cmeth[9].flags=16;}
static Class *chat_class(Image *im,const char *ns,const char *name){int i;for(i=0;i<9;i++){Image *want=i==0||i==4?&images[3]:i>=5?&images[0]:&chat_image;if(im==want&&!strcmp(ns,cc[i].ns)&&!strcmp(name,cc[i].name))return &cc[i];}return NULL;}
static Image *chat_class_image(Class *k){int i;if(k==&nc[5]||(mode==331&&k==&cc[7]))return &chat_image;for(i=0;i<9;i++)if(k==&cc[i])return i==0||i==4?&images[3]:i>=5?&images[0]:&chat_image;return &images[0];}
static Method *chat_method(Class *k,const char *name,int arity){int i;for(i=0;i<13;i++)if(arity==0&&(k==cmeth[i].klass||(i==12&&k==&cc[6]))&&!strcmp(name,cmeth[i].name)){if(mode==317&&i==12)return NULL;return &cmeth[i];}return NULL;}
static unsigned char chat_assignable(Class *a,Class *b){return ((a==&cc[6]&&b==&cc[6])||(a==&cc[7]&&b==&cc[6]&&mode!=335))||(a==&cc[4]&&(b==&cc[3]||b==&cc[4]))||(a==&cc[5]&&(b==&cc[3]||b==&cc[4]||b==&cc[5]));}
static void *chat_unbox(Object *o){if(o==&integer_box)return &integer_value;if(o==&loaded_field)return &loaded_field.value;return NULL;}
API Class *il2cpp_class_get_parent(Class *k){if(k==&cc[6]&&mode>=328&&mode<=337)return (mode==329||mode==337)?&cc[8]:mode==330?&cc[6]:&cc[7];if(k==&cc[3])return &cc[4];if(k==&cc[4])return &cc[5];return NULL;}
API int fixture_state_reads(void){return state_reads;}
API int fixture_bad_receiver(void){return bad_receiver;}
API int fixture_sample_frames(void){return sample_frames;}
static Class greeting_string_class={"System","String"};
static Object greeting_string={&greeting_string_class,0};static int greeting_sends,greeting_bad;
static Type greeting_string_type={14,&greeting_string_class};
static Method greeting_send={"DV.Messages.BottomBarView.IDelegate.OnSendText",&nc[5],64,&tvoid,60,1,&greeting_string_type};
static Method greeting_input={"get_IsInputEnabled",&cc[1],0,&tbool,61};
static Method *greeting_method(Class *k,const char *name,int arity){
 if(k==&nc[5]&&arity==1&&!strcmp(name,greeting_send.name)){if(mode==405)return NULL;greeting_send.flags=mode==407?16:64;greeting_string_type.kind=mode==406?8:14;return &greeting_send;}
 if(k==&cc[1]&&arity==0&&!strcmp(name,greeting_input.name))return &greeting_input;return NULL;}
API Object *il2cpp_string_new(const char *text){if(!text||strcmp(text,"\xd0\x9f\xd1\x80\xd0\xb8\xd0\xb2\xd0\xb5\xd1\x82 \xf0\x9f\x99\x82"))greeting_bad++;return mode==404?NULL:&greeting_string;}
API int fixture_greeting_sends(void){return greeting_sends;}
API int fixture_greeting_bad(void){return greeting_bad;}
static int last_action;
API int fixture_last_action(void){return last_action;}
static Object *tree_invoke(Method *m,void *obj,void **args,void **exc){int yes=0;last_action=m->action;(void)args;
 switch(m->action){
 case 10:sample_frames++;return &app_root;
 case 11:return NULL;
 case 12:return obj==&app_root?&ui_nav:NULL;
 case 13:return active();
 case 14:yes=1;break;
 case 15:return &view;
 case 16:case 17:yes=0;break;
 case 18:return &window;
 case 19:yes=0;break;
 case 20:yes=1;break;
 case 22:opens++;return NULL;
 case 23:cancels++;return NULL;
 case 24:yes=1;break;
 case 25:return &ui_nav;
 case 26:yes=0;break;
 case 27:return active();
 case 28:return &ui_container;
 case 29:return &tabs;
 case 30:case 31:case 32:yes=0;break;
 case 33:return NULL;
 case 34:return (Object *)obj;
 case 60:greeting_sends++;if(obj!=&filters||!args||args[0]!=&greeting_string)greeting_bad++;if(mode==403)*exc=&exception;return NULL;
 case 61:yes=mode!=402;break;
 case 40:return &user;
 case 41:binding_reads++;if(mode==313&&sample_frames>1)return &other_chat;return &chat;
 case 42:yes=1;break;
 case 43:return mode==312?&other_user:&user;
 case 44:state_reads++;yes=mode!=305&&(mode!=338||sample_frames>1);break;
 case 45:draft_reads++;yes=mode==341?draft_reads%2==1:mode==342?sample_frames==1:mode==306||(mode>=343&&mode<=346);break;
 case 46:yes=mode!=307&&mode!=344&&(mode!=339||sample_frames>1);break;
 case 47:cm_reads++;if(mode==308)return NULL;if(mode==314&&sample_frames>1)return &other_cm;if(mode==320)return &user;return &cm;
 case 48:return mode==311?&last_message:mode==326&&count_reads>=3?&last_message:NULL;
 case 49:loading_reads++;yes=mode==304||mode==340||mode==343||(mode==324&&loading_reads%2==0);break;
 case 50:return mode==321?NULL:&loaded_field;
 case 51:count_reads++;if(mode==319){*exc=&exception;return NULL;}integer_value=(mode==303||mode==346||mode==401)?7:mode==309?-1:mode==310&&count_reads%2==0?1:mode==325&&count_reads%3==0?1:0;return &integer_box;
 case 52:if(obj!=((mode==302||mode==336)?(void *)&loaded_field.value:(void *)&loaded_field))bad_receiver++;yes=mode==322?2:mode!=304&&mode!=323&&mode!=345;break;
 }
 boolbox.value=(unsigned char)yes;return &boolbox;
}
