/* Owned semantic navigation fixture; no Android/APKs, accounts or messages. */
#define PROFILE_FIXTURE
#define NAV_FIXTURE
#define TREE_FIXTURE
#define il2cpp_domain_get_assemblies fixture_base_assemblies
#include "root_fixture.c"
#undef il2cpp_domain_get_assemblies
static Image messages_image={"DV.Messages.dll"};
API Image **il2cpp_domain_get_assemblies(void *d,size_t *n){static Image *all[]={&images[0],&images[1],&images[2],&images[3],&nav_image,&profile_image,&messages_image};(void)d;*n=7;return all;}
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
static uint64_t clock_ms(void){
#ifdef _WIN32
 return GetTickCount64();
#else
 struct timespec ts;clock_gettime(CLOCK_MONOTONIC,&ts);return (uint64_t)ts.tv_sec*1000+ts.tv_nsec/1000000;
#endif
}
static uint64_t started_ms;static int opened_ms,closed_ms,friend_reads;
API int fixture_opened_ms(void){return opened_ms;}
API int fixture_closed_ms(void){return closed_ms;}
API int fixture_elapsed_ms(void){return (int)(clock_ms()-started_ms);}
API int fixture_friend_reads(void){return friend_reads;}
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
static Type pentry={18,&pc[4]},pbool={2},presource={18,&pc[7]},pbyrow={18,&pc[1]},pbyentry={18,&pc[4]},pwrongref={18,&pc[8]};
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
static Class profile_model={"DV.Models","Profile"};
static Type tlong={10},tmodel={18,&profile_model},tbylong={10};
static Method profile_getter={"get_Profile",&pc[9],0,&tmodel,66};
static Method actual_getter={"get_IsActual",&profile_model,0,&tbool,67};
static Method friend_getters[]={
 {"get_FriendsCount",&profile_model,0,&tlong,65}};
static Object model_obj={&profile_model,0},other_model={&profile_model,0};
static Object longbox={NULL,0};static int64_t longnumber;
static int model_reads,actual_reads,id_reads;
static Method identity_getter={"get_Id",&pc[8],0,&tlong,68};
static int batch_mode(void){return (mode>=250&&mode<=257)||(mode>=500&&mode<=519);}
static Object ptable={&pc[2],0},pvisiblelist={&pc[17],0},prow={&pc[10],0},precord={&pc[13],0},pcell={&pc[3],0},pentryobj={&pc[4],0},pavatar={&pc[6],0},puser={&pc[8],0},potheruser={&pc[8],0},pcontent={&pc[9],0},pothercontent={&pc[9],0};
static Object preplacementrow={&pc[10],0};
static Object ppromocell={&pc[3],0},ppromoentry={&pc[4],0};
static int entry_reads,avatar_reads,promo_reads;
/* Many distinct UI rows/iterators: unlike the tiny earlier graph these expose
   retention across completed rows. Objects are fixture-owned, no app values. */
static Object stress_rows[24],stress_wrap[24][2],stress_cells[24],stress_parents[21];
static int iterator_allocations,pin_errors,blocked,stress_current_row;
static int stress_mode(void){return batch_mode()||(mode>=190&&mode<=197)||mode==207;}
static int stress_count(void){if(mode==518)return 24;if(batch_mode())return mode==252||mode==501?5:12;return mode==191||mode==192?24:8;}
static int stress_index(void *obj,Object *array,int length){int i;for(i=0;i<length;i++)if(obj==&array[i])return i;return -1;}
static int pinned(void *obj){int i;for(i=0;i<HANDLE_COUNT;i++)if(handles[i].live&&handles[i].target==obj)return 1;return 0;}
API int fixture_pin_errors(void){return pin_errors;}
API int fixture_blocked(void){return blocked;}
API int fixture_iterator_allocations(void){return iterator_allocations;}
static Object pbox={NULL,0};static int pnumber,plist_reads,profile_reads,selected_wrong,row_reads;
typedef struct PIterator {Class *klass;int source,index;Object *view;} PIterator;
static PIterator pi[1024];static int pi_count;
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

