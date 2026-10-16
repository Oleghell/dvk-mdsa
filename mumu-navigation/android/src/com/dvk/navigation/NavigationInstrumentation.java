package com.dvk.navigation;
import android.app.Instrumentation;
import android.app.UiAutomation;
import android.graphics.Bitmap;
import android.graphics.Rect;
import android.os.Bundle;
import android.os.SystemClock;
import android.util.Base64;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import org.json.JSONArray;
import org.json.JSONObject;

/** Supervised navigation and ten approved empty-field greetings. No editor actions or send loop.
 * A tap CAN activate a button. Caller must inspect the fresh image before use.
 */
public final class NavigationInstrumentation extends Instrumentation {
 private static final String[] GREETINGS={"Привет","Привет)","Привет))","Привет!","Привет 🙂","Привет 😊","Привет 👋","Привет! 🙂","Приветик)","Привет-привет)"};
 private static final String BUTTON_SHA="87ce3d79d4bff8f6f05f3450f1a41ccbd29719d9eb893a376a1a529135cb410e";
 private String op,expected; private int x,y; private String stage="initialization";
 @Override public void onCreate(Bundle args){
  super.onCreate(args);
  op=args==null?"":args.getString("op","");
  expected=args==null?"":args.getString("expected_content_sha256","");
  try{x=Integer.parseInt(args.getString("x","0"));y=Integer.parseInt(args.getString("y","0"));}catch(Exception e){done("denied_arguments");return;}
  if(!"inspect".equals(op) && !"tap".equals(op) && !"back".equals(op) && !"profile_chat".equals(op) && !"profile_back".equals(op) && !"greeting".equals(op) && !"finish_input".equals(op)){done("denied_operation");return;}
  if(!"inspect".equals(op) && !expected.matches("[0-9a-f]{64}")){done("denied_arguments");return;}
  if((("greeting".equals(op) || "finish_input".equals(op)) && (x<0 || x>=10 || y!=0)) || ("tap".equals(op) && (x<0 || x>=900 || y<48 || y>=1536)) || ("profile_chat".equals(op) && (x!=321 || y!=1515)) || (("inspect".equals(op) || "back".equals(op) || "profile_back".equals(op)) && (x!=0 || y!=0))){done("denied_coordinates");return;}
  start();
 }
 private void done(String status){Bundle b=new Bundle();b.putString("navigation_status",status);finish(0,b);}
 private static AccessibilityNodeInfo root(UiAutomation a) throws Exception {
  AccessibilityNodeInfo n=null;
  for(int i=0;i<10 && n==null;i++){n=a.getRootInActiveWindow();if(n==null)SystemClock.sleep(200);}
  if(n==null || n.getPackageName()==null || !"drug.vokrug".contentEquals(n.getPackageName()))throw new Exception();
  return n;
 }
 private static String hash(UiAutomation a) throws Exception {return hash(a,false);}
 private static String digest(byte[] data) throws Exception {
  StringBuilder s=new StringBuilder();for(byte v:MessageDigest.getInstance("SHA-256").digest(data))s.append(String.format(java.util.Locale.ROOT,"%02x",v&255));return s.toString();
 }
 private static String hash(UiAutomation a,boolean profile) throws Exception {
  Bitmap b=a.takeScreenshot();if(b==null)throw new Exception();
  try{
   if(b.getWidth()!=900 || b.getHeight()!=1600)throw new Exception();
   if(profile){
    int[] button=new int[64*64];b.getPixels(button,0,64,290,1484,64,64);byte[] data=new byte[button.length*3];int index=0;
    for(int c:button){data[index++]=(byte)(c>>>16);data[index++]=(byte)(c>>>8);data[index++]=(byte)c;}
    if(!BUTTON_SHA.equals(digest(data)))throw new Exception("button mismatch");
   }
   int[] colors=new int[900*1552];b.getPixels(colors,0,900,0,48,900,1552);
   byte[] rgb=new byte[colors.length*3];int k=0;
   for(int i=0;i<colors.length;i++){int c=colors[i];int px=i%900,py=i/900+48;
    if(profile && px>=720 && px<900 && py>=810 && py<1032)c=0;
    rgb[k++]=(byte)(c>>>16);rgb[k++]=(byte)(c>>>8);rgb[k++]=(byte)c;}
   byte[] digest=MessageDigest.getInstance("SHA-256").digest(rgb);StringBuilder s=new StringBuilder();
   for(byte v:digest)s.append(String.format(java.util.Locale.ROOT,"%02x",v&255));return s.toString();
  }finally{b.recycle();}
 }
 private static String label(CharSequence v){if(v==null)return "";String s=v.toString();return s.length()>400?s.substring(0,400):s;}
 private void inspect(UiAutomation a) throws Exception {
  ArrayList<AccessibilityNodeInfo> pending=new ArrayList<>();pending.add(root(a));JSONArray out=new JSONArray();boolean truncated=false;
  for(int i=0;i<pending.size();i++){
   if(i>=1000){truncated=true;break;}AccessibilityNodeInfo n=pending.get(i);
   if(n.isVisibleToUser()){
    JSONObject o=new JSONObject();Rect r=new Rect();n.getBoundsInScreen(r);
    o.put("bounds",new JSONArray(new int[]{r.left,r.top,r.right,r.bottom}));o.put("class",label(n.getClassName()));
    o.put("resource_id",n.getViewIdResourceName());o.put("text",n.isPassword()?"":label(n.getText()));
    o.put("description",n.isPassword()?"":label(n.getContentDescription()));o.put("clickable",n.isClickable());
    o.put("editable",n.isEditable());o.put("focused",n.isFocused());o.put("enabled",n.isEnabled());o.put("checked",n.isChecked());o.put("checkable",n.isCheckable());
    out.put(o);if(out.length()>=200){truncated=true;break;}
   }
   for(int j=0;j<n.getChildCount();j++){if(pending.size()>=1000){truncated=true;break;}AccessibilityNodeInfo c=n.getChild(j);if(c!=null)pending.add(c);}
  }
  JSONObject report=new JSONObject();report.put("nodes",out);report.put("truncated",truncated);report.put("content_sha256",hash(a));
  report.put("semantic_identity_verified",false);
  Bundle b=new Bundle();b.putString("navigation_status","inspection_ok");b.putString("layout_b64",Base64.encodeToString(report.toString().getBytes(StandardCharsets.UTF_8),Base64.NO_WRAP));finish(0,b);
 }

