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
static Type manager_type={18,&manager_class},long_type={10},text_type={14,&greeting_string_class};
static Object manager_object={&manager_class,0},long_object={NULL,0};
static int64_t long_value;
typedef struct Text {Object header;int length;uint16_t chars[16];} Text;
static Text text_a={{&greeting_string_class,0},5,{'H','e','l','l','o'}},text_b={{&greeting_string_class,0},5,{'R','e','p','l','y'}};
static Object outgoing={&text_class,0},incoming={&text_class,0};
static int body_reads,items;
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
 {"get_Item",&cc[5],0,&ctmessage,109,1,&tint}};
API Class *il2cpp_class_from_name(Image *im,const char *ns,const char *name){
 if(im==&chat_image&&!strcmp(ns,"DV.Messages")){if(!strcmp(name,"MessagesManager"))return &manager_class;if(!strcmp(name,"TextMessage"))return &text_class;}
 return old_class_from_name(im,ns,name);
}
API Image *il2cpp_class_get_image(Class *k){if(k==&manager_class||k==&text_class)return &chat_image;return old_image(k);}
API Class *il2cpp_class_get_parent(Class *k){if(k==&text_class)return &cc[2];return old_parent(k);}
API unsigned char il2cpp_class_is_assignable_from(Class *a,Class *b){return (a==&cc[2]&&b==&text_class)||old_assignable(a,b);}
API Method *il2cpp_class_get_method_from_name(Class *c,const char *name,int arity){
 int i;for(i=0;i<10;i++)if(extra[i].arity==(unsigned)arity&&!strcmp(name,extra[i].name)&&
  (c==extra[i].klass||(i==9&&(c==&cc[3]||c==&cc[4]))||(i>=4&&i<=7&&c==&text_class))){
   if(mode==509&&i==8)return NULL;return &extra[i];}
 if(mode>=600&&c==&nc[5]&&arity==1&&!strcmp(name,greeting_send.name)){
  if(mode==605)return NULL;
 }
 Method *found=old_method(c,name,arity);
 if(mode==606&&found==&greeting_send)greeting_string_type.kind=8;
 return found;
}
API void *il2cpp_object_unbox(Object *o){if(o==&long_object)return &long_value;return old_unbox(o);}
API Object *il2cpp_string_new(const char *text){
 if(mode<600)return old_string_new(text);
 if(!text||strcmp(text,"\320\232\320\260\320\272 \320\264\320\265\320\273\320\260?)"))greeting_bad++;
 return mode==604?NULL:&greeting_string;
}
API int il2cpp_string_length(Text *s){return mode==504?2049:s->length;}
API const uint16_t *il2cpp_string_chars(Text *s){return s->chars;}
API Object *il2cpp_runtime_invoke(Method *m,void *obj,void **args,void **exc){
 int in=obj==&incoming;if(exc)*exc=NULL;
 if(mode>=600&&m->action==60){
  managed_calls++;if(TID()!=main_id)off_thread_calls++;greeting_sends++;
  if(obj!=&filters||!args||args[0]!=&greeting_string)greeting_bad++;
  if(mode==603)*exc=&exception;return NULL;
 }
 if(mode==602&&m->action==61){managed_calls++;if(TID()!=main_id)off_thread_calls++;boolbox.value=0;return &boolbox;}
 if(m->action==51){managed_calls++;if(TID()!=main_id)off_thread_calls++;integer_value=mode==507?0:2;return &integer_box;}
 if(m->action<100)return old_invoke(m,obj,args,exc);
 managed_calls++;if(TID()!=main_id)off_thread_calls++;
 switch(m->action){
 case 100:return &manager_object;
 case 101:long_value=mode==526?0:mode==527?-1:100;break;
 case 102:long_value=mode==528?0:mode==529?-1:mode==506&&sample_frames>1?201:200;break;
 case 103:long_value=mode==530?0:mode==531?-1:300;break;
 case 104:long_value=mode==520?0:mode==521?-1:in&&mode!=503?1002:1001;break;
 case 105:long_value=mode==522?0:mode==523?-1:in?(mode==501?999:200):100;break;
 case 106:long_value=mode==524?0:mode==525?-1:mode==502?301:300;break;
 case 107:boolbox.value=!in;return &boolbox;
 case 108:body_reads++;return (Object *)(in?&text_b:&text_a);
 case 109:items++;if(!args||!args[0]){*exc=&exception;return NULL;}return *(int *)args[0]?&incoming:&outgoing;
 }
 return &long_object;
}
API void fixture_tick(void){void *exc=NULL;il2cpp_runtime_invoke(&methods[3],&runtime,NULL,&exc);}
API int fixture_body_reads(void){return body_reads;}
API int fixture_item_reads(void){return items;}