static Class ac[]={
 {"DV.Profiles","ProfileOverlayView"},{"DV.Messages","MessagesViewController"},
 {"DV.Messages","Chat"},{"DV.CMs","MessagesCM"},{"DV.CMs","ContentDataList`1"},
 {"DataKit","BaseDataList`1"},{"DataKit","DataField`1"},{"DataKit","BaseField`1"},
 {"DV.Messages","Message"},{"System","String"},{"DV.Messages","MessagesManager"}};
static Type atvc={18,&ac[1]},atmodel={18,&profile_model},atuser={18,&pc[8]},atchat={18,&ac[2]},atcm={18,&ac[3]},atloaded={21,&ac[6]},atmessage={18,&ac[8]},atstring={14,&ac[9]},atoverlay={18,&ac[0]};
static Object aoverlay={&ac[0],0},achatvc={&ac[1],0},achat={&ac[2],0},acm={&ac[3],0},acm_other={&ac[3],0},afield={&ac[6],0},alast={&ac[8],0},astring={&ac[9],0},aintbox={NULL,0};
static Type atmanager={18,&ac[10]};
static Object amanager={&ac[10],0};
static int cohort_mode;
static uint64_t delayed_return_at;
API void fixture_cohort_mode(int m){cohort_mode=m;}
static int auto_slowed;
static int auto_opens,auto_backs,auto_sends,auto_bad,auto_actual_reads,auto_variant=-1,auto_int;
static uint64_t auto_last_action;static int auto_timing_bad;
static void auto_action(void){uint64_t now=clock_ms();if(auto_last_action&&now-auto_last_action<990)auto_timing_bad++;auto_last_action=now;}
API int fixture_auto_timing_bad(void){return auto_timing_bad;}
static Method am[]={
 {"OnMessageButton",&ac[0],0,&tvoid,80}, {"get_Profile",&ac[0],0,&atmodel,81},
 {"get_User",&ac[1],0,&atuser,82},{"get_Chat",&ac[1],0,&atchat,83},
 {"get_Dialog",&ac[2],0,&tbool,84},{"get_DialogOpponent",&ac[2],0,&atuser,85},
 {"get_IsActual",&ac[2],0,&tbool,86},{"get_IsDraftChat",&ac[2],0,&tbool,87},
 {"get_HasMessagesCM",&ac[2],0,&tbool,88},{"get_MessagesCM",&ac[2],0,&atcm,89},
 {"get_LastMessage",&ac[2],0,&atmessage,90},{"get_LoadInProgress",&ac[4],0,&tbool,91},
 {"get_AllIsLoaded",&ac[4],0,&atloaded,92},{"get_Count",&ac[5],0,&tint,93},
 {"get_Value",&ac[7],0,&tbool,94},{"get_IsInputEnabled",&ac[2],0,&tbool,95},
 {"DV.Messages.BottomBarView.IDelegate.OnSendText",&ac[1],64,&tvoid,96,1,&atstring},
 {"DV.Messages.BottomBarView.IDelegate.OnBackButton",&ac[1],0,&tvoid,97},
 {"get_MessagesManager",&ac[2],0,&atmanager,98},
 {"get_CurrentUserId",&ac[10],0,&tlong,99},
 {"get_Id",&ac[2],0,&tlong,100}};
