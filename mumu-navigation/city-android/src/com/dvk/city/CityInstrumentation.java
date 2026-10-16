package com.dvk.city;
import android.app.Instrumentation;
import android.app.UiAutomation;
import android.graphics.Bitmap;
import android.graphics.Rect;
import android.os.Bundle;
import android.os.SystemClock;
import android.util.Base64;
import android.view.accessibility.AccessibilityNodeInfo;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import org.json.JSONObject;

/** Isolated CITY SEARCH editor only. No tap, Back, key events, chat or send API.
 * This is NOT a city-result chooser or filter applier. One ACTION_SET_TEXT only.
 */
public final class CityInstrumentation extends Instrumentation {
 private String op,expected; private int index,previousEncoded;
 private String phase="startup";
 private static final class GuardFailure extends Exception {
  final String code; final Rect actual;
  GuardFailure(String code){this(code,null);}
  GuardFailure(String code,Rect actual){this.code=code;this.actual=actual==null?null:new Rect(actual);}
 }
 private static String reason(Exception e){return e instanceof GuardFailure?((GuardFailure)e).code:"internal_error";}
 private void denied(String status,String code){denied(status,code,null);}
 private void denied(String status,String code,Rect actual){
  Bundle out=new Bundle();out.putString("navigation_status",status);out.putString("city_diagnostic_code",code);
  out.putString("city_diagnostic_phase",phase);
  if(actual!=null)out.putString("actual_editor_bounds",actual.left+","+actual.top+","+actual.right+","+actual.bottom);
  finish(0,out);
 }
 private void deniedFailure(String status,Exception e){denied(status,reason(e),e instanceof GuardFailure?((GuardFailure)e).actual:null);}
 private static void awaitAccessibility(final UiAutomation a) throws Exception{
  final Exception[] last=new Exception[1];
  int state=CityPolicy.awaitRoot(new CityPolicy.RootProbe(){
   public int state(){
    try{field(a);return 1;}
    catch(Exception e){
     last[0]=e;String code=reason(e);
     // Startup reads ONLY; never repeat guards or actions after dispatch.
     return "root_not_ready".equals(code) || "node_not_ready".equals(code) || "editor_bounds".equals(code)?0:-1;
    }
   }
   public void pause(){SystemClock.sleep(50);}
  });
  if(state!=1){if(last[0]!=null)throw last[0];throw new GuardFailure("root_not_ready");}
 }
 @Override public void onCreate(Bundle args){
  super.onCreate(args);
  try{
   if(args==null || args.size()!=4){done("denied_arguments");return;}
   op=args.getString("op","");expected=args.getString("expected_content_sha256","");
   index=Integer.parseInt(args.getString("x",""));previousEncoded=Integer.parseInt(args.getString("y",""));
   if(!CityPolicy.validArgs(op,expected,index,previousEncoded)){done("denied_arguments");return;}
  }catch(Exception e){done("denied_arguments");return;}
  start();
 }
 private void done(String status){Bundle out=new Bundle();out.putString("navigation_status",status);finish(0,out);}
 private static AccessibilityNodeInfo root(UiAutomation a) throws Exception{
  AccessibilityNodeInfo n=a.getRootInActiveWindow();
  if(n==null)throw new GuardFailure("root_not_ready");
  if(n.getPackageName()==null || !"drug.vokrug".contentEquals(n.getPackageName()))throw new GuardFailure("wrong_package");
  if(!n.refresh())throw new GuardFailure("node_not_ready");
  if(n.getPackageName()==null || !"drug.vokrug".contentEquals(n.getPackageName()))throw new GuardFailure("wrong_package");
  return n;
 }
 private static AccessibilityNodeInfo field(UiAutomation a) throws Exception{
  ArrayList<AccessibilityNodeInfo> nodes=new ArrayList<>();nodes.add(root(a));
  AccessibilityNodeInfo edit=null;int count=0;
  for(int i=0;i<nodes.size();i++){
   AccessibilityNodeInfo n=nodes.get(i);
   if((n.isEditable() || "android.widget.EditText".contentEquals(n.getClassName())) && !n.refresh())throw new GuardFailure("node_not_ready");
   if(n.isVisibleToUser() && n.isEditable()){edit=n;count++;}
   for(int j=0;j<n.getChildCount();j++){
    if(nodes.size()>=1000)throw new GuardFailure("tree_truncated");
    AccessibilityNodeInfo child=n.getChild(j);if(child!=null)nodes.add(child);
   }
  }
  if(count!=1 || edit==null || !edit.isEnabled() || edit.isPassword()
    || edit.getPackageName()==null || !"drug.vokrug".contentEquals(edit.getPackageName())
    || !"android.widget.EditText".contentEquals(edit.getClassName()))throw new GuardFailure("editor_invalid");
  Rect r=new Rect();edit.getBoundsInScreen(r);
  if(!r.equals(new Rect(118,196,786,276)))throw new GuardFailure("editor_bounds",r);
  return edit;
 }
 private static String text(AccessibilityNodeInfo edit){
  return edit.isShowingHintText() || edit.getText()==null ? "" : edit.getText().toString();
 }
 private static String digest(byte[] bytes) throws Exception{
  StringBuilder out=new StringBuilder();
  for(byte b:MessageDigest.getInstance("SHA-256").digest(bytes))out.append(String.format(java.util.Locale.ROOT,"%02x",b&255));
  return out.toString();
 }
 private static String cropDigest(Bitmap b,int l,int t,int r,int bottom) throws Exception{
  int width=r-l,height=bottom-t;int[] colors=new int[width*height];b.getPixels(colors,0,width,l,t,width,height);
  byte[] rgb=new byte[colors.length*3];int k=0;
  for(int c:colors){rgb[k++]=(byte)(c>>>16);rgb[k++]=(byte)(c>>>8);rgb[k++]=(byte)c;}
  return digest(rgb);
 }
 private static Bitmap screen(UiAutomation a) throws Exception{
  root(a);Bitmap b=a.takeScreenshot();if(b==null)throw new GuardFailure("screenshot_unavailable");
  try{
   if(b.getWidth()!=900 || b.getHeight()!=1600)throw new GuardFailure("screen_size");
  if(!"50331b5d952f8fe1023158c36ad14853544677498c9dba2c3ec79c6f748b8633".equals(cropDigest(b,330,116,574,162)))throw new GuardFailure("title_anchor");
  if(!"0f46440361d98a420a6263bcbe0c0a42d5e6be8a1b10f9e5b448164b4eb0ee8e".equals(cropDigest(b,60,216,100,258)))throw new GuardFailure("search_anchor");
   return b;
  }catch(Exception e){b.recycle();throw e;}
 }
 private static String context(Bitmap b) throws Exception{
  int[] colors=new int[900*1552];b.getPixels(colors,0,900,0,48,900,1552);
  byte[] rgb=new byte[colors.length*3];int k=0;
  for(int i=0;i<colors.length;i++){
   int c=colors[i],x=i%900,y=i/900+48;
   // ONLY the exact native city search editor; no caller masks or result masks.
   if(x>=118 && x<786 && y>=196 && y<276)c=0;
   rgb[k++]=(byte)(c>>>16);rgb[k++]=(byte)(c>>>8);rgb[k++]=(byte)c;
  }
  return digest(rgb);
 }
 private static String checkedContext(UiAutomation a) throws Exception{
  Bitmap b=screen(a);try{return context(b);}finally{b.recycle();}
 }
 private void inspect(UiAutomation a) throws Exception{
  phase="inspect_before";AccessibilityNodeInfo edit=field(a);String query=text(edit);boolean focused=edit.isFocused();
  Bitmap b=screen(a);String hash;try{hash=context(b);}finally{b.recycle();}
  phase="inspect_confirm";edit=field(a);
  if(!query.equals(text(edit)) || focused!=edit.isFocused() || !hash.equals(checkedContext(a))){denied("denied_screen_changed","context_changed");return;}
  if(query.length()>128)throw new GuardFailure("query_length");
  JSONObject report=new JSONObject();report.put("catalog",CityPolicy.CATALOG);
  report.put("query",query);report.put("focused",focused);report.put("city_context_sha256",hash);
  report.put("bounds",new org.json.JSONArray(new int[]{118,196,786,276}));
  report.put("result_rows_available",false);report.put("city_selected",false);report.put("filters_applied",false);
  Bundle out=new Bundle();out.putString("navigation_status","city_inspection_ok");
  out.putString("layout_b64",Base64.encodeToString(report.toString().getBytes(StandardCharsets.UTF_8),Base64.NO_WRAP));finish(0,out);
 }
 private void input(UiAutomation a){boolean attempted=false;
  try{
   phase="input_before";int previous=previousEncoded-1;
   if(!expected.equals(checkedContext(a))){done("denied_screen_changed");return;}
   AccessibilityNodeInfo edit=field(a);
   if(!edit.isFocused() || !CityPolicy.matchesPrevious(text(edit),previous)){done("denied_field");return;}
   if(!expected.equals(checkedContext(a))){done("denied_screen_changed");return;}
   phase="input_confirm";edit=field(a);
   if(!edit.isFocused() || !CityPolicy.matchesPrevious(text(edit),previous)){done("denied_field");return;}
   Bundle value=new Bundle();value.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,CityPolicy.city(index));
   attempted=true;
   if(!edit.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,value)){done("indeterminate_after_attempt");return;}
   SystemClock.sleep(250);
   // Search rows may legitimately change. Verify only the city window/editor
   // and exact native text; never claim that results or filters are verified.
   phase="input_after";Bitmap b=screen(a);b.recycle();edit=field(a);
   done(edit.isFocused() && CityPolicy.city(index).equals(text(edit))?"city_input_native_verified":"indeterminate_after_attempt");
  }catch(Exception e){deniedFailure(attempted?"indeterminate_after_attempt":"denied_context_or_layout",e);}
 }
 @Override public void onStart(){
  try{
   UiAutomation a=getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES);
   awaitAccessibility(a);
   if("inspect_city".equals(op)){inspect(a);return;}
   if("city_input".equals(op)){input(a);return;}
   done("denied_operation");
  }catch(Exception e){deniedFailure("denied_context_or_layout",e);}
 }
}
