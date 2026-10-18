/* Owned semantic navigation fixture; no Android/APKs, accounts or messages. */
#define PROFILE_FIXTURE
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
 {"DV.Profiles","ProfilesQueueViewController"},{"Fixture","Other"},
 {"DV","RootViewController"},{"DV","MainTabsController"},{"DV.Common","DVContainerViewController"},
 {"UIKit","UIContainerViewController"},{"DV.Common","DVNavigationController"},{"UIKit","UINavigationController"}};
static Class pc[]={
 {"UIKit","TableView"},{"UIKit","TableCell"},{"DV.Search","SearchTableView"},{"DV","SearchCell"},
 {"DV.Search","SearchEntry"},{"DV.Search","ISearchEntry"},{"DV","AvatarView"},
 {"DV.Common","ResourceImageView"},{"DV.Models","User"},{"DV.Profiles","ProfileViewController"},
 {"","LineCell"},{"","BlockACell"},{"","BlockBCell"},{"","LineRecord"},{"","BlockARecord"},{"","BlockBRecord"},{"","RowRecord"},
 {"Core.Collections","CoreList`1"},{"Core.Collections.StructBased","ShortList`1"},{"","Iterator"},{"UIKit","ScrollView"},{"Core.Collections","CoreList`1"}};
static Type pt[22];static Type tview;
static Class modal_class={"Core.Collections","ReadOnlyList`1"};
static Type tint={8},tmodal={21,&modal_class};
static Object modal_list={&modal_class,0};
static int modal_reads;
static Type pentries={21,&pc[21]};
static Object pentrylist={&pc[21],0};
static Type pvisible={21,&pc[17]},piter={21,&pc[19]};
static Type pentry={18,&pc[4]},pbool={2},presource={18,&pc[7]};
static Method pm[]={
 {"get_ScrollView",&nc[4],0,&pt[20],40},
 {"get_VisibleCells",&pc[0],0,&pvisible,41},
 {"get_Count",&pc[17],0,&tint,42},
 {"get_Item",&pc[17],0,&pt[1],43,1,&tint},
 {"get_Subviews",&nc[0],0,&piter,44},
 {"GetEnumerator",&pc[19],0,&piter,45},
 {"get_Count",&pc[19],0,&tint,46},
 {"MoveNext",&pc[19],0,&tbool,47},
 {"get_Current",&pc[19],0,&tview,48},
 {"get_Item",&pc[10],0,&pt[13],49},
 {"get_Item",&pc[11],0,&pt[14],50},
 {"get_Item",&pc[12],0,&pt[15],51},
 {"IsPromoEntry",&pc[16],64,&tbool,52,1,&pt[5]},
 {"get_Entry",&pc[3],0,&pt[4],53},
 {"get_AvatarView",&pc[3],0,&pt[6],54},
 {"get_User",&pc[4],0,&pt[8],55},
 {"get_User",&pc[6],0,&pt[8],56},
 {"get_IsCurrentUser",&pc[8],0,&tbool,57},
 {"get_CurrentProfileController",&nc[5],0,&pt[9],58},
 {"get_User",&pc[9],0,&pt[8],59},
 {"DV.Search.SearchTableView.IDelegate.OnUserSelected",&nc[4],0,&tvoid,60,3,&pentry},
 {"DV.Profiles.ProfileViewController.IDelegate.OnCloseRequested",&nc[5],0,&tvoid,61},
 {"get_Items",&pc[16],0,&pentries,62},
 {"get_Count",&pc[21],0,&tint,63},
 {"get_Item",&pc[21],0,&pt[4],64,1,&tint}};
