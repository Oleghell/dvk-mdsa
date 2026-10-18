/* Synthetic C ABI fixture only. Not an application helper; never put in an APK. */
#include <stddef.h>
#include <string.h>
#ifdef _WIN32
#define API __declspec(dllexport)
#else
#define API __attribute__((visibility("default")))
#endif
typedef struct Image { const char *name; } Image;
typedef struct Assembly { Image *image; } Assembly;
typedef struct Klass { const char *ns; const char *name; int image; } Klass;
static int domain, thread, method, attached, mode;
static Image images[]={{"UnityEngine.CoreModule.dll"},{"UnityEngine.UI.dll"},{"mscorlib.dll"},{"PRIVATE_UNKNOWN_ASSEMBLY.dll"},{"Core.dll"},{"DV.dll"},{"UIKit.Unity.dll"}};
static Assembly assemblies[]={{&images[0]},{&images[1]},{&images[2]},{&images[3]},{&images[4]},{&images[5]},{&images[6]}};
static Assembly *array[]={&assemblies[0],&assemblies[1],&assemblies[2],&assemblies[3],&assemblies[4],&assemblies[5],&assemblies[6]};
static Klass classes[]={{"UnityEngine","Object",0},{"UnityEngine","GameObject",0},
 {"UnityEngine","Resources",0},{"UnityEngine.UI","Button",1},
 {"System.Threading","SynchronizationContext",2},{"UIKit","UIRuntime",4},
 {"UIKit","UIView",4},{"DV","DVButton",5},{"UIKit","UIRuntimeComponent",6}};
API void fixture_set_mode(int value) { mode=value; attached=value==4; }
API int fixture_is_attached(void) { return attached; }
API void *il2cpp_domain_get(void) { return mode==1?NULL:&domain; }
API void *il2cpp_thread_current(void) { return attached?&thread:NULL; }
API void *il2cpp_thread_attach(void *d) { if(d!=&domain)return NULL; attached=1;return &thread; }
API void il2cpp_thread_detach(void *t) { if(t==&thread)attached=0; }
API Assembly **il2cpp_domain_get_assemblies(void *d,size_t *n) { *n=mode==2?2049:mode==3?0:mode==5?7:4;return array; }
API Image *il2cpp_assembly_get_image(Assembly *a) { return a->image; }
API const char *il2cpp_image_get_name(Image *i) { return i->name; }
API Klass *il2cpp_class_from_name(Image *image,const char *ns,const char *name) {
 size_t i;for(i=0;i<sizeof(classes)/sizeof(classes[0]);i++)
  if(image==&images[classes[i].image]&&!strcmp(ns,classes[i].ns)&&!strcmp(name,classes[i].name))return &classes[i];
 return NULL;
}
API void *il2cpp_class_get_method_from_name(Klass *c,const char *name,int arity) {
 if(!strcmp(c->name,"UIRuntime")&&!strcmp(name,"get_OptionalInstance")&&arity==0)return &method;
 if(!strcmp(c->name,"UIView")&&!strcmp(name,"get_Subviews")&&arity==0)return &method;
 if(!strcmp(c->name,"DVButton")&&!strcmp(name,"get_Text")&&arity==0)return &method;
 if(!strcmp(c->name,"UIRuntimeComponent")&&!strcmp(name,"Update")&&arity==0)return &method;
 if(!strcmp(c->name,"Button")&&!strcmp(name,"get_onClick")&&arity==0)return &method;
 if(!strcmp(c->name,"Resources")&&!strcmp(name,"FindObjectsOfTypeAll")&&arity==1)return &method;
 return NULL;
}