 private static AccessibilityNodeInfo emptyField(UiAutomation a,boolean requireEmpty) throws Exception {
  ArrayList<AccessibilityNodeInfo> list=new ArrayList<>();list.add(root(a));AccessibilityNodeInfo edit=null;int count=0;
  for(int i=0;i<list.size();i++){
   if(list.size()>1000)throw new Exception("too many nodes");AccessibilityNodeInfo n=list.get(i);
   if(n.isVisibleToUser() && n.isEditable()){edit=n;count++;}
   for(int j=0;j<n.getChildCount();j++){AccessibilityNodeInfo c=n.getChild(j);if(c!=null)list.add(c);}
  }
  if(count!=1 || edit==null || !edit.isEnabled() || edit.isPassword() || edit.getPackageName()==null || !"drug.vokrug".contentEquals(edit.getPackageName()))throw new Exception("field");
  Rect bounds=new Rect();edit.getBoundsInScreen(bounds);
  if(!bounds.equals(new Rect(152,1488,748,1544)))throw new Exception("unsupported field bounds");
  if(requireEmpty && !edit.isShowingHintText() && edit.getText()!=null && edit.getText().length()!=0)return null;
  return edit;
 }
 private static String conversationHash(UiAutomation a) throws Exception {
  Bitmap b=a.takeScreenshot();if(b==null)throw new Exception();
  try{
   if(b.getWidth()!=900 || b.getHeight()!=1600)throw new Exception();
   int[] colors=new int[900*1412];b.getPixels(colors,0,900,0,48,900,1412);byte[] rgb=new byte[colors.length*3];int k=0;
   for(int c:colors){rgb[k++]=(byte)(c>>>16);rgb[k++]=(byte)(c>>>8);rgb[k++]=(byte)c;}
   return digest(rgb);
  }finally{b.recycle();}
 }

