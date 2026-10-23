/* Synthetic owned objects only; no APKs, credentials or real messages. */
#define il2cpp_class_from_name old_class_from_name
#define il2cpp_class_get_method_from_name old_method
#define il2cpp_class_get_image old_image
#define il2cpp_class_get_parent old_parent
#define il2cpp_class_is_assignable_from old_assignable
#define il2cpp_object_unbox old_unbox
#define il2cpp_runtime_invoke old_invoke
#define fixture_tick old_tick
#define il2cpp_string_new old_string_new
#include "chat_state_fixture.c"
#undef il2cpp_string_new
#undef il2cpp_class_from_name
#undef il2cpp_class_get_method_from_name
#undef il2cpp_class_get_image
#undef il2cpp_class_get_parent
#undef il2cpp_class_is_assignable_from
#undef il2cpp_object_unbox
#undef il2cpp_runtime_invoke
#undef fixture_tick
static Class manager_class={"DV.Messages","MessagesManager"},text_class={"DV.Messages","TextMessage"};
static Type manager_type={18,&manager_class},long_type={10},text_type={14,&greeting_string_class},name_type={14,&greeting_string_class};
static Object manager_object={&manager_class,0},long_object={NULL,0};
static int64_t long_value;
typedef struct Text {Object header;int length;uint16_t chars[16];} Text;
static Text text_a={{&greeting_string_class,0},5,{'H','e','l','l','o'}},text_b={{&greeting_string_class,0},5,{'R','e','p','l','y'}};
static Object outgoing={&text_class,0},incoming={&text_class,0};
static int body_reads,items,name_reads,own_chat_reads;
static Object read_parents[31];
static Object batch_messages[18];
static Text display_name={{&greeting_string_class,0},4,{0x410,0x43d,0x43d,0x430}}, changed_name={{&greeting_string_class,0},4,{0x418,0x43d,0x43d,0x430}};
static Method extra[]={
 {"get_MessagesManager",&cc[1],0,&manager_type,100},
 {"get_CurrentUserId",&manager_class,0,&long_type,101},
 {"get_Id",&cc[0],0,&long_type,102},
 {"get_Id",&cc[1],0,&long_type,103},
 {"get_Id",&cc[2],0,&long_type,104},
 {"get_SenderId",&cc[2],0,&long_type,105},
 {"get_ChatId",&cc[2],0,&long_type,106},
 {"get_IsMine",&cc[2],0,&tbool,107},
 {"get_Text",&text_class,0,&text_type,108},
 {"get_Item",&cc[5],0,&ctmessage,109,1,&tint},
 {"get_Name",&cc[0],0,&name_type,110}};
API Class *il2cpp_class_from_name(Image *im,const char *ns,const char *name){
 if(im==&chat_image&&!strcmp(ns,"DV.Messages")){if(!strcmp(name,"MessagesManager"))return &manager_class;if(!strcmp(name,"TextMessage"))return &text_class;}
 return old_class_from_name(im,ns,name);
}
API Image *il2cpp_class_get_image(Class *k){if(k==&manager_class||k==&text_class)return &chat_image;return old_image(k);}
API Class *il2cpp_class_get_parent(Class *k){if(k==&text_class)return &cc[2];return old_parent(k);}
API unsigned char il2cpp_class_is_assignable_from(Class *a,Class *b){return (a==&cc[2]&&b==&text_class)||old_assignable(a,b);}
API Method *il2cpp_class_get_method_from_name(Class *c,const char *name,int arity){
 int i;for(i=0;i<11;i++)if(extra[i].arity==(unsigned)arity&&!strcmp(name,extra[i].name)&&
  (c==extra[i].klass||(i==9&&(c==&cc[3]||c==&cc[4]))||(i>=4&&i<=7&&c==&text_class))){
   if((mode==509&&i==8)||(mode==540&&i==10))return NULL;
   if(mode==541&&i==10)name_type.kind=8;return &extra[i];}
 if(mode>=600&&c==&nc[5]&&arity==1&&!strcmp(name,greeting_send.name)){
  if(mode==605)return NULL;
 }
 Method *found=old_method(c,name,arity);
 if(mode==606&&found==&greeting_send)greeting_string_type.kind=8;
 return found;
}
API void *il2cpp_object_unbox(Object *o){if(o==&long_object)return &long_value;return old_unbox(o);}
static int reply_variant;
static char expected_reply[1024];
API void fixture_expected_reply(const char *text){
 expected_reply[0]=0;
 if(text && strlen(text)<sizeof(expected_reply)){strcpy(expected_reply,text);}
}
API void fixture_reply_variant(int value){reply_variant=value>=0&&value<3?value:0;}
static const char *reply_texts[]={"\320\232\320\260\320\272\040\320\264\320\265\320\273\320\260\077\051",
 "\320\232\320\260\320\272\040\320\275\320\260\321\201\321\202\321\200\320\276\320\265\320\275\320\270\320\265\077\051",
 "\320\241\321\203\320\277\320\265\321\200\054\040\321\203\040\320\274\320\265\320\275\321\217\040\321\202\320\276\320\266\320\265\056\040\320\242\321\213\040\320\265\321\201\321\202\321\214\040\320\262\040\321\202\320\265\320\273\320\265\320\263\321\200\320\260\320\274\320\265\040\320\270\320\273\320\270\040\320\262\320\260\321\202\321\206\320\260\320\277\320\265\077\040\320\220\040\321\202\320\276\040\321\217\040\321\202\321\203\321\202\040\320\275\320\265\040\321\207\320\260\321\201\321\202\320\276\040\320\261\321\213\320\262\320\260\321\216\040\360\237\230\205"};
