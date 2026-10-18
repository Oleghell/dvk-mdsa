/* Owned synthetic fixture. No Android, app logic, input or private data. */
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#define API __declspec(dllexport)
static DWORD main_id;
#define TID() GetCurrentThreadId()
#else
#include <pthread.h>
#define API __attribute__((visibility("default")))
static pthread_t main_id;
#define TID() pthread_self()
#endif
typedef struct Class { const char *ns,*name; } Class;
typedef struct Type { int kind; } Type;
typedef struct Method { const char *name; Class *klass; uint32_t flags; Type *type; int action; } Method;
typedef struct Image { const char *name; } Image;
typedef struct Object { Class *klass; unsigned char value; } Object;
static Class classes[]={{"UIKit","UIRuntime"},{"UIKit","UIWindow"},{"UIKit","UIRuntimeComponent"},{"UnityEngine","UnitySynchronizationContext"}};
static Type tvoid={1},tbool={2},tclass={18};
static Method methods[]={
 {"get_IsOnMainThread",&classes[0],16,&tbool,1},
 {"get_OptionalInstance",&classes[0],16,&tclass,2},
 {"get_MainWindow",&classes[0],0,&tclass,3},
 {"Update",&classes[2],0,&tvoid,0},
 {"OnUnityUpdate",&classes[0],0,&tvoid,0},
 {"ExecuteTasks",&classes[3],16,&tvoid,0}};
static Image images[]={{"Core.dll"},{"UIKit.Unity.dll"},{"UnityEngine.CoreModule.dll"}};
static Image *image_array[]={&images[0],&images[1],&images[2]};
static Object runtime={&classes[0],0},window={&classes[1],0},fixture_boxed_bool={NULL,0};
typedef struct Handle {Object *target;int live;} Handle;
static Handle handles[2];
static int domain,thread,exception,mode,attached,managed_calls,off_thread_calls,live_handles,bad_frees;
API void fixture_init(int m) { mode=m;main_id=TID();attached=1;managed_calls=off_thread_calls=live_handles=bad_frees=0;handles[0].live=handles[1].live=0;if(m==6)methods[0].type=&tclass;if(m==8)runtime.klass=&classes[1]; }
API int fixture_handles(void) {return live_handles;}
API int fixture_bad_frees(void) {return bad_frees;}
API int fixture_high_handles(void) {return ((uintptr_t)&handles[0]>>32)!=0;}
API int fixture_calls(void) {return managed_calls;}
API int fixture_off_thread_calls(void) {return off_thread_calls;}
API void *il2cpp_domain_get(void) {return &domain;}
API void *il2cpp_thread_current(void) {return attached?&thread:NULL;}
API void *il2cpp_thread_attach(void *d) {(void)d;attached=1;return &thread;}
API void il2cpp_thread_detach(void *t) {(void)t;attached=0;}
API Image **il2cpp_domain_get_assemblies(void *d,size_t *n) {(void)d;*n=3;return image_array;}
API Image *il2cpp_assembly_get_image(Image *a) {return a;}
API const char *il2cpp_image_get_name(Image *i) {return i->name;}
API Class *il2cpp_class_from_name(Image *im,const char *ns,const char *name) {
 size_t i;for(i=0;i<4;i++)if(!strcmp(ns,classes[i].ns)&&!strcmp(name,classes[i].name)){
  if((i<2&&im==&images[0])||(i==2&&im==&images[1])||(i==3&&im==&images[2]))return &classes[i];
 }return NULL;
}
API Method *il2cpp_class_get_method_from_name(Class *c,const char *name,int arity) {
 size_t i;if(arity!=0)return NULL;for(i=0;i<6;i++)if(methods[i].klass==c&&!strcmp(methods[i].name,name))return &methods[i];return NULL;
}
API uint32_t il2cpp_method_get_param_count(Method *m) {(void)m;return 0;}
API uint32_t il2cpp_method_get_flags(Method *m,uint32_t *iflags) {*iflags=0;return m->flags;}
API Type *il2cpp_method_get_return_type(Method *m) {return m->type;}
API int il2cpp_type_get_type(Type *t) {return t->kind;}
API void *il2cpp_object_unbox(Object *o) {return &o->value;}
API Class *il2cpp_object_get_class(Object *o) {return o->klass;}
API unsigned char il2cpp_class_is_assignable_from(Class *a,Class *b) {return a==b;}
/* Unity 6 API: typedef void* Il2CppGCHandle. Preserve all pointer bits. */
API void *il2cpp_gchandle_new(Object *o,unsigned char pin) {
 int i;(void)pin;for(i=0;i<2;i++)if(!handles[i].live){handles[i].live=1;handles[i].target=o;live_handles++;return &handles[i];}return NULL;
}
API void il2cpp_gchandle_free(void *h) {
 int i;for(i=0;i<2;i++)if(h==&handles[i]&&handles[i].live){handles[i].live=0;handles[i].target=NULL;live_handles--;return;}bad_frees++;
}
API Object *il2cpp_runtime_invoke(Method *m,void *obj,void **args,void **exc) {
 (void)obj;(void)args;if(exc)*exc=NULL;if(m->action==0){if(mode==9&&exc)*exc=&exception;return NULL;}
 managed_calls++;if(TID()!=main_id)off_thread_calls++;
 if(mode==4&&m->action==1){if(exc)*exc=&exception;return NULL;}
 if(m->action==1){fixture_boxed_bool.value=(mode!=1&&TID()==main_id);return &fixture_boxed_bool;}
 if(m->action==2)return mode==2?NULL:&runtime;
 if(m->action==3)return mode==3?NULL:&window;
 return NULL;
}
API void fixture_tick(void) {void *exc=NULL;il2cpp_runtime_invoke(&methods[3],&runtime,NULL,&exc);}
