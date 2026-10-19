/* Owned definitions only. No application objects, messages, accounts or keys. */
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#ifdef _WIN32
#define API __declspec(dllexport)
#else
#define API __attribute__((visibility("default")))
#endif

typedef struct Image {const char *name;} Image;
typedef struct Class {const char *ns,*name;int image,parent;} Class;
typedef struct Type {int kind,byref;Class *klass;} Type;
typedef struct Method {const char *name;int owner,flags,arity;Type *ret,*param;} Method;
static Image images[]={{"Core.dll"},{"DV.dll"},{"DV.Messages.dll"},{"mscorlib.dll"}};
static Image *all[]={&images[0],&images[1],&images[2],&images[3]};
static Class classes[]={
 {"DV.Messages","MessagesViewController",2,-1}, /* 0 */
 {"DV.Messages","Chat",2,-1},
 {"DV.CMs","MessagesCM",2,7},
 {"DV.Messages","Message",2,-1},
 {"DV.Messages","TextMessage",2,3},
 {"DV.Messages","MessagesManager",2,-1},
 {"DV.Models","User",1,-1},
 {"DV.CMs","ContentDataList`1",1,8},
 {"DataKit","BaseDataList`1",0,-1},
 {"DataKit","DataField`1",0,10},
 {"DataKit","DataFieldBase`1",0,-1},
 {"System","Boolean",3,-1},
 {"System","Int32",3,-1},
 {"System","Int64",3,-1},
 {"System","String",3,-1},
 {"UIKit","GenericString",0,-1},
 {"DataKit","Unrelated",0,-1}
};
static Type tb={2,0,&classes[11]},ti={8,0,&classes[12]},tl={10,0,&classes[13]},ts={14,0,&classes[14]},
 tc={18,0,&classes[1]},tu={18,0,&classes[6]},th={18,0,&classes[2]},tm={18,0,&classes[5]},
 tmsg={18,0,&classes[3]},td={21,0,&classes[9]},tvar={19,0,NULL},tg={21,0,&classes[15]},tbyref={14,1,&classes[14]};