static Object ptable={&pc[2],0},pvisiblelist={&pc[17],0},prow={&pc[10],0},precord={&pc[13],0},pcell={&pc[3],0},pentryobj={&pc[4],0},pavatar={&pc[6],0},puser={&pc[8],0},potheruser={&pc[8],0},pcontent={&pc[9],0},pothercontent={&pc[9],0};
static Object pbox={NULL,0};static int pnumber,plist_reads,profile_reads,selected_wrong,row_reads;
typedef struct PIterator {Class *klass;int source,index;} PIterator;
static PIterator pi[4];static int pi_count;
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
static void tree_init(int m){int i;row_reads=0;modal_reads=plist_reads=profile_reads=selected_wrong=pi_count=0;for(i=0;i<22;i++){pt[i].kind=18;pt[i].klass=&pc[i];}for(i=0;i<4;i++)pi[i].klass=&pc[19];prow.klass= m==150?&pc[11]:m==151?&pc[12]:&pc[10];precord.klass=m==150?&pc[14]:m==151?&pc[15]:&pc[13];phase=opens=cancels=virtual_calls=hidden_reads=0;for(i=0;i<35;i++)view_chain[i].klass=&nc[0];for(i=0;i<14;i++)deep[i].klass=&nc[10];if(m==145)pm[20].arity=2;if(m==146)pm[3].param=&tbool;if(m==147)pm[7].type=&tvoid;if(m==109)nm[26].param=&tbool;if(m==110)nm[25].type=&tbool;if(m==111)nm[26].type=&tbool;if(m==112)nm[26].flags=16;if(m==90)nm[17].type=&tbool;if(m==62)nm[12].flags=16;}
static Class *tree_class(Image *im,const char *ns,const char *name){int i;
 if(im==&profile_image&&!strcmp(ns,"DV.Profiles")&&!strcmp(name,"ProfileViewController"))return &pc[9];
 if(im==&profile_image&&!strcmp(ns,"DV.Profiles")&&!strcmp(name,"ProfilesQueueViewController"))return &nc[5];
 for(i=0;i<22;i++){Image *want=(i<2||i>=17)?&images[0]:(i==2||i==3||i==4||i==5)?&nav_image:i==9?&profile_image:&images[3];if(im==want&&!strcmp(ns,pc[i].ns)&&!strcmp(name,pc[i].name))return &pc[i];}
 for(i=0;i<13;i++){
 Image *want=(i<2||i==10||i==12)?&images[0]:(i<4||i>=7)?&images[3]:&nav_image;
 if(im==want&&!strcmp(ns,nc[i].ns)&&!strcmp(name,nc[i].name))return &nc[i];}return NULL;}
static Method *tree_method(Class *c,const char *name,int arity){int i;
 for(i=0;i<25;i++)if(arity==pm[i].arity&&c==pm[i].klass&&!strcmp(name,pm[i].name))return &pm[i];
 for(i=0;i<27;i++)if(arity==nm[i].arity&&c==nm[i].klass&&!strcmp(name,nm[i].name))return &nm[i];return NULL;}
static unsigned char tree_assignable(Class *a,Class *b){
 if(a==&pc[0]&&b==&pc[2])return 1;
 if(a==&pc[1]&&(b==&pc[10]||b==&pc[11]||b==&pc[12]))return 1;
 if(a==&pc[7]&&b==&pc[6])return 1;
 if(a==&pc[5]&&b==&pc[4])return 1;
 if(a==&pc[16]&&(b==&pc[13]||b==&pc[14]||b==&pc[15]))return 1;
 if(a==&nc[1]&&b==&pc[9])return 1;
 if(a==&nc[0]&&((uintptr_t)b>=(uintptr_t)&pc[0]&&(uintptr_t)b<=(uintptr_t)&pc[12]))return 1;
 if(a==&nc[0])return b==&nc[0]||b==&classes[1];
 if(a==&nc[1])return (uintptr_t)b>=(uintptr_t)&nc[1]&&(uintptr_t)b<=(uintptr_t)&nc[12];
 if(a==&nc[10])return b==&nc[8]||b==&nc[10]||b==&nc[11]||b==&nc[12];
 if(a==&nc[12])return b==&nc[11]||b==&nc[12];
 if(a==&nc[2])return b==&nc[2]||b==&nc[4];
 if(a==&nc[3])return b==&nc[3]||b==&nc[5];return 0;}
