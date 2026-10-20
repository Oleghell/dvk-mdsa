/* Owned ABI fixture for exactly one online-only settings operation. No APKs. */
#define SEARCH_SETTINGS_FIXTURE
#include "navigation_fixture.c"
#ifdef CITY_FIXTURE
static void city_init(int);
static Class *city_class(Image *,const char *,const char *);
static Method *city_method(Class *,const char *,int);
static Object *city_invoke(Method *,void *,void **,void **);
static int city_assignable(Class *,Class *);
static Object *city_geocode(Object *);
static int city_distance(Object *);
static void city_apply(void);
#endif
static Class oc[]={
 {"DV","SearchPeopleFilterViewController"},{"DV.Search","SearchFilterBaseViewController"},
 {"DV.Search","SearchFilter"},{"DV.CMs","SearchCM"}};
static Type otmodel={18,&oc[2]},otpeople={18,&oc[0]},otcm={18,&oc[3]},otstring={14};
static Method om[]={
 {"get_SearchFilter",&oc[3],0,&otmodel,200},
 {"get_SearchFilter",&oc[1],0,&otmodel,201},
 {"get_IsSearchFilterReady",&oc[0],64,&tbool,202},
 {"get_IsSearchFilterValid",&oc[0],64,&tbool,203},
 {"get_OnlineOnly",&oc[2],64,&tbool,204},
 {"set_OnlineOnly",&oc[2],64,&tvoid,205,1,&tbool},
 {"get_GeoCode",&oc[2],64,&otstring,206},
 {"get_RegionCode",&oc[2],64,&otstring,207},
 {"get_ByDistance",&oc[2],64,&tbool,208},
 {"ApplySearchFilter",&oc[1],0,&tvoid,209,1,&otmodel},
 {"OnApplyButton",&nc[5],0,&tvoid,210}};