static Method methods[]={
 {"get_Chat",0,0,0,&tc,NULL},{"get_User",0,0,0,&tu,NULL},
 {"get_Id",1,0,0,&tl,NULL},{"get_DialogOpponent",1,0,0,&tu,NULL},
 {"get_Dialog",1,0,0,&tb,NULL},{"get_IsActual",1,0,0,&tb,NULL},
 {"get_IsDraftChat",1,0,0,&tb,NULL},{"get_HasMessagesCM",1,0,0,&tb,NULL},
 {"get_MessagesCM",1,0,0,&th,NULL},{"get_MessagesManager",1,0,0,&tm,NULL},
 {"get_CurrentUserId",5,0,0,&tl,NULL},{"get_Id",6,0,0,&tl,NULL},
 {"get_Name",6,0,0,&ts,NULL},{"get_Id",3,0,0,&tl,NULL},
 {"get_SenderId",3,0,0,&tl,NULL},{"get_ChatId",3,0,0,&tl,NULL},
 {"get_IsMine",3,0,0,&tb,NULL},{"get_Text",4,0,0,&ts,NULL},
 {"get_Count",8,0,0,&ti,NULL},{"get_Item",8,0,1,&tmsg,&ti},
 {"get_LoadInProgress",7,0,0,&tb,NULL},{"get_AllIsLoaded",7,0,0,&td,NULL},
 {"get_Value",10,0,0,&tb,NULL}
};
static int mode,attached,domain,thread,invokes,values,keeps,detaches,lookups;
API void fixture_init(int value){mode=value;attached=value==11;invokes=values=keeps=detaches=lookups=0;}
API int fixture_invokes(void){return invokes;}
API int fixture_values(void){return values;}
API int fixture_keeps(void){return keeps;}
API int fixture_attached(void){return attached;}
API int fixture_detaches(void){return detaches;}
API int fixture_lookups(void){return lookups;}
API void *il2cpp_domain_get(void){return mode==12?NULL:&domain;}
API void *il2cpp_thread_current(void){return attached?&thread:NULL;}
API void *il2cpp_thread_attach(void *d){if(mode==9||d!=&domain)return NULL;attached=1;return &thread;}
API void il2cpp_thread_detach(void *t){detaches++;if(t==&thread&&mode!=10)attached=0;}
API Image **il2cpp_domain_get_assemblies(void *d,size_t *count){(void)d;*count=mode==13?2049:4;return all;}
API Image *il2cpp_assembly_get_image(Image *im){return im;}
API const char *il2cpp_image_get_name(Image *im){return im->name;}
API Class *il2cpp_class_from_name(Image *im,const char *ns,const char *name){
 int i;lookups++;
 for(i=0;i<17;i++)if(im==&images[classes[i].image]&&!strcmp(ns,classes[i].ns)&&!strcmp(name,classes[i].name)){
  if(mode==1&&i==4)return NULL;
  if(mode==20&&i==4)return &classes[15];
  return &classes[i];
 }
 return NULL;
}
API Class *il2cpp_class_get_parent(Class *k){if(mode==8&&k==&classes[8])return &classes[2];return k->parent<0?NULL:&classes[k->parent];}
API Image *il2cpp_class_get_image(Class *k){return &images[k->image];}
API const char *il2cpp_class_get_name(Class *k){return mode==16&&k==&classes[4]?"PRIVATE\nBAD":k->name;}
API const char *il2cpp_class_get_namespace(Class *k){return k->ns;}
API Method *il2cpp_class_get_method_from_name(Class *k,const char *name,int arity){
 int i,depth;
 for(depth=0;k&&depth<10;depth++,k=k->parent<0?NULL:&classes[k->parent])
  for(i=0;i<23;i++)if(k==&classes[methods[i].owner]&&arity==methods[i].arity&&!strcmp(name,methods[i].name)){
   if(mode==2&&i==17)return NULL;
   return &methods[i];
  }
 return NULL;
}
API Class *il2cpp_method_get_class(Method *m){return mode==7&&m==&methods[22]?&classes[16]:&classes[m->owner];}
API uint32_t il2cpp_method_get_param_count(Method *m){return mode==22&&m==&methods[17]?256:(uint32_t)m->arity;}
API uint32_t il2cpp_method_get_flags(Method *m,uint32_t *impl){*impl=0;return mode==5&&m==&methods[14]?16:(uint32_t)m->flags;}
API Type *il2cpp_method_get_return_type(Method *m){
 if(m==&methods[19]){if(mode==3)return &tvar;if(mode==21)return &tu;}
 if(m==&methods[17]){if(mode==4)return &tg;if(mode==14)return &tbyref;}
 return m->ret;
}
API Type *il2cpp_method_get_param(Method *m,uint32_t n){(void)n;return mode==6&&m==&methods[19]?&tb:m->param;}
API int il2cpp_type_get_type(Type *t){return t->kind;}
API int il2cpp_type_is_byref(Type *t){return t->byref;}
API Class *il2cpp_class_from_type(Type *t){return t->klass;}
API int il2cpp_class_is_assignable_from(Class *base,Class *child){
 int i;if(mode==15&&base==&classes[3]&&child==&classes[4])return 0;
 for(i=0;child&&i<10;i++,child=child->parent<0?NULL:&classes[child->parent])if(base==child)return 1;
 return 0;
}
/* Forbidden APIs are counters, not dependencies of the checker. */
API void *il2cpp_runtime_invoke(void *a,void *b,void *c,void *d){(void)a;(void)b;(void)c;(void)d;invokes++;return NULL;}
API void il2cpp_field_get_value(void *a,void *b,void *c){(void)a;(void)b;(void)c;values++;}
API void *il2cpp_gchandle_new(void *a,int b){(void)a;(void)b;keeps++;return NULL;}