static int modal_count;static Object countbox={NULL,0};
static void *tree_unbox(Object *o){if(o==&pbox)return &pnumber;if(o&&o->klass==&pc[19])return ((char *)o)+sizeof(void *);return o==&countbox?&modal_count:NULL;}
API unsigned char il2cpp_class_is_valuetype(Class *c){return c==&pc[18]||c==&pc[19];}
API const char *il2cpp_class_get_name(Class *c){return mode==114&&c==&modal_class?"OtherList":c->name;}
API const char *il2cpp_class_get_namespace(Class *c){return c->ns;}
API Image *il2cpp_class_get_image(Class *c){return c==&pc[9]||c==&nc[5]?&profile_image:&images[0];}
API Class *il2cpp_class_get_declaring_type(Class *c){if(c==&pc[19])return &pc[18];if(c>=&pc[10]&&c<=&pc[16])return &pc[2];return NULL;}
API Class *il2cpp_class_get_parent(Class *c){(void)c;return NULL;}
API Class *il2cpp_class_get_nested_types(Class *c,void **cursor){uintptr_t i=(uintptr_t)*cursor;if(c!=&pc[2]||i>=7)return NULL;*cursor=(void *)(i+1);return &pc[10+i];}
API Type *il2cpp_method_get_param(Method *m,unsigned int n){if(m==&pm[20])return n==0?&pentry:n==1?&pbool:n==2?&presource:NULL;return n==0?m->param:NULL;}
API Class *il2cpp_method_get_class(Method *m){return m->klass;}
API unsigned char il2cpp_type_is_byref(Type *t){(void)t;return 0;}
API Class *il2cpp_class_from_type(Type *t){return t->klass;}
API Method *il2cpp_object_get_virtual_method(Object *o,Method *m){(void)o;virtual_calls++;return m;}
API int fixture_visible_reads(void){return plist_reads;}
API int fixture_wrong_selection(void){return selected_wrong;}
API int fixture_modal_reads(void){return modal_reads;}
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
 (void)args;int yes=0;if(m>=&pm[5]&&m<=&pm[8])obj=((char *)obj)-sizeof(void *);
 if(mode==67&&m->action==15){*exc=&exception;return NULL;}
 switch(m->action){
 case 62:return &pentrylist;
 case 63:pnumber=1;return &pbox;
 case 64:if(!args||!args[0]||*(int *)args[0]!=0){selected_wrong++;*exc=&exception;return NULL;}return mode==153?&other:&pentryobj;
 case 40:return &ptable;
 case 41:return &pvisiblelist;
 case 42:plist_reads++;if(mode==149)slow();pnumber=mode==154?25:mode==132?0:1;return &pbox;
 case 43:row_reads++;if(mode==157&&row_reads>1)return &other;if(!args||!args[0]||*(int *)args[0]!=0){selected_wrong++;*exc=&exception;return NULL;}return &prow;
 case 44:pi[0].source=obj==&prow?1:0;pi[0].index=-1;return (Object *)&pi[0];
 case 45:if(pi_count>=3)pi_count=0;pi_count++;pi[pi_count]=*(PIterator *)obj;return (Object *)&pi[pi_count];
 case 46:pnumber=mode==155?17:((PIterator *)obj)->source;return &pbox;
 case 47:yes=++((PIterator *)obj)->index<((PIterator *)obj)->source;break;
 case 48:return &pcell;
 case 49:case 50:case 51:return &precord;
 case 52:if(!args||args[0]!=&pentryobj){selected_wrong++;*exc=&exception;return NULL;}yes=mode==133;break;
 case 53:return mode==134?NULL:&pentryobj;
 case 54:return &pavatar;
 case 55:return &puser;
 case 56:return mode==135?&potheruser:&puser;
 case 57:yes=mode==136;break;
 case 58:profile_reads++;if(mode==156)return &other;if(mode==137)return NULL;return mode==140&&profile_reads>2?&pothercontent:&pcontent;
 case 59:return mode==138?&potheruser:&puser;
 case 60:
  if(!args||args[0]!=&pentryobj||!args[1]||*(unsigned char *)args[1]!=0||args[2]!=&pavatar){selected_wrong++;*exc=&exception;return NULL;}
  opens++;if(mode==148)slow();if(mode==141){*exc=&exception;return NULL;}if(mode!=142)phase=1;return NULL;
 case 61:cancels++;if(mode==143){*exc=&exception;return NULL;}if(mode!=144)phase=2;return NULL;

 case 10:if(mode==77)slow();return mode>=80?&app_root:active();
 case 11:if(mode>=98)return NULL;if(mode==88)return &view;return (mode==72||phase!=1||mode==87)?NULL:&view;
 case 12:if(obj==&app_root)return mode==81?&dv_nav:&ui_nav;return NULL;
 case 13:return mode==88?&other:active();
 case 14:yes=mode!=96;break;
 case 15:if(mode==139&&obj==&pcontent)return NULL;return &view;
 case 16:yes=(mode==73);break;
 case 17:yes=0;break;
 case 18:
  if(obj==&pavatar)return &pcell;if(obj==&pcell)return &prow;if(obj==&prow)return &ptable;
  if(obj==&ptable)return &window;
  if(mode==94){if(obj==&view)return &view_chain[0];if((uintptr_t)obj>=(uintptr_t)&view_chain[0]&&(uintptr_t)obj<(uintptr_t)&view_chain[34])return ((Object *)obj)+1;}
  if(mode==95)return obj==&other_window?NULL:&other_window;
  if(mode==68||mode==93)return NULL;if(mode==91)return &view;return &window;
 case 19:hidden_reads++;if(mode==131&&obj==&prow){yes=1;break;}yes=mode==63||(mode==97&&hidden_reads<4);break;
 case 20:yes=mode!=64;break;
 case 21:yes=mode!=65;break;
 case 22:opens++;if(mode==79)slow();if(mode==66){*exc=&exception;return NULL;}if(mode!=69&&mode!=76)phase=1;return NULL;
 case 24:yes=mode!=92&&phase==1;break;
 case 25:return mode==81?&dv_nav:&ui_nav;
 case 26:yes=0;break;
 case 27:if(mode==158)return &other;if(mode==159&&phase==2)return &replacement;if(mode>=98)return &search;return mode==82?&other:mode==83?NULL:active();
 case 28:return &ui_container;
 case 29:
  if(mode==84)return obj==&ui_nav?&ui_container:&ui_nav;
  if(mode==85){if(obj==&ui_nav)return &deep[0];if((uintptr_t)obj>=(uintptr_t)&deep[0]&&(uintptr_t)obj<(uintptr_t)&deep[13])return ((Object *)obj)+1;}
  if(mode==81){if(obj==&dv_nav)return &dv_container;if(obj==&ui_container)return &tabs;}
  return &tabs;
 case 30:case 31:yes=mode==86;break;
 case 32:yes=mode==87||((obj==&app_root||obj==&search)&&phase==1);break;
 case 33:
  if(obj==&pcontent||obj==&pothercontent)return NULL;
  if(mode<98)return NULL;
  if(phase!=1)return NULL;
  if(mode==115&&obj==&filters)return &modal_list;
  if(mode==100)return obj==&search?&modal_list:NULL;
  if(mode==101)return obj==&tabs?&modal_list:NULL;
  if(mode==117)return obj==&dv_container?&modal_list:NULL;
  if(mode==102||mode==116)return NULL;
  return obj==&app_root?&modal_list:NULL;
 case 34:if(mode==117)return &dv_container;return mode>=98?&app_root:(Object *)obj;
 case 35:
  modal_reads++;modal_count=1;
  if(mode==118)slow();if(mode==121)return NULL;
  if(mode==103)modal_count=2;if(mode==104)modal_count=-1;if(mode==105)modal_count=9;
  if(mode==106&&modal_reads%2==0)modal_count=0;
  return &countbox;
 case 36:
  if(mode==119){*exc=&exception;return NULL;}
  if(mode==120&&modal_reads>=3)return &other_filters;
  if(!args||!args[0]||*(int *)args[0]!=0){*exc=&exception;return NULL;}
  if(mode==107)return NULL;if(mode==99)return &other;
  if(mode==108&&modal_reads%2==0)return &other;
  if(mode==115)return &filters;
  return &filters;
 case 23:cancels++;if(mode==74){*exc=&exception;return NULL;}if(mode!=75)phase=2;return NULL;
 }
 boolbox.value=(unsigned char)yes;return &boolbox;
}
