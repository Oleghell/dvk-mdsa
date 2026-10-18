/* Owned synthetic UIView graph; never loads an APK or real UI. */
#include <time.h>
#define TREE_FIXTURE
#include "root_fixture.c"
static Class tc[]={
 {"UIKit","UIView"},{"UIKit","Control"},{"UIKit","Button"},{"UIKit","Label"},
 {"UIKit","TextField"},{"UIKit","UITextView"},{"DV","DVButton"},
 {"Core.Collections","ReadOnlyList`1"},{"Fixture","Int32"},{"Fixture","Unknown"}};
static Type tint={8,NULL},tview={18,&tc[0]},tlist={18,&tc[7]};
static Method tm[]={
 {"get_EffectivelyHidden",&tc[0],0,&tbool,10,0,NULL},
 {"get_UserInteractionEnabled",&tc[0],0,&tbool,11,0,NULL},
 {"get_Subviews",&tc[0],0,&tlist,12,0,NULL},
 {"get_Enabled",&tc[1],0,&tbool,13,0,NULL},
 {"get_Count",&tc[7],0,&tint,14,0,NULL},
 {"get_Item",&tc[7],0,&tview,15,1,&tint}};
typedef struct Node {Object base;int index;} Node;
typedef struct List {Object base;int owner;} List;
typedef struct BoxInt {Object base;int number;} BoxInt;
static Node nodes[100];static List lists[100];static BoxInt boxed_int;
static int wrong_index;
static void tree_init(int m){int i;for(i=0;i<100;i++){
 nodes[i].base.klass=&tc[i%5+2];nodes[i].index=i;lists[i].base.klass=&tc[7];lists[i].owner=i;}
 boxed_int.base.klass=&tc[8];wrong_index=0;
 if(m==24)lists[0].base.klass=&tc[9];
}
static Class *tree_class(Image *im,const char *ns,const char *name){int i;for(i=0;i<8;i++){
 if(!strcmp(ns,tc[i].ns)&&!strcmp(name,tc[i].name)&&im==&images[i==6?3:0])return &tc[i];}return NULL;}
static Method *tree_method(Class *c,const char *name,int arity){int i;for(i=0;i<6;i++){
 if(!strcmp(name,tm[i].name)&&arity==(int)tm[i].arity&&
 (c==tm[i].klass||(tm[i].klass==&tc[0]&&(c==&classes[1]||c==&tc[1]||c==&tc[2]||c==&tc[3]||c==&tc[4]||c==&tc[5]||c==&tc[6]))))return &tm[i];}return NULL;}
static unsigned char tree_assignable(Class *a,Class *b){
 if(a==&tc[0])return b==&classes[1]||b==&tc[0]||b==&tc[1]||b==&tc[2]||b==&tc[3]||b==&tc[4]||b==&tc[5]||b==&tc[6];
 if(a==&tc[1])return b==&tc[1]||b==&tc[2]||b==&tc[4]||b==&tc[6];
 if(a==&tc[2])return b==&tc[6];return 0;
}
static void *tree_unbox(Object *o){return o==&boxed_int.base?&boxed_int.number:NULL;}
API const char *il2cpp_class_get_name(Class *c){return c->name;}
API const char *il2cpp_class_get_namespace(Class *c){return c->ns;}
API Image *il2cpp_class_get_image(Class *c){return c==&tc[6]?&images[3]:&images[0];}
API unsigned char il2cpp_class_is_valuetype(Class *c){return mode==26&&c==&tc[7];}
API Class *il2cpp_class_from_type(Type *t){return t->klass;}
API Type *il2cpp_method_get_param(Method *m,uint32_t i){return i<m->arity?m->param:NULL;}
API int fixture_wrong_index(void){return wrong_index;}
static Object *tree_invoke(Method *m,void *obj,void **args,void **exc){
 int owner=obj==&window?0:((Node*)obj)->index;
 if(m->action==10||m->action==11||m->action==13){fixture_boxed_bool.value=m->action!=10;return &fixture_boxed_bool;}
 if(m->action==12){
  if(mode==29&&owner==0){clock_t until=clock()+CLOCKS_PER_SEC/5;while(clock()<until){/* synthetic slow getter */}}
  return &lists[owner].base;
 }
 if(m->action==14){
  owner=((List*)obj)->owner;
  if(mode==22){boxed_int.number=4097;return &boxed_int.base;}
  if(mode==28){boxed_int.number=owner<40?3:0;return &boxed_int.base;}
  if(mode==25){boxed_int.number=owner<12?1:0;return &boxed_int.base;}
  boxed_int.number=owner==0?(mode==23?40:3):0;return &boxed_int.base;
 }
 if(m->action==15){int index;
  owner=((List*)obj)->owner;if(!args||!args[0]){wrong_index++;if(exc)*exc=&exception;return NULL;}
  index=*(int*)args[0];if(index<0||index>39){wrong_index++;return NULL;}
  if(mode==21&&index==1)return &window;
  if(mode==27&&index==1){if(exc)*exc=&exception;return NULL;}
  if(mode==28)return &nodes[3*owner+index+1].base;
  if(mode==25)return &nodes[owner+1].base;
  return &nodes[index+1].base;
 }return NULL;
}
