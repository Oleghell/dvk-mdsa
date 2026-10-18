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
 {"DV.Search","SearchSettingsCardController"},{"Fixture","Other"}};
static Type tvc={18,&nc[1]},tview={18,&nc[0]};
static Method nm[]={
 {"get_RootViewController",&classes[1],0,&tvc,10},
 {"GetLastPresentedView",&classes[1],0,&tview,11},
 {"get_TopViewController",&nc[1],0,&tvc,12},
 {"get_ViewController",&nc[0],0,&tvc,13},
 {"get_HasView",&nc[1],0,&tbool,14},
 {"get_View",&nc[1],0,&tview,15},
 {"get_IsBeingPresented",&nc[1],0,&tbool,16},
 {"get_IsBeingDismissed",&nc[1],0,&tbool,17},
 {"get_IsEffectivelyPresented",&nc[2],0,&tbool,18},
 {"get_EffectivelyHidden",&nc[0],0,&tbool,19},
 {"get_UserInteractionEnabled",&nc[0],0,&tbool,20},
 {"get_CanBeClosedByUser",&nc[3],64,&tbool,21},
 {"ShowSearchSettings",&nc[4],0,&tvoid,22},
 {"DismissWithCancel",&nc[3],64,&tvoid,23},
 {"get_IsPresented",&nc[1],0,&tbool,24}};
static Object search={&nc[4],0},filters={&nc[5],0},other={&nc[6],0},view={&nc[0],0},boolbox={NULL,0},replacement={&nc[4],0};
static int phase,opens,cancels,virtual_calls;
static void tree_init(int m){phase=opens=cancels=virtual_calls=0;if(m==62)nm[12].flags=16;}
static Class *tree_class(Image *im,const char *ns,const char *name){int i;for(i=0;i<6;i++){
 Image *want=i<2?&images[0]:i<4?&images[3]:&nav_image;
 if(im==want&&!strcmp(ns,nc[i].ns)&&!strcmp(name,nc[i].name))return &nc[i];}return NULL;}
static Method *tree_method(Class *c,const char *name,int arity){int i;if(arity!=0)return NULL;
 for(i=0;i<15;i++)if(c==nm[i].klass&&!strcmp(name,nm[i].name))return &nm[i];return NULL;}
static unsigned char tree_assignable(Class *a,Class *b){
 if(a==&nc[1])return b==&nc[1]||b==&nc[2]||b==&nc[3]||b==&nc[4]||b==&nc[5]||b==&nc[6];
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
 case 10:if(mode==77)slow();return &search;
 case 11:return (mode==72)?NULL:&view;
 case 12:return active();
 case 13:return active();
 case 14:yes=1;break;
 case 15:return &view;
 case 16:yes=(mode==73);break;
 case 17:yes=0;break;
 case 18:yes=mode!=68;break;
 case 19:yes=mode==63;break;
 case 20:yes=mode!=64;break;
 case 21:yes=mode!=65;break;
 case 22:opens++;if(mode==79)slow();if(mode==66){*exc=&exception;return NULL;}if(mode!=69&&mode!=76)phase=1;return NULL;
 case 24:yes=phase==1;break;
 case 23:cancels++;if(mode==74){*exc=&exception;return NULL;}if(mode!=75)phase=2;return NULL;
 }
 boolbox.value=(unsigned char)yes;return &boolbox;
}
