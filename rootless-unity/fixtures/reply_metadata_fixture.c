/* Owned type inventory; canaries prove no message values are read or sent. */
#define il2cpp_class_from_name base_class_from_name
#define il2cpp_class_get_parent base_class_get_parent
#include "chat_metadata_fixture.c"
#undef il2cpp_class_from_name
#undef il2cpp_class_get_parent
static Class reply_message={"DV.Messages","Message",3,-1};
static Class reply_text={"DV.Messages","TextMessage",3,-1};
API Class *il2cpp_class_from_name(Image *im,const char *ns,const char *name){
 if(im==&images[3]&&!strcmp(ns,"DV.Messages")){
  if(!strcmp(name,"Message"))return &reply_message;
  if(!strcmp(name,"TextMessage"))return &reply_text;
 }
 return base_class_from_name(im,ns,name);
}
API Class *il2cpp_class_get_parent(Class *k){return k==&reply_text?&reply_message:base_class_get_parent(k);}
API size_t il2cpp_image_get_class_count(Image *im){return mode==99?16385:im==&images[3]?2:0;}
API Class *il2cpp_image_get_class(Image *im,size_t index){if(im!=&images[3])return NULL;return index==0?&reply_message:index==1?&reply_text:NULL;}
API int il2cpp_class_is_assignable_from(Class *parent,Class *child){return parent==child||(parent==&reply_message&&child==&reply_text);}
