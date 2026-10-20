/* Own semantic-city test ABI. Contains no APK, account, location or messaging. */
#define CITY_FIXTURE
#include "search_online_fixture.c"
static Class cc[]={
 {"DV","CityFinderViewController"},{"DV","CityFinderCell"},{"DV.Models","GeoRecord"},
 {"DV","SearchField"},{"","GeoType"},{"UIKit","TableView"},{"UIKit","TableCell"},
 {"Core.Collections","CoreList`1"},{"DataKit","UIDataGridCell`1"}};
static Type ctcity={18,&cc[0]},ctcell={18,&cc[1]},ctrecord={18,&cc[2]},ctinput={18,&cc[3]},ctenum={17,&cc[4]},cttable={18,&cc[5]},cttablecell={18,&cc[6]},ctlist={21,&cc[7]};
static Method cmeth[]={
 {"ShowRegionPicker",&oc[0],0,&tvoid,300},
 {"get_Text",&cc[3],0,&otstring,301},
 {"set_Text",&cc[3],0,&tvoid,302,1,&otstring},
 {"get_QueryString",&cc[0],0,&otstring,303},
 {"OnSearch",&cc[0],0,&tvoid,304},
 {"OnCellSelected",&cc[0],0,&tvoid,305,2,&ctcell},
 {"get_GeoID",&cc[2],0,&otstring,306},
 {"get_Name",&cc[2],0,&otstring,307},
 {"get_RecordType",&cc[2],0,&ctenum,308},
 {"get_GeoRecordName",&oc[2],64,&otstring,309},
 {"set_ByDistance",&oc[2],64,&tvoid,310,1,&tbool},
 {"get_Item",&cc[8],0,&ctrecord,311},
 {"get_VisibleCells",&cc[5],0,&ctlist,312},
 {"get_Count",&cc[7],0,&tint,313},
 {"get_Item",&cc[7],0,&cttablecell,314,1,&tint},
 {"get_SectionsCount",&cc[5],0,&tint,315},
 {"GetSectionItemsCount",&cc[5],0,&tint,316,1,&tint},
 {"get_CanSelect",&cc[6],0,&tbool,317},
 {"get_NonSelectable",&cc[6],0,&tbool,318}};
static Object city_controller={&cc[0],0},city_input={&cc[3],0},city_table={&cc[5],0},city_list={&cc[7],0},city_cell={&cc[1],0},city_cell2={&cc[1],0},city_record={&cc[2],0},city_record2={&cc[2],0},city_int_box={NULL,0};
static Field input_field={&cc[0],&ctinput,3},table_field={&cc[0],&cttable,4},query_field={&cc[0],&otstring,5},enum_field={&cc[4],&ctenum,6};
typedef struct CityString {Class *klass;int length;uint16_t chars[128];} CityString;
static CityString wanted_string,old_id_string,new_id_string,other_id_string,old_name_string,other_name_string,similar_name_string,case_name_string;
static int query_sent,city_pick_calls,city_open_calls,city_text_calls,city_search_calls,form_has_city,model_has_city,form_distance,model_distance,city_integer,picked_second,city_name_reads;
static Object *input_text;
static void init_string(CityString *s,const char *text){int i;s->klass=NULL;s->length=(int)strlen(text);for(i=0;i<s->length;i++)s->chars[i]=(uint16_t)text[i];s->chars[s->length]=0;}
static void city_init(int m){
 query_sent=city_pick_calls=city_open_calls=city_text_calls=city_search_calls=form_has_city=model_has_city=0;
 form_distance=model_distance=1;input_text=NULL;picked_second=city_name_reads=0;
 init_string(&wanted_string,"Pskov");init_string(&old_id_string,"old-code");init_string(&new_id_string,"actual-returned-code");
 init_string(&other_id_string,"different-real-code");init_string(&old_name_string,"OldCity");init_string(&other_name_string,"NotPskov");
 init_string(&similar_name_string,"Pskovsk");init_string(&case_name_string,"PSKOV");
 if(m==301)cmeth[5].arity=1;
 if(m==302)cmeth[2].param=&tbool;
 if(m==303)table_field.type=&ctinput;
 if(m==319)form_distance=model_distance=0;
}
static Class *city_class(Image *im,const char *ns,const char *name){int i;for(i=0;i<9;i++){
 Image *expected=i<5?&images[3]:&images[0];
 if(im==expected&&!strcmp(ns,cc[i].ns)&&!strcmp(name,cc[i].name))return &cc[i];}return NULL;}
static Method *city_method(Class *c,const char *name,int arity){int i;for(i=0;i<19;i++)
 if((c==cmeth[i].klass||(c==&cc[1]&&i==11))&&arity==cmeth[i].arity&&!strcmp(name,cmeth[i].name))return &cmeth[i];return NULL;}
static int city_assignable(Class *a,Class *b){
 if(a==&nc[1]&&b==&cc[0])return 1;if(mode==325&&a==&nc[1]&&b==&oc[0])return 1;if(a==&nc[3]&&b==&cc[0])return 1;
 if(a==&nc[0]&&(b==&cc[1]||b==&cc[3]||b==&cc[5]||b==&cc[6]))return 1;
 if(b==&cc[1]&&(a==&cc[6]||a==&cc[8]))return 1;return a==b;}
