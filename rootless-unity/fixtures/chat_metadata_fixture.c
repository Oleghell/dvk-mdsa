/* Owned metadata definitions only. No Android, network or real messages. */
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#ifdef _WIN32
#define API __declspec(dllexport)
#else
#define API __attribute__((visibility("default")))
#endif
typedef struct Image{const char *name;}Image;
typedef struct Class{const char *ns,*name;int image,parent;}Class;
typedef struct Type{int kind,byref;Class *klass;}Type;
typedef struct Method{const char *name;int owner,flags,arity;Type *ret,*param;}Method;
typedef struct Field{const char *name;int owner,flags;Type *type;}Field;
static Image images[]={{"Core.dll"},{"DV.dll"},{"DV.Profile.dll"},{"DV.Messages.dll"},{"mscorlib.dll"}};
static Image *all[]={&images[0],&images[1],&images[2],&images[3],&images[4]};
static Class classes[]={
 {"DV.Profiles","ProfilesQueueViewController",2,-1},{"DV.Profiles","ProfileOverlayView",2,-1},
 {"DV.Messages","MessagesViewController",3,-1},{"DV.Messages","Chat",3,-1},
 {"DV.CMs","MessagesCM",3,7},{"DV.Messages","MessagesManager",3,-1},
 {"DV.Routers.Messages","MessagesRouter",3,-1},
 {"DV.CMs","ContentDataList`1",3,8},{"DataKit","BaseDataList`1",0,9},
 {"System","Object",4,-1},{"System","Void",4,-1},{"System","Boolean",4,-1},
 {"System","Int32",4,-1},{"DV.Models","User",1,-1}};
static Type tv={1,0,&classes[10]},tb={2,0,&classes[11]},ti={8,0,&classes[12]},tc={18,0,&classes[3]},tm={18,0,&classes[4]},to={18,0,&classes[1]},tu={18,0,&classes[13]};
static Method methods[]={
 {"OnMessageButton",1,0,0,&tv,NULL},{"get_Chat",2,0,0,&tc,NULL},
 {"get_MessagesCM",3,0,0,&tm,NULL},{"get_IsActual",3,0,0,&tb,NULL},
 {"get_IsLoading",7,0,0,&tb,NULL},{"get_HasMore",7,0,0,&tb,NULL},
 {"get_Count",8,0,0,&ti,NULL},{"ReadOnlySignatureExample",4,0,1,&tv,&tu}};
static Field fields[]={{"m_OverlayView",0,0,&to},{"m_User",1,0,&tu},{"m_Chat",2,0,&tc}};
static int mode,attached,domain,thread,invokes,values,keeps,detach_calls;
API void fixture_init(int m){mode=m;attached=m==7;invokes=values=keeps=detach_calls=0;}
API int fixture_attached(void){return attached;}
API int fixture_invokes(void){return invokes;}
API int fixture_values(void){return values;}
API int fixture_keeps(void){return keeps;}
API int fixture_detaches(void){return detach_calls;}
API void *il2cpp_domain_get(void){return mode==5?NULL:&domain;}
API void *il2cpp_thread_current(void){return attached?&thread:NULL;}
API void *il2cpp_thread_attach(void *d){if(mode==9||d!=&domain)return NULL;attached=1;return &thread;}
API void il2cpp_thread_detach(void *t){detach_calls++;if(t==&thread&&mode!=6)attached=0;}
API Image **il2cpp_domain_get_assemblies(void *d,size_t *n){(void)d;*n=mode==10?2049:5;return all;}
API Image *il2cpp_assembly_get_image(Image *i){return i;}
API const char *il2cpp_image_get_name(Image *i){return i->name;}
API Class *il2cpp_class_from_name(Image *im,const char *ns,const char *name){int i;for(i=0;i<14;i++)if(im==&images[classes[i].image]&&!strcmp(ns,classes[i].ns)&&!strcmp(name,classes[i].name)){if(mode==1&&i==1)return NULL;return &classes[i];}return NULL;}
API const char *il2cpp_class_get_name(Class *k){return mode==4&&k==&classes[4]?"PRIVATE\nBAD":k->name;}
API const char *il2cpp_class_get_namespace(Class *k){return k->ns;}
API Image *il2cpp_class_get_image(Class *k){return &images[k->image];}
API Class *il2cpp_class_get_parent(Class *k){if(mode==2&&k==&classes[8])return &classes[4];if(mode==11&&k==&classes[4])return k;return k->parent<0?NULL:&classes[k->parent];}
API Method *il2cpp_class_get_methods(Class *k,void **cursor){size_t i=(size_t)*cursor;if(mode==13&&k==&classes[1])return &methods[0];for(;i<8;i++)if(&classes[methods[i].owner]==k){*cursor=(void *)(i+1);return &methods[i];}return NULL;}
API Field *il2cpp_class_get_fields(Class *k,void **cursor){size_t i=(size_t)*cursor;if(mode==14&&k==&classes[0])return &fields[0];for(;i<3;i++)if(&classes[fields[i].owner]==k){*cursor=(void *)(i+1);return &fields[i];}return NULL;}
API const char *il2cpp_field_get_name(Field *f){return f->name;}
API Type *il2cpp_field_get_type(Field *f){return mode==16?NULL:f->type;}
API uint32_t il2cpp_field_get_flags(Field *f){return f->flags;}
API const char *il2cpp_method_get_name(Method *m){return m->name;}
API Class *il2cpp_method_get_class(Method *m){return mode==8&&m==&methods[0]?&classes[0]:&classes[m->owner];}
API uint32_t il2cpp_method_get_param_count(Method *m){return mode==15?256:mode==3&&m==&methods[7]?17:m->arity;}
API Type *il2cpp_method_get_param(Method *m,uint32_t n){(void)n;return m->param;}
API uint32_t il2cpp_method_get_flags(Method *m,uint32_t *impl){*impl=0;return m->flags;}
API Type *il2cpp_method_get_return_type(Method *m){return m->ret;}
API int il2cpp_type_get_type(Type *t){return t->kind;}
API int il2cpp_type_is_byref(Type *t){return t->byref;}
API Class *il2cpp_class_from_type(Type *t){return t->klass;}
/* Forbidden object/action APIs are canaries, not dependencies. */
API void *il2cpp_runtime_invoke(void *a,void *b,void *c,void *d){(void)a;(void)b;(void)c;(void)d;invokes++;return NULL;}
API void il2cpp_field_get_value(void *a,void *b,void *c){(void)a;(void)b;(void)c;values++;}
API void *il2cpp_gchandle_new(void *a,int b){(void)a;(void)b;keeps++;return NULL;}