static Object people={&oc[0],0},model={&oc[2],0},form_model={&oc[2],0},cm={&oc[3],0},changed_cm={&oc[3],0},online_box={NULL,0};
typedef struct Field {Class *parent;Type *type;int slot;} Field;
static Field cm_field={&nc[4],&otcm,1},people_field={&nc[5],&otpeople,2};
typedef struct LocationString {Class *klass;int length;uint16_t chars[4];} LocationString;
static LocationString geo_string={NULL,2,{'A','1',0,0}},changed_geo={NULL,2,{'B','2',0,0}};
static int online_set_calls,online_refresh_calls,online_apply_calls,location_changed,field_reads;
static void online_init(int m){
#ifdef CITY_FIXTURE
 city_init(m);
#endif

 model.value=m==201||m==324;form_model.value=model.value;online_set_calls=online_refresh_calls=online_apply_calls=location_changed=field_reads=0;
 if(m==202)om[5].param=&tint;
 if(m==203)cm_field.type=&otpeople;
 if(m==216)om[9].param=&otpeople;
}
static Class *online_class(Image *im,const char *ns,const char *name){int i;
#ifdef CITY_FIXTURE
 Class *extra=city_class(im,ns,name);if(extra)return extra;
#endif

 if(im!=&nav_image)return NULL;
 for(i=0;i<4;i++)if(!strcmp(ns,oc[i].ns)&&!strcmp(name,oc[i].name))return &oc[i];return NULL;
}
static Method *online_method(Class *c,const char *name,int arity){int i;
#ifdef CITY_FIXTURE
 Method *extra=city_method(c,name,arity);if(extra)return extra;
#endif

 for(i=0;i<11;i++)if(c==om[i].klass&&arity==om[i].arity&&!strcmp(name,om[i].name))return &om[i];return NULL;
}
static int online_assignable(Class *a,Class *b){
#ifdef CITY_FIXTURE
 if(city_assignable(a,b))return 1;
#endif

 return (b==&oc[0]&&(a==&oc[1]||a==&nc[1]))||a==b;
}
static Method *online_virtual(Object *obj,Method *m){
 static Method bad;
 (void)obj;
 if((mode==222&&m==&om[5])||(mode==223&&m==&om[4])){
  bad=*m;if(mode==222)bad.param=&tint;else bad.type=&tint;return &bad;
 }
 return m;
}
static Object *online_invoke(Method *m,void *obj,void **args,void **exc){
 int yes=0;
#ifdef CITY_FIXTURE
 if(m->action>=300)return city_invoke(m,obj,args,exc);
 if(mode>=300&&m->action==206)return city_geocode((Object *)obj);
 if(mode>=300&&m->action==208){online_box.value=(unsigned char)city_distance((Object *)obj);return &online_box;}
 if(mode>=300&&m->action==210)city_apply();
#endif
 switch(m->action){
 case 200:return &model;
 case 201:return &form_model;
 case 202:yes=mode!=204;break;
 case 203:yes=mode!=205;break;
 case 204:yes=((Object *)obj)->value;break;
 case 205:
  online_set_calls++;if(mode==210)slow();
  if(!args||!args[0]||*(unsigned char *)args[0]!=1){*exc=&exception;return NULL;}
  if(mode==206){*exc=&exception;return NULL;}
  if(mode!=207)((Object *)obj)->value=1;return NULL;
 case 206:
  if(mode==219||mode==220||mode==221)return (Object *)(mode==220&&phase==2?&changed_geo:&geo_string);
  return NULL;
 case 207:return NULL; /* permitted absent region code */
 case 208:yes=location_changed;break;
 case 209:
  online_refresh_calls++;
  if(!args||args[0]!=&form_model){*exc=&exception;return NULL;}
  if(mode==212){*exc=&exception;return NULL;}
  if(mode==213)form_model.value=0;
  if(mode==214)location_changed=1;
  return NULL;
 case 210:
  online_apply_calls++;
  if(mode==208){*exc=&exception;return NULL;}
  if(mode!=209)model.value=form_model.value;
  if(mode==215)location_changed=1;
  phase=2;return NULL;
 }
 online_box.value=(unsigned char)yes;return &online_box;
}
#ifdef CITY_FIXTURE
static Field *city_field(Class *,const char *);
static Object *city_field_object(Object *,Field *);
static int city_string_length(void *);
static uint16_t *city_string_chars(void *);
#endif
API Field *il2cpp_class_get_field_from_name(Class *c,const char *name){
#ifdef CITY_FIXTURE
 Field *extra=city_field(c,name);if(extra)return extra;
#endif

 if(c==&nc[4]&&!strcmp(name,"m_SearchCM"))return &cm_field;
 if(c==&nc[5]&&!strcmp(name,"m_PeopleFilterViewController"))return &people_field;return NULL;
}
API Class *il2cpp_field_get_parent(Field *f){return f->parent;}
API Type *il2cpp_field_get_type(Field *f){return f->type;}
API int il2cpp_field_get_flags(Field *f){return f->slot==6?(16|64):0;}
API void il2cpp_field_get_value(Object *obj,Field *f,Object **out){
 (void)obj;field_reads++;
#ifdef CITY_FIXTURE
 if(f->slot>=3){*out=city_field_object(obj,f);return;}
#endif

 if(f->slot==1){*out=mode==211&&phase==2?&changed_cm:&cm;return;}
 *out=mode==217?&other:&people;
}
API int il2cpp_string_length(void *s){
#ifdef CITY_FIXTURE
 if(mode>=300)return city_string_length(s);
#endif
return mode==221?129:((LocationString *)s)->length;}
API uint16_t *il2cpp_string_chars(void *s){
#ifdef CITY_FIXTURE
 if(mode>=300)return city_string_chars(s);
#endif
return ((LocationString *)s)->chars;}
API int fixture_online_sets(void){return online_set_calls;}
API int fixture_online_refreshes(void){return online_refresh_calls;}
API int fixture_online_applies(void){return online_apply_calls;}