typedef struct AutoField {int present;} AutoField;
static AutoField overlay_field={1};
API AutoField *il2cpp_class_get_field_from_name(Class *k,const char *name){return mode!=508&&k==&nc[5]&&!strcmp(name,"m_OverlayView")?&overlay_field:NULL;}
API Type *il2cpp_field_get_type(AutoField *f){(void)f;return &atoverlay;}
API Class *il2cpp_field_get_parent(AutoField *f){(void)f;return &nc[5];}
API uint32_t il2cpp_field_get_flags(AutoField *f){(void)f;return 0;}
API void il2cpp_field_get_value(Object *o,AutoField *f,void **out){(void)f;if(o!=&filters||phase!=1)auto_bad++;*out=&aoverlay;}
#include "greetings_fixture.h"
API Object *il2cpp_string_new(const char *text){int i,found=0;for(i=0;i<30;i++)if(text&&!strcmp(text,fixture_greetings[i])){found=1;auto_variant=i;}if(!found)auto_bad++;return &astring;}
API int fixture_auto_sends(void){return auto_sends;}
API int fixture_auto_opens(void){return auto_opens;}
API int fixture_auto_backs(void){return auto_backs;}
API int fixture_auto_bad(void){return auto_bad;}
static Class *auto_class(Image *im,const char *ns,const char *name){int i;for(i=0;i<11;i++){Image *want=i==0?&profile_image:i>=5&&i<=7||i==9?&images[0]:i==4?&images[3]:&messages_image;if(im==want&&!strcmp(ns,ac[i].ns)&&!strcmp(name,ac[i].name))return &ac[i];}return NULL;}
static Method *auto_method(Class *k,const char *name,int arity){int i;for(i=0;i<21;i++)if((k==am[i].klass||(i==14&&k==&ac[6]))&&arity==am[i].arity&&!strcmp(name,am[i].name))return &am[i];return NULL;}
static Image *auto_image(Class *k){int i;for(i=0;i<11;i++)if(k==&ac[i])return i==0?&profile_image:i>=5&&i<=7||i==9?&images[0]:i==4?&images[3]:&messages_image;return NULL;}
static Object *auto_invoke(Method *m,void *obj,void **args,void **exc){int yes=0;
 switch(m->action){
 case 80:if(obj!=&aoverlay||phase!=1)auto_bad++;auto_action();auto_opens++;phase=3;auto_actual_reads=0;return NULL;
 case 81:return &model_obj;
 case 82:return mode==504?&potheruser:&puser;
 case 83:return &achat;
 case 84:yes=1;break;
 case 85:return &puser;
 case 86:auto_actual_reads++;yes=1;break;
 case 87:case 88:case 94:case 95:yes=1;break;
 case 89:return mode==510&&auto_actual_reads>2?&acm_other:&acm;
 case 90:return mode==512?&alast:NULL;
 case 91:yes=mode==503;break;
 case 92:return &afield;
 case 93:auto_int=mode==502||mode==515?1:0;return &aintbox;
 case 96:if(obj!=&achatvc||phase!=3||!args||args[0]!=&astring||auto_variant<0)auto_bad++;auto_action();auto_sends++;if(mode==505)*exc=&exception;return NULL;
 case 97:if(obj!=&achatvc||phase!=3)auto_bad++;auto_action();auto_backs++;if(mode==506){*exc=&exception;return NULL;}
  if(auto_backs==3&&(cohort_mode==5||cohort_mode==6)){delayed_return_at=cohort_mode==5?clock_ms()+12000:0;return NULL;}
  phase=mode>=513&&mode<=517?2:1;return NULL;
 case 98:return &amanager;
 case 99:longnumber=cohort_mode==1?0:cohort_mode==2?stress_current_row+1:9999;return &longbox;
 case 100:longnumber=cohort_mode==3?-1:cohort_mode==4?++id_reads:1000+stress_current_row;return &longbox;
 }
 boolbox.value=(unsigned char)yes;return &boolbox;
}

