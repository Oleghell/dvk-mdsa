package com.dvk.control;
import android.app.Instrumentation;
import android.app.UiAutomation;
import android.content.*;
import android.graphics.Bitmap;
import android.graphics.Rect;
import android.os.*;
import android.util.Base64;
import android.view.*;
import android.view.accessibility.AccessibilityNodeInfo;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.json.*;
public final class ControlInstrumentation extends Instrumentation {
 private JSONObject request;private UiAutomation auto;private boolean attempted;
 private String phase="startup";
 private static final class GuardFailure extends Exception {
  final String code;GuardFailure(String code){this.code=code;}
 }
 private static String reason(Exception e){return e instanceof GuardFailure?((GuardFailure)e).code:"internal_error";}
 private void denied(String state,Exception e){Bundle b=new Bundle();b.putString("control_status",state);b.putString("control_diagnostic_code",reason(e));b.putString("control_diagnostic_phase",phase);finish(0,b);}
 private void awaitAccessibility() throws Exception{
  final Exception[] last=new Exception[1];
  int state=ControlPolicy.awaitRoot(new ControlPolicy.RootProbe(){
   public int state(){try{root();return 1;}catch(Exception e){last[0]=e;String code=reason(e);return "root_not_ready".equals(code) || "node_not_ready".equals(code)?0:-1;}}
   public void pause(){SystemClock.sleep(50);}
  });
  if(state!=1){if(last[0]!=null)throw last[0];throw new GuardFailure("root_not_ready");}
 }
 private void done(String state,JSONObject data){Bundle b=new Bundle();b.putString("control_status",state);if(data!=null)b.putString("report_b64",Base64.encodeToString(data.toString().getBytes(StandardCharsets.UTF_8),Base64.NO_WRAP));finish(0,b);}
 @Override public void onCreate(Bundle args){super.onCreate(args);try{String raw=args.getString("request_b64","");if(raw.length()>24000)throw new Exception();request=new JSONObject(new String(Base64.decode(raw,Base64.NO_WRAP),StandardCharsets.UTF_8));start();}catch(Exception e){done("denied_arguments",null);}}
 private AccessibilityNodeInfo root() throws Exception{
  AccessibilityNodeInfo n=auto.getRootInActiveWindow();
  if(n==null)throw new GuardFailure("root_not_ready");
  if(n.getPackageName()==null || !"drug.vokrug".contentEquals(n.getPackageName()))throw new GuardFailure("wrong_package");
  if(!n.refresh())throw new GuardFailure("node_not_ready");
  if(n.getPackageName()==null || !"drug.vokrug".contentEquals(n.getPackageName()))throw new GuardFailure("wrong_package");return n;
 }
 private AccessibilityNodeInfo field() throws Exception{
  ArrayList<AccessibilityNodeInfo> q=new ArrayList<>();q.add(root());AccessibilityNodeInfo found=null;
  for(int i=0;i<q.size();i++){
   if(q.size()>1000)throw new Exception();AccessibilityNodeInfo n=q.get(i);
   if(n.isVisibleToUser() && n.isEditable() && n.isFocused()){
    if(found!=null || !n.refresh() || !n.isEnabled() || n.isPassword() || n.getPackageName()==null || !"drug.vokrug".contentEquals(n.getPackageName()))throw new Exception();found=n;
   }
   for(int j=0;j<n.getChildCount();j++){AccessibilityNodeInfo c=n.getChild(j);if(c!=null)q.add(c);}
  }
  if(found==null)throw new Exception();Rect b=new Rect();found.getBoundsInScreen(b);if(!ControlPolicy.point(b.left,b.top) || b.right>900 || b.bottom>1600 || b.width()<1 || b.height()<1)throw new Exception();return found;
 }
 private Rect gestureEditor(JSONObject guard) throws Exception{
  if(guard.length()!=2 || !guard.has("bounds") || !guard.has("expected_text"))throw new GuardFailure("invalid_editor_guard");
  AccessibilityNodeInfo n=field();Rect actual=new Rect();n.getBoundsInScreen(actual);
  JSONArray b=guard.getJSONArray("bounds");Object text=guard.get("expected_text");
  if(b.length()!=4 || !(text instanceof String) || ((String)text).length()>4096)throw new GuardFailure("invalid_editor_guard");
  int[] expected=new int[4];for(int i=0;i<4;i++){Object v=b.get(i);if(!(v instanceof Integer))throw new GuardFailure("invalid_editor_guard");expected[i]=(Integer)v;}
  Rect requested=new Rect(expected[0],expected[1],expected[2],expected[3]);
  if(!actual.equals(requested) || actual.width()>800 || actual.height()>160 || !text.equals(value(n)))throw new GuardFailure("editor_changed");
  return actual;
 }
 private String value(AccessibilityNodeInfo n){return n.isShowingHintText() || n.getText()==null?"":n.getText().toString();}
 private static final class ScreenSnapshot {
  final int[] pixels;final String sha;
  ScreenSnapshot(int[] pixels,String sha){this.pixels=pixels;this.sha=sha;}
 }
 private ScreenSnapshot snapshot(Rect mask) throws Exception{
  root();Bitmap b=auto.takeScreenshot();if(b==null)throw new GuardFailure("screenshot_unavailable");
  try{if(b.getWidth()!=900 || b.getHeight()!=1600)throw new GuardFailure("screen_dimensions");int[] px=new int[900*1552];b.getPixels(px,0,900,0,48,900,1552);byte[] rgb=new byte[px.length*3];int k=0;
   for(int i=0;i<px.length;i++){int x=i%900,y=i/900+48,c=mask!=null && mask.contains(x,y)?0:px[i]&0xffffff;px[i]=c;rgb[k++]=(byte)(c>>>16);rgb[k++]=(byte)(c>>>8);rgb[k++]=(byte)c;}
   StringBuilder out=new StringBuilder();for(byte v:MessageDigest.getInstance("SHA-256").digest(rgb))out.append(String.format(java.util.Locale.ROOT,"%02x",v&255));return new ScreenSnapshot(px,out.toString());
  }finally{b.recycle();}
 }
 private String hash(Rect mask) throws Exception{return snapshot(mask).sha;}
 private JSONObject mismatchReport(int check,ScreenSnapshot previous,ScreenSnapshot current) throws Exception{
  JSONObject report=new JSONObject();report.put("guard_check",check);report.put("masked_context_match",false);
  // Only counts and bounds, NEVER pixel data or app text leave the helper.
  if(previous!=null){int changed=0,left=900,top=1600,right=0,bottom=48;
   for(int i=0;i<current.pixels.length;i++)if(previous.pixels[i]!=current.pixels[i]){int x=i%900,y=i/900+48;changed++;left=Math.min(left,x);top=Math.min(top,y);right=Math.max(right,x+1);bottom=Math.max(bottom,y+1);}
   report.put("diff_pixels",changed);if(changed>0)report.put("diff_bounds",new JSONArray(new int[]{left,top,right,bottom}));
  }
  return report;
 }
 private void motion(int x,int y,int x2,int y2,int ms) throws Exception{
  long now=SystemClock.uptimeMillis();sendMotion(now,now,MotionEvent.ACTION_DOWN,x,y);
  try{int steps=ms==0?0:Math.max(1,ms/40);for(int i=1;i<=steps;i++){SystemClock.sleep(ms/steps);sendMotion(now,SystemClock.uptimeMillis(),MotionEvent.ACTION_MOVE,x+(x2-x)*i/steps,y+(y2-y)*i/steps);}}
  finally{sendMotion(now,SystemClock.uptimeMillis()+1,MotionEvent.ACTION_UP,x2,y2);}
 }
 private void sendMotion(long down,long now,int action,int x,int y) throws Exception{MotionEvent e=MotionEvent.obtain(down,now,action,x,y,0);e.setSource(InputDevice.SOURCE_TOUCHSCREEN);try{if(!auto.injectInputEvent(e,true))throw new Exception();}finally{e.recycle();}}
 private Bundle ime(String op,String expected,String text,int delay,long generation) throws Exception{
  Intent intent=new Intent();intent.setComponent(new ComponentName("com.dvk.keyboard.v2","com.dvk.keyboard.ImeCommandReceiver"));intent.putExtra("op",op);intent.putExtra("expected_text",expected);intent.putExtra("text",text);intent.putExtra("delay_ms",delay);intent.putExtra("generation",generation);
  CountDownLatch latch=new CountDownLatch(1);Bundle[] answer={null};
  getTargetContext().sendOrderedBroadcast(intent,"com.dvk.keyboard.v2.CONTROL",new BroadcastReceiver(){public void onReceive(Context c,Intent i){Bundle b=getResultExtras(false);if(b!=null)answer[0]=b;latch.countDown();}},new Handler(Looper.getMainLooper()),0,null,null);
  if(!latch.await(5,TimeUnit.SECONDS) || answer[0]==null)throw new Exception();return answer[0];
 }
 @Override public void onStart(){
  try{
   auto=getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES);phase="startup_root";awaitAccessibility();phase="arguments";String op=request.getString("op");
   if("inspect".equals(op)){
    phase="inspect_screen";JSONObject d=new JSONObject();d.put("content_sha256",hash(null));d.put("gesture_editor_guard_supported",true);
    phase="inspect_field";try{AccessibilityNodeInfo n=field();Rect r=new Rect();n.getBoundsInScreen(r);d.put("bounds",new JSONArray(new int[]{r.left,r.top,r.right,r.bottom}));d.put("text",value(n));d.put("field_context_sha256",hash(r));d.put("focused",true);}catch(Exception e){d.put("focused",false);}
    done("inspection_ok",d);return;
   }
   String expected=request.getString("expected_sha256");if(!expected.matches("[0-9a-f]{64}")){done("denied_arguments",null);return;}
   if("clear".equals(op) || "type".equals(op)){
    phase="validate_field";AccessibilityNodeInfo n=field();Rect r=new Rect();n.getBoundsInScreen(r);JSONArray bounds=request.getJSONArray("bounds");
    if(bounds.length()!=4 || r.left!=bounds.getInt(0) || r.top!=bounds.getInt(1) || r.right!=bounds.getInt(2) || r.bottom!=bounds.getInt(3)){done("denied_field",null);return;}
    String old=request.getString("expected_text"),text=request.getString("text");int delay=request.getInt("delay_ms");
    if(old.length()>4096 || !ControlPolicy.plain(text) || delay<20 || delay>500 || "clear".equals(op) && !"".equals(text) || "type".equals(op) && !old.isEmpty()){done("denied_arguments",null);return;}
    if(!old.equals(value(n)) || !expected.equals(hash(r))){done("denied_screen_changed",null);return;}
    n=field();Rect again=new Rect();n.getBoundsInScreen(again);if(!again.equals(r) || !old.equals(value(n)) || !expected.equals(hash(r))){done("denied_screen_changed",null);return;}
    phase="ime_input";long generation=-1;String prefix=old;long deadline=SystemClock.uptimeMillis()+70000;
    if("clear".equals(op)){
     attempted=true;Bundle answer=ime(op,old,"",delay,-1);String status=answer.getString("control_status","indeterminate_after_attempt");if("denied_ime".equals(status))attempted=false;done(status,null);return;
    }
    for(int p=0;p<text.length();){
     if(SystemClock.uptimeMillis()>deadline)throw new Exception();
     AccessibilityNodeInfo current=field();Rect currentBounds=new Rect();current.getBoundsInScreen(currentBounds);if(!r.equals(currentBounds) || !prefix.equals(value(current)))throw new Exception();
     int cp=text.codePointAt(p);String letter=new String(Character.toChars(cp));
     boolean earlier=attempted;attempted=true;Bundle answer=ime("type",prefix,letter,delay,generation);String status=answer.getString("control_status","indeterminate_after_attempt");
     if(!"text_verified".equals(status)){if(!earlier && "denied_ime".equals(status)){attempted=false;done("denied_ime",null);return;}throw new Exception();}
     generation=answer.getLong("generation",-1);if(generation<0)throw new Exception();prefix+=letter;p+=Character.charCount(cp);
    }
    done("text_verified",null);return;
   }
   int x=request.getInt("x"),y=request.getInt("y"),x2=request.getInt("x2"),y2=request.getInt("y2"),ms=request.getInt("duration_ms"),key=request.getInt("keycode");
   boolean valid=("tap".equals(op) && ControlPolicy.point(x,y) && ms==0 || "hold".equals(op) && ControlPolicy.point(x,y) && ms>=300 && ms<=2000 || "swipe".equals(op) && ControlPolicy.point(x,y) && ControlPolicy.point(x2,y2) && ms>=100 && ms<=2000 || "key".equals(op) && ControlPolicy.key(key));
   if(!valid){done("denied_arguments",null);return;}phase="gesture_guard";
   if(request.has("editor_guard")){
    if("key".equals(op)){done("denied_arguments",null);return;}
    JSONObject guard=request.getJSONObject("editor_guard");
    // Re-read exact native field before BOTH image checks. Only the native
    // focused editor rectangle is normalized; caller cannot mask arbitrary UI.
    ScreenSnapshot previous=null;
    for(int check=0;check<2;check++){
     Rect mask=gestureEditor(guard);
     ScreenSnapshot current=snapshot(mask);
     if(!expected.equals(current.sha)){done("denied_screen_changed",mismatchReport(check,previous,current));return;}
     previous=current;
     gestureEditor(guard);
    }
   }else if(!expected.equals(hash(null)) || !expected.equals(hash(null))){done("denied_screen_changed",null);return;}
   phase="gesture_inject";attempted=true;
   if("key".equals(op)){if(key==4){if(!auto.performGlobalAction(android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_BACK))throw new Exception();}else{long now=SystemClock.uptimeMillis();if(!auto.injectInputEvent(new KeyEvent(now,now,KeyEvent.ACTION_DOWN,key,0),true) || !auto.injectInputEvent(new KeyEvent(now,now+40,KeyEvent.ACTION_UP,key,0),true))throw new Exception();}}
   else motion(x,y,"swipe".equals(op)?x2:x,"swipe".equals(op)?y2:y,ms);
   done("input_injected",null);
  }catch(Exception e){denied(attempted?"indeterminate_after_attempt":"denied_context",e);}
 }
}