static Object *city_active(void){return mode==325?&filters:&city_controller;}
static int city_hosted(void *obj){return mode==325&&phase==3&&obj==&people;}
static Object *city_hosted_item(void){return &city_controller;}
static Object *city_parent(Object *obj){return obj==&city_cell||obj==&city_cell2?&city_table:&window;}
static Object *city_geocode(Object *obj){return (Object *)((obj==&form_model?form_has_city:model_has_city)?(picked_second?&other_id_string:&new_id_string):&old_id_string);}
static int city_distance(Object *obj){return obj==&form_model?form_distance:model_distance;}
static void city_apply(void){model_has_city=mode==314?0:form_has_city;model_distance=form_distance;}
static Object *city_invoke(Method *m,void *obj,void **args,void **exc){
 int yes=0,index=0;
 if((m->action==314||m->action==316)&&args&&args[0])index=*(int *)args[0];
 switch(m->action){
 case 300:city_open_calls++;if(mode==304||mode==321){*exc=&exception;return NULL;}if(mode==305)phase=2;else phase=3;return NULL;
 case 301:return input_text;
 case 302:city_text_calls++;input_text=mode==306?(Object *)&other_name_string:(Object *)args[0];return NULL;
 case 303:return input_text;
 case 304:city_search_calls++;if(mode==307){*exc=&exception;return NULL;}query_sent=1;return NULL;
 case 305:
  city_pick_calls++;
  if(!args||args[0]!=(mode==327?&city_cell2:&city_cell)||args[1]!=(mode==327?&city_record2:&city_record)){*exc=&exception;return NULL;}
  picked_second=mode==327;
  if(mode==315||mode==323)slow();if(mode==316){*exc=&exception;return NULL;}
  form_has_city=mode!=313;phase=1;return NULL;
 case 306:return (Object *)(obj==&city_record2?&other_id_string:&new_id_string);
 case 307:
  city_name_reads++;
  if(mode==326||(mode==327&&obj==&city_record)||(mode==331&&city_name_reads>2))return (Object *)&similar_name_string;
  return (Object *)(mode==310?&other_name_string:mode==330?&case_name_string:&wanted_string);
 case 308:city_integer=mode==311?2:1;return &city_int_box;
 case 309:
  if((mode==328&&obj==&model&&model_has_city)||(mode==329&&obj==&form_model&&form_has_city))return (Object *)&similar_name_string;
  return (Object *)((obj==&form_model?form_has_city:model_has_city)?(mode==330?&case_name_string:&wanted_string):&old_name_string);
 case 310:if(!args||!args[0]||*(unsigned char *)args[0]!=0){*exc=&exception;return NULL;}if(mode!=318)form_distance=0;return NULL;
 case 311:return obj==&city_cell2?&city_record2:&city_record;
 case 312:return &city_list;
 case 313:city_integer=mode==308?0:mode==309||mode==327?2:1;return &city_int_box;
 case 314:if(mode==320)return &other;return index==0?&city_cell:&city_cell2;
 case 315:city_integer=1;return &city_int_box;
 case 316:city_integer=mode==308?0:mode==309||mode==312||mode==327?2:1;return &city_int_box;
 case 317:yes=mode!=317;break;
 case 318:yes=0;break;
 }
 online_box.value=(unsigned char)yes;return &online_box;
}
static Field *city_field(Class *c,const char *name){
 if(c==&cc[0]){if(!strcmp(name,"m_SearchField"))return &input_field;if(!strcmp(name,"m_TableView"))return &table_field;if(!strcmp(name,"m_LastSearchText"))return &query_field;}
 if(c==&cc[4]&&!strcmp(name,"CITY"))return &enum_field;return NULL;}
static Object *city_field_object(Object *obj,Field *f){(void)obj;
 if(f==&input_field)return &city_input;if(f==&table_field)return &city_table;
 if(f==&query_field)return query_sent?input_text:NULL;return NULL;}
static int city_string_length(void *s){return ((CityString *)s)->length;}
static uint16_t *city_string_chars(void *s){return ((CityString *)s)->chars;}
API Object *il2cpp_string_new(const char *text){if(strcmp(text,"Pskov"))return NULL;return (Object *)&wanted_string;}
API void il2cpp_field_static_get_value(Field *f,int *out){*out=f==&enum_field?1:-1;}
API Type *il2cpp_class_enum_basetype(Class *c){return c==&cc[4]?&tint:NULL;}
API int fixture_city_opens(void){return city_open_calls;}
API int fixture_city_searches(void){return city_search_calls;}
API int fixture_city_selects(void){return city_pick_calls;}
/* Distinguish the two-argument handler's second parameter through the real API. */

static Type *city_param(Method *m,unsigned int n){return m==&cmeth[5]&&n==1?&ctrecord:NULL;}
static void *city_unbox(Object *o){return o==&city_int_box?&city_integer:NULL;}