static void tree_init(int m){int i;iterator_allocations=pin_errors=blocked=0;stress_current_row=-1;
 for(i=0;i<24;i++){stress_rows[i].klass=&pc[10];stress_wrap[i][0].klass=stress_wrap[i][1].klass=&nc[0];stress_cells[i].klass=&pc[3];}
 for(i=0;i<21;i++)stress_parents[i].klass=&nc[0];
 started_ms=clock_ms();opened_ms=closed_ms=friend_reads=0;model_reads=actual_reads=id_reads=0;identity_getter.type=m==253?&tint:&tlong;friend_getters[0].type=m==215?&tbool:m==229?&tint:m==238?&tbylong:&tlong;
 friend_getters[0].klass=m==236?&pc[8]:&profile_model;friend_getters[0].flags=m==237?16:0;
 profile_getter.type=m==228?&tbool:m==232?&pt[8]:&tmodel;
 actual_getter.type=m==233?&tint:&tbool;
 entry_reads=avatar_reads=promo_reads=0;if(m>=170&&m<=197){pm[3].type=&pbyrow;pm[24].type=&pbyentry;}if(m==173)pm[3].type=&pwrongref;if(m==174)pm[1].type=&pbyrow;if(m==176)pm[3].flags=64;if(m==177)pm[3].param=&tbool;if(m==178)pm[3].flags=16;if(m==179)pm[3].arity=2;if(m==164)attached=0;row_reads=0;modal_reads=plist_reads=profile_reads=selected_wrong=pi_count=0;for(i=0;i<22;i++){pt[i].kind=18;pt[i].klass=&pc[i];}for(i=0;i<1024;i++)pi[i].klass=&pc[19];prow.klass= m==150||m==171||m==180||m==181?&pc[11]:m==151||m==172||m==186?&pc[12]:&pc[10];precord.klass=m==150||m==171||m==180||m==181?&pc[14]:m==151||m==172||m==186?&pc[15]:&pc[13];phase=opens=cancels=virtual_calls=hidden_reads=0;for(i=0;i<35;i++)view_chain[i].klass=&nc[0];for(i=0;i<14;i++)deep[i].klass=&nc[10];if(m==145)pm[20].arity=2;if(m==146)pm[3].param=&tbool;if(m==147)pm[7].type=&tvoid;if(m==163)pm[14].type=&tbool;if(m==109)nm[26].param=&tbool;if(m==110)nm[25].type=&tbool;if(m==111)nm[26].type=&tbool;if(m==112)nm[26].flags=16;if(m==90)nm[17].type=&tbool;if(m==62)nm[12].flags=16;}
static Class *tree_class(Image *im,const char *ns,const char *name){int i;Class *extra=auto_class(im,ns,name);if(extra)return extra;
 if(mode==162&&!strcmp(name,"AvatarView"))return NULL;
 if(!strcmp(ns,"DV.Models")&&!strcmp(name,"Profile"))return ((mode>=210&&mode<=240)||batch_mode())&&mode!=234?&profile_model:NULL;
 if(im==&profile_image&&!strcmp(ns,"DV.Profiles")&&!strcmp(name,"ProfileViewController"))return &pc[9];
 if(im==&profile_image&&!strcmp(ns,"DV.Profiles")&&!strcmp(name,"ProfilesQueueViewController"))return &nc[5];
 for(i=0;i<22;i++){Image *want=(i<2||i>=17)?&images[0]:(i==2||i==3||i==4||i==5)?&nav_image:i==9?&profile_image:&images[3];if(im==want&&!strcmp(ns,pc[i].ns)&&!strcmp(name,pc[i].name))return &pc[i];}
 for(i=0;i<13;i++){
 Image *want=(i<2||i==10||i==12)?&images[0]:(i<4||i>=7)?&images[3]:&nav_image;
 if(im==want&&!strcmp(ns,nc[i].ns)&&!strcmp(name,nc[i].name))return &nc[i];}return NULL;}
