/* Owned semantic navigation fixture; no Android/APKs, accounts or messages. */
#define NAV_FIXTURE
#define TREE_FIXTURE
#include "root_fixture.c"
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
 {"DV.Search","SearchSettingsCardController"},{"Fixture","Other"},
 {"DV","RootViewController"},{"DV","MainTabsController"},{"DV.Common","DVContainerViewController"},
 {"UIKit","UIContainerViewController"},{"DV.Common","DVNavigationController"},{"UIKit","UINavigationController"}};
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
 {"HasPresentedViewControllers",&nc[1],0,&tbool,32}};
static Object search={&nc[4],0},filters={&nc[5],0},other={&nc[6],0},view={&nc[0],0},boolbox={NULL,0},replacement={&nc[4],0};
static Object app_root={&nc[7],0},tabs={&nc[8],0},dv_container={&nc[9],0},ui_container={&nc[10],0},dv_nav={&nc[11],0},ui_nav={&nc[12],0},deep[14];
static Object view_chain[35],other_window={&classes[1],0};
static int phase,opens,cancels,virtual_calls,hidden_reads;
static void tree_init(int m){int i;phase=opens=cancels=virtual_calls=hidden_reads=0;for(i=0;i<35;i++)view_chain[i].klass=&nc[0];for(i=0;i<14;i++)deep[i].klass=&nc[10];if(m==90)nm[17].type=&tbool;if(m==62)nm[12].flags=16;}
static Class *tree_class(Image *im,const char *ns,const char *name){int i;for(i=0;i<13;i++){
 Image *want=(i<2||i==10||i==12)?&images[0]:(i<4||i>=7)?&images[3]:&nav_image;
 if(im==want&&!strcmp(ns,nc[i].ns)&&!strcmp(name,nc[i].name))return &nc[i];}return NULL;}
static Method *tree_method(Class *c,const char *name,int arity){int i;if(arity!=0)return NULL;
 for(i=0;i<23;i++)if(c==nm[i].klass&&!strcmp(name,nm[i].name))return &nm[i];return NULL;}
static unsigned char tree_assignable(Class *a,Class *b){
 if(a==&nc[0])return b==&nc[0]||b==&classes[1];
 if(a==&nc[1])return (uintptr_t)b>=(uintptr_t)&nc[1]&&(uintptr_t)b<=(uintptr_t)&nc[12];
 if(a==&nc[10])return b==&nc[8]||b==&nc[10]||b==&nc[11]||b==&nc[12];
 if(a==&nc[12])return b==&nc[11]||b==&nc[12];
 if(a==&nc[2])return b==&nc[2]||b==&nc[4];
 if(a==&nc[3])return b==&nc[3]||b==&nc[5];return 0;}
static void *tree_unbox(Object *o){(void)o;return NULL;}
API Class *il2cpp_method_get_class(Method *m){return m->klass;}
API unsigned char il2cpp_type_is_byref(Type *t){(void)t;return 0;}
API Class *il2cpp_class_from_type(Type *t){return t->klass;}
API Method *il2cpp_object_get_virtual_method(Object *o,Method *m){(void)o;virtual_calls++;return m;}
API int fixture_opens(void){return opens;}
API int fixture_cancels(void){return cancels;}
API int fixture_virtual_calls(void){return virtual_calls;}
static Object *active(void){
 if(mode==61)return &other;
 if(mode==71&&phase>0)return &other;
 if(mode==70&&phase==2)return &replacement;
 return phase==1?&filters:&search;
}
static Object *tree_invoke(Method *m,void *obj,void **args,void **exc){
 (void)obj;(void)args;int yes=0;
 if(mode==67&&m->action==15){*exc=&exception;return NULL;}
 switch(m->action){
 case 10:if(mode==77)slow();return mode>=80?&app_root:active();
 case 11:if(mode==88)return &view;return (mode==72||phase!=1||mode==87)?NULL:&view;
 case 12:if(obj==&app_root)return mode==81?&dv_nav:&ui_nav;return NULL;
 case 13:return mode==88?&other:active();
 case 14:yes=mode!=96;break;
 case 15:return &view;
 case 16:yes=(mode==73);break;
 case 17:yes=0;break;
 case 18:
  if(mode==94){if(obj==&view)return &view_chain[0];if((uintptr_t)obj>=(uintptr_t)&view_chain[0]&&(uintptr_t)obj<(uintptr_t)&view_chain[34])return ((Object *)obj)+1;}
  if(mode==95)return obj==&other_window?NULL:&other_window;
  if(mode==68||mode==93)return NULL;if(mode==91)return &view;return &window;
 case 19:hidden_reads++;yes=mode==63||(mode==97&&hidden_reads<4);break;
 case 20:yes=mode!=64;break;
 case 21:yes=mode!=65;break;
 case 22:opens++;if(mode==79)slow();if(mode==66){*exc=&exception;return NULL;}if(mode!=69&&mode!=76)phase=1;return NULL;
 case 24:yes=mode!=92&&phase==1;break;
 case 25:return mode==81?&dv_nav:&ui_nav;
 case 26:yes=0;break;
 case 27:return mode==82?&other:mode==83?NULL:active();
 case 28:return &ui_container;
 case 29:
  if(mode==84)return obj==&ui_nav?&ui_container:&ui_nav;
  if(mode==85){if(obj==&ui_nav)return &deep[0];if((uintptr_t)obj>=(uintptr_t)&deep[0]&&(uintptr_t)obj<(uintptr_t)&deep[13])return ((Object *)obj)+1;}
  if(mode==81){if(obj==&dv_nav)return &dv_container;if(obj==&ui_container)return &tabs;}
  return &tabs;
 case 30:case 31:yes=mode==86;break;
 case 32:yes=mode==87||(obj==&app_root&&phase==1);break;
 case 23:cancels++;if(mode==74){*exc=&exception;return NULL;}if(mode!=75)phase=2;return NULL;
 }
 boolbox.value=(unsigned char)yes;return &boolbox;
}