API Object *il2cpp_string_new(const char *text){
 if(mode<600)return old_string_new(text);
 if(!text||strcmp(text,expected_reply[0]?expected_reply:reply_texts[reply_variant]))greeting_bad++;
 return mode==604?NULL:&greeting_string;
}
API int il2cpp_string_length(Text *s){return mode==504?2049:s->length;}
API const uint16_t *il2cpp_string_chars(Text *s){return s->chars;}
API Object *il2cpp_runtime_invoke(Method *m,void *obj,void **args,void **exc){
 int batch_index=-1;
 for(int bi=0;bi<18;bi++)if(obj==&batch_messages[bi])batch_index=bi;
 int in=obj==&incoming||batch_index>0;if(exc)*exc=NULL;
 if(mode>=570&&mode<=574&&m->action==51){managed_calls++;if(TID()!=main_id)off_thread_calls++;integer_value=mode==572&&items<4?16:18;return &integer_box;}
 if(mode>=570&&mode<=574&&m->action==109){
  managed_calls++;if(TID()!=main_id)off_thread_calls++;items++;
  if(!args||!args[0]||*(int *)args[0]<0||*(int *)args[0]>=18){*exc=&exception;return NULL;}
  if(mode==571){
#ifdef _WIN32
   Sleep(8);
#else
   usleep(8000);
#endif
  }
  int index=*(int *)args[0];batch_messages[index].klass=&text_class;return &batch_messages[index];
 }
 if(mode>=600&&m->action==60){
  managed_calls++;if(TID()!=main_id)off_thread_calls++;greeting_sends++;
  if(obj!=&filters||!args||args[0]!=&greeting_string)greeting_bad++;
  if(mode==603)*exc=&exception;return NULL;
 }
 if(mode==602&&m->action==61){managed_calls++;if(TID()!=main_id)off_thread_calls++;boolbox.value=0;return &boolbox;}
 if(m->action==51){managed_calls++;if(TID()!=main_id)off_thread_calls++;integer_value=mode==507?0:mode==564?1:2;return &integer_box;}
 if((mode==550||mode==551)&&m->action==18){
  managed_calls++;if(TID()!=main_id)off_thread_calls++;
  int length=mode==550?24:31;
  for(int i=0;i<length;i++){read_parents[i].klass=&nc[0];read_parents[i].value=i;}
  if(obj==&view)return &read_parents[0];
  for(int i=0;i<length;i++)if(obj==&read_parents[i])return i+1<length?&read_parents[i+1]:&window;
 }
 if(m->action<100)return old_invoke(m,obj,args,exc);
 managed_calls++;if(TID()!=main_id)off_thread_calls++;
 switch(m->action){
 case 100:return &manager_object;
 case 101:long_value=mode==526?0:mode==527?-1:100;break;
 case 102:long_value=mode==528?0:mode==529?-1:((mode==506&&sample_frames>1)||(mode==573&&items>=4))?201:200;break;
 case 103:long_value=mode==530?0:mode==531?-1:300;break;
 case 104:long_value=batch_index>=0?1001+batch_index:mode==520?0:mode==521?-1:in&&mode!=503?1002:1001;break;
 case 105:long_value=mode==574&&batch_index==17?999:mode==522?0:mode==523?-1:in?(mode==501?999:200):100;break;
 case 106:
  if(!in)own_chat_reads++;
  long_value=mode==524||(!in&&mode==563)?0:mode==525||(in&&mode==562)?-1:
   !in&&(mode==560||mode==561||mode==564||mode==568||mode==650||mode==651)?-1:
   !in&&mode==565?(((own_chat_reads-1)/2)%2?-2:-1):
   !in&&mode==566?(own_chat_reads%2?-1:-2):
   !in&&mode==567?(-INT64_C(9223372036854775807)-1):
   mode==502||(in&&(mode==561||mode==651))?301:300;break;
 case 107:boolbox.value=!in;return &boolbox;
 case 108:body_reads++;return (Object *)(in?&text_b:&text_a);
 case 110:name_reads++;return (Object *)(mode==542&&name_reads%2==0?&changed_name:&display_name);
 case 109:items++;if(!args||!args[0]){*exc=&exception;return NULL;}if(mode==568)return *(int *)args[0]?&outgoing:&incoming;return *(int *)args[0]?&incoming:&outgoing;
 }
 return &long_object;
}
API void fixture_tick(void){void *exc=NULL;il2cpp_runtime_invoke(&methods[3],&runtime,NULL,&exc);}
API int fixture_body_reads(void){return body_reads;}
API int fixture_item_reads(void){return items;}

API int fixture_name_reads(void){return name_reads;}