static Method *tree_method(Class *c,const char *name,int arity){int i;Method *extra=auto_method(c,name,arity);if(extra)return extra;
 if(batch_mode()&&c==&pc[8]&&arity==0&&!strcmp(name,"get_Id"))return &identity_getter;
 if(((mode>=210&&mode<=240)||batch_mode())&&arity==0){
  if(c==&pc[9]&&!strcmp(name,"get_Profile"))return mode==216?NULL:&profile_getter;
  if(c==&profile_model&&!strcmp(name,"get_IsActual"))return mode==240?NULL:&actual_getter;
  if(c==&profile_model&&!strcmp(name,"get_FriendsCount"))return mode==230?NULL:&friend_getters[0];
 }
 for(i=0;i<25;i++)if(arity==pm[i].arity&&c==pm[i].klass&&!strcmp(name,pm[i].name))return &pm[i];
 for(i=0;i<27;i++)if(arity==nm[i].arity&&c==nm[i].klass&&!strcmp(name,nm[i].name))return &nm[i];return NULL;}
static unsigned char tree_assignable(Class *a,Class *b){
 if((a==&nc[1]&&b==&ac[1])||(a==&nc[0]&&b==&ac[0])||(a==&ac[4]&&b==&ac[3])||(a==&ac[5]&&(b==&ac[3]||b==&ac[4]))||(a==&ac[7]&&b==&ac[6]))return 1;
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
static void *tree_unbox(Object *o){if(o==&aintbox)return &auto_int;if(o==&longbox)return &longnumber;if(o==&pbox)return &pnumber;if(o&&o->klass==&pc[19])return ((char *)o)+sizeof(void *);return o==&countbox?&modal_count:NULL;}
API unsigned char il2cpp_class_is_valuetype(Class *c){return c==&pc[18]||c==&pc[19];}
API const char *il2cpp_class_get_name(Class *c){return mode==114&&c==&modal_class?"OtherList":c->name;}
API const char *il2cpp_class_get_namespace(Class *c){return c->ns;}
API Image *il2cpp_class_get_image(Class *c){Image *extra=auto_image(c);if(extra)return extra;return c==&profile_model?&images[3]:c==&pc[9]||c==&nc[5]?&profile_image:&images[0];}
API Class *il2cpp_class_get_declaring_type(Class *c){if(mode==161&&c==&pc[10])return NULL;if(c==&pc[19])return &pc[18];if(c>=&pc[10]&&c<=&pc[16])return &pc[2];return NULL;}
API Class *il2cpp_class_get_parent(Class *c){if(c==&ac[3])return &ac[4];if(c==&ac[4])return &ac[5];if(c==&ac[6])return &ac[7];return NULL;}
API Class *il2cpp_class_get_nested_types(Class *c,void **cursor){uintptr_t i=(uintptr_t)*cursor;if(c!=&pc[2]||i>=(mode==160?6:7))return NULL;*cursor=(void *)(i+1);return &pc[10+i];}
API Type *il2cpp_method_get_param(Method *m,unsigned int n){if(m==&pm[20])return n==0?&pentry:n==1?&pbool:n==2?&presource:NULL;return n==0?m->param:NULL;}
API Class *il2cpp_method_get_class(Method *m){return m->klass;}
API unsigned char il2cpp_type_is_byref(Type *t){if(t==&tbylong)return 1;return t==&pbyrow||t==&pbyentry||t==&pwrongref;}
API Class *il2cpp_class_from_type(Type *t){return t->klass;}
API Method *il2cpp_object_get_virtual_method(Object *o,Method *m){(void)o;virtual_calls++;if(mode==176&&m==&pm[3])return &pm[13];return m;}
API int fixture_visible_reads(void){return plist_reads;}
API int fixture_wrong_selection(void){return selected_wrong;}
API int fixture_modal_reads(void){return modal_reads;}
API int fixture_opens(void){return opens;}
API int fixture_cancels(void){return cancels;}
API int fixture_virtual_calls(void){return virtual_calls;}
static Object *active(void){if(delayed_return_at&&phase==3&&clock_ms()>=delayed_return_at){phase=2;delayed_return_at=0;}
 if(phase==3)return &achatvc;if(mode==514&&phase==2)return &replacement;
 if(mode==61)return &other;
 if(mode==71&&phase>0)return &other;
 if(mode==70&&phase==2)return &replacement;
 return phase==1?&filters:&search;
}
static Object *tree_invoke(Method *m,void *obj,void **args,void **exc){
 (void)args;int yes=0;if(m->action>=80)return auto_invoke(m,obj,args,exc);if(m>=&pm[5]&&m<=&pm[8])obj=((char *)obj)-sizeof(void *);
 if(stress_mode()){
  int owned=(m->action>=45&&m->action<=48)||obj==&precord||obj==&pentryobj||obj==&pavatar||obj==&puser;
  int i;if(stress_index(obj,stress_rows,24)>=0||stress_index(obj,stress_cells,24)>=0||stress_index(obj,stress_parents,21)>=0)owned=1;
  for(i=0;i<24;i++)if(obj==&stress_wrap[i][0]||obj==&stress_wrap[i][1])owned=1;
  if(owned&&!pinned(obj))pin_errors++;
 }
 if(mode==67&&m->action==15){*exc=&exception;return NULL;}
 switch(m->action){
 case 68:
  if(obj!=&puser){selected_wrong++;*exc=&exception;return NULL;}
  id_reads++;longnumber=mode==254?0:(mode==251||mode==509)?1:mode==256?id_reads:stress_current_row+1;return &longbox;
 case 65:
  friend_reads++;if(obj!=&model_obj){selected_wrong++;*exc=&exception;return NULL;}
  if(!pinned(obj))pin_errors++;
  if(mode==218||(mode==255&&opens==3)){*exc=&exception;return NULL;}
  if(batch_mode()){longnumber=stress_current_row%4==0?0:stress_current_row%4==1?49:stress_current_row%4==2?50:97;return &longbox;}
  longnumber=mode==211?50:mode==212?0:mode==213?-1:mode==214?1000001:mode==219?(friend_reads==1?49:50):mode==221?INT64_C(4294967393):mode==222?INT64_MAX:mode==235?(-INT64_C(4294967296)+97):mode==210?49:97;return &longbox;
 case 66:
  model_reads++;
  if(obj!=&pcontent){selected_wrong++;*exc=&exception;return NULL;}
  if(mode==224&&model_reads==1)return NULL;
  if(mode==226)return &potheruser;
  return mode==223&&friend_reads?&other_model:&model_obj;
 case 67:
  actual_reads++;
  if(mode==239){*exc=&exception;return NULL;}
  if(obj!=&model_obj){selected_wrong++;*exc=&exception;return NULL;}
  pnumber=mode==227||(mode==225&&actual_reads==1)||(mode==231&&friend_reads)?0:1;return &pbox;
 case 62:return mode==182?NULL:&pentrylist;
 case 63:pnumber=1;return &pbox;
 case 64:if(!args||!args[0]||*(int *)args[0]!=0){selected_wrong++;*exc=&exception;return NULL;}entry_reads++;return mode==153?&other:mode==188||(mode==183&&entry_reads==1)?&ppromoentry:&pentryobj;
 case 40:return mode==200?NULL:&ptable;
 case 41:return &pvisiblelist;
 case 42:plist_reads++;if(mode==149)slow();pnumber=stress_mode()?stress_count():mode==154?25:mode==132?0:1;return &pbox;
 case 43:
  if(mode==207){
#ifdef _WIN32
   Sleep(20);
#else
   struct timespec delay={0,20000000};nanosleep(&delay,NULL);
#endif
  }
  if(stress_mode()){int index=args&&args[0]?*(int *)args[0]:-1;if(index<0||index>=stress_count()){selected_wrong++;*exc=&exception;return NULL;}return &stress_rows[index];}
  if(mode==175)return &potheruser;row_reads++;if(mode==157&&row_reads%2==0)return &other;if(mode==185&&row_reads==2)return &preplacementrow;if(!args||!args[0]||*(int *)args[0]!=0){selected_wrong++;*exc=&exception;return NULL;}return &prow;
 case 44:
  if(stress_mode()){
   int row=stress_index(obj,stress_rows,24),i;
   if(mode==194&&!blocked){blocked=1;slow();}
   if(++pi_count>=1024)pi_count=1;iterator_allocations++;pi[pi_count].index=-1;pi[pi_count].view=obj;pi[pi_count].source=0;
   if(row>=0)pi[pi_count].source=mode==196?17:1;
   for(i=0;i<24;i++)if(obj==&stress_wrap[i][0]||obj==&stress_wrap[i][1])pi[pi_count].source=1;
   return (Object *)&pi[pi_count];
  }
  pi[0].source=obj==&prow?(mode==180?2:1):0;pi[0].index=-1;return (Object *)&pi[0];
 case 45:
  if(stress_mode()){PIterator copy=*(PIterator *)obj;if(++pi_count>=1024)pi_count=1;iterator_allocations++;pi[pi_count]=copy;return (Object *)&pi[pi_count];}
  if(pi_count>=3)pi_count=0;pi_count++;pi[pi_count]=*(PIterator *)obj;return (Object *)&pi[pi_count];
 case 46:pnumber=mode==155?17:((PIterator *)obj)->source;return &pbox;
 case 47:
  if(mode==195&&((PIterator *)obj)->view==&stress_wrap[6][1]){*exc=&exception;return NULL;}
  yes=++((PIterator *)obj)->index<((PIterator *)obj)->source;break;
 case 48:
  if(stress_mode()){Object *source=((PIterator *)obj)->view;int i=stress_index(source,stress_rows,24),j;if(i>=0)return &stress_wrap[i][0];for(j=0;j<24;j++){if(source==&stress_wrap[j][0])return &stress_wrap[j][1];if(source==&stress_wrap[j][1])return &stress_cells[j];}selected_wrong++;return NULL;}
  return (mode==180&&((PIterator *)obj)->index==0)||mode==181?&ppromocell:&pcell;
 case 49:case 50:case 51:return mode==201?NULL:&precord;
 case 52:if(!args||(args[0]!=&pentryobj&&args[0]!=&ppromoentry)){selected_wrong++;*exc=&exception;return NULL;}promo_reads++;yes=mode==192||mode==133||args[0]==&ppromoentry||(mode==186&&promo_reads==2)||(mode==187&&promo_reads%2==0);break;
 case 53:
  if((mode==516&&!auto_slowed++)||mode==517){
#ifdef _WIN32
   Sleep(120);
#else
   struct timespec delay={0,120000000};nanosleep(&delay,NULL);
#endif
  }
  if(stress_mode()){int i=stress_index(obj,stress_cells,24);stress_current_row=i;return batch_mode()||mode==193||i==stress_count()-1?&pentryobj:&ppromoentry;}
  if(obj==&ppromocell)return &ppromoentry;return mode==134?NULL:&pentryobj;
 case 54:return mode==199?NULL:&pavatar;
 case 55:if(mode==198||(mode==202&&entry_reads==1))return NULL;return &puser;
 case 56:avatar_reads++;return mode==135||mode==206||(mode==184&&avatar_reads==1)?&potheruser:&puser;
 case 57:yes=mode==136||(mode==193&&stress_current_row!=stress_count()-1);break;
 case 58:profile_reads++;if(mode==519&&phase==1&&clock_ms()<(uint64_t)opened_ms+started_ms+6000)return NULL;if(mode==156)return &other;if(mode==137)return NULL;return mode==140&&profile_reads>2?&pothercontent:&pcontent;
 case 59:return mode==138||mode==189||(mode==220&&friend_reads>0)?&potheruser:&puser;
 case 60:
  if(stress_mode()&&(!pinned(&pentryobj)||!pinned(&pavatar)||!pinned(&puser)))pin_errors++;
  if(!args||args[0]!=&pentryobj||!args[1]||*(unsigned char *)args[1]!=0||args[2]!=&pavatar){selected_wrong++;*exc=&exception;return NULL;}
  auto_action();opened_ms=(int)(clock_ms()-started_ms);opens++;if(mode==148)slow();if(mode==141){*exc=&exception;return NULL;}if(mode!=142)phase=1;return NULL;
 case 61:auto_action();closed_ms=(int)(clock_ms()-started_ms);cancels++;if(mode==143||mode==507){*exc=&exception;return NULL;}if(mode!=144)phase=2;return NULL;

 case 10:if(mode==77)slow();return mode>=80?&app_root:active();
 case 11:if(mode>=98)return NULL;if(mode==88)return &view;return (mode==72||phase!=1||mode==87)?NULL:&view;
 case 12:if(obj==&app_root)return mode==81?&dv_nav:&ui_nav;return NULL;
 case 13:return mode==88?&other:active();
 case 14:yes=mode!=96;break;
 case 15:if(mode==139&&obj==&pcontent)return NULL;return &view;
 case 16:yes=(mode==73);break;
 case 17:yes=0;break;
 case 18:
  if(stress_mode()){
   int i=stress_index(obj,stress_rows,24),j;
   if(obj==&pavatar)return &stress_cells[batch_mode()?stress_current_row:stress_count()-1];
   if(i>=0)return mode==197?&stress_rows[i]:mode==191?&stress_parents[0]:&ptable;
   i=stress_index(obj,stress_cells,24);if(i>=0)return &stress_wrap[i][1];
   for(j=0;j<24;j++){if(obj==&stress_wrap[j][1])return &stress_wrap[j][0];if(obj==&stress_wrap[j][0])return &stress_rows[j];}
   i=stress_index(obj,stress_parents,21);if(i>=0)return i==20?&ptable:&stress_parents[i+1];
  }
  if(obj==&ppromocell)return &prow;if(obj==&pavatar)return mode==205?NULL:&pcell;if(obj==&pcell)return &prow;if(obj==&prow)return &ptable;
  if(obj==&ptable)return &window;
  if(mode==94){if(obj==&view)return &view_chain[0];if((uintptr_t)obj>=(uintptr_t)&view_chain[0]&&(uintptr_t)obj<(uintptr_t)&view_chain[34])return ((Object *)obj)+1;}
  if(mode==95)return obj==&other_window?NULL:&other_window;
  if(mode==68||mode==93)return NULL;if(mode==91)return &view;return &window;
 case 19:if(mode==204&&obj==&pavatar){yes=1;break;}hidden_reads++;if(mode==131&&obj==&prow){yes=1;break;}yes=mode==63||(mode==97&&hidden_reads<4);break;
 case 20:yes=mode!=64&&!(mode==203&&obj==&pavatar);break;
 case 21:yes=mode!=65;break;
 case 22:opens++;if(mode==79)slow();if(mode==66){*exc=&exception;return NULL;}if(mode!=69&&mode!=76)phase=1;return NULL;
 case 24:yes=mode!=92&&phase==1;break;
 case 25:return mode==81?&dv_nav:&ui_nav;
 case 26:yes=0;break;
 case 27:if(mode==158)return &other;if(mode==159&&phase==2)return &replacement;if(mode>=500)return active();if(mode>=98)return &search;return mode==82?&other:mode==83?NULL:active();
 case 28:return &ui_container;
 case 29:
  if(mode==84)return obj==&ui_nav?&ui_container:&ui_nav;
  if(mode==85){if(obj==&ui_nav)return &deep[0];if((uintptr_t)obj>=(uintptr_t)&deep[0]&&(uintptr_t)obj<(uintptr_t)&deep[13])return ((Object *)obj)+1;}
  if(mode==81){if(obj==&dv_nav)return &dv_container;if(obj==&ui_container)return &tabs;}
  return &tabs;
 case 30:case 31:yes=mode==86;break;
 case 32:if(mode>=500){yes=0;break;}yes=mode==87||((obj==&app_root||obj==&search)&&phase==1);break;
 case 33:if(mode>=500)return NULL;
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