 private static String inputHash(UiAutomation a) throws Exception {
  Bitmap b=a.takeScreenshot();if(b==null)throw new Exception();
  try{
   if(b.getWidth()!=900 || b.getHeight()!=1600)throw new Exception();
   int[] colors=new int[900*1552];b.getPixels(colors,0,900,0,48,900,1552);byte[] rgb=new byte[colors.length*3];int k=0;
   for(int i=0;i<colors.length;i++){int c=colors[i],px=i%900,py=i/900+48;
    if(px>=152 && px<748 && py>=1488 && py<1544)c=0;
    rgb[k++]=(byte)(c>>>16);rgb[k++]=(byte)(c>>>8);rgb[k++]=(byte)c;}
   return digest(rgb);
  }finally{b.recycle();}
 }
 private void finishInput(UiAutomation a){boolean attempted=false;
  try{
   if(!expected.equals(inputHash(a))){done("denied_screen_changed");return;}
   AccessibilityNodeInfo edit=emptyField(a,false);
   if(edit.getText()==null || !GREETINGS[x].contentEquals(edit.getText())){done("denied_text");return;}
   if(!expected.equals(inputHash(a))){done("denied_screen_changed");return;}
   edit=emptyField(a,false);
   if(edit.getText()==null || !GREETINGS[x].contentEquals(edit.getText())){done("denied_text");return;}
   attempted=true;
   done(a.performGlobalAction(android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_BACK)?"input_injected":"indeterminate_after_attempt");
  }catch(Exception e){done(attempted?"indeterminate_after_attempt":"denied_field");}
 }
 private void greeting(UiAutomation a){boolean attempted=false;
  try{
   if(!expected.equals(inputHash(a))){done("denied_screen_changed");return;}
   AccessibilityNodeInfo edit=emptyField(a,true);if(edit==null){done("denied_nonempty_draft");return;}
   String context=conversationHash(a);
   if(!expected.equals(inputHash(a))){done("denied_screen_changed");return;}
   edit=emptyField(a,true);if(edit==null){done("denied_nonempty_draft");return;}
   Bundle value=new Bundle();value.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,GREETINGS[x]);
   attempted=true;
   if(!edit.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,value)){done("indeterminate_after_attempt");return;}
   SystemClock.sleep(250);edit=emptyField(a,false);
   if(context.equals(conversationHash(a)) && edit.getText()!=null && GREETINGS[x].contentEquals(edit.getText()))done("greeting_draft_verified");
   else done("indeterminate_after_attempt");
  }catch(Exception e){done(attempted?"indeterminate_after_attempt":"denied_field");}
 }
 @Override public void onStart(){boolean attempted=false;
  try{
   UiAutomation a=getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES);stage="foreground_root";root(a);
   if("inspect".equals(op)){stage="inspect_layout";inspect(a);return;}
   if("greeting".equals(op)){greeting(a);return;}
   if("finish_input".equals(op)){finishInput(a);return;}
   stage="screen_guard";
   if(!expected.equals(hash(a,"profile_chat".equals(op) || "profile_back".equals(op)))){done("denied_screen_changed");return;}
   root(a);if(!expected.equals(hash(a,"profile_chat".equals(op) || "profile_back".equals(op)))){done("denied_screen_changed");return;}
   stage="input_event";attempted=true;boolean first,second;
   if("tap".equals(op) || "profile_chat".equals(op)){
    long now=SystemClock.uptimeMillis();MotionEvent down=MotionEvent.obtain(now,now,MotionEvent.ACTION_DOWN,x,y,0);down.setSource(InputDevice.SOURCE_TOUCHSCREEN);
    MotionEvent up=MotionEvent.obtain(now,now+60,MotionEvent.ACTION_UP,x,y,0);up.setSource(InputDevice.SOURCE_TOUCHSCREEN);
    try{first=a.injectInputEvent(down,true);second=a.injectInputEvent(up,true);}finally{down.recycle();up.recycle();}
   }else{
    first=a.performGlobalAction(android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_BACK);
    second=first;
   }
   done(first && second?"input_injected":"indeterminate_after_attempt");
  }catch(Exception e){Bundle b=new Bundle();b.putString("navigation_status",attempted?"indeterminate_after_attempt":"denied_context_or_layout");b.putString("failure_stage",stage);b.putString("failure_type",e.getClass().getSimpleName());finish(0,b);}
 }
}
