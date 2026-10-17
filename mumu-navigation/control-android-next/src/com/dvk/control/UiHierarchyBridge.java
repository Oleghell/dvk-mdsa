package com.dvk.control;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.app.Instrumentation;
import android.app.UiAutomation;
import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Point;
import android.graphics.Rect;
import android.os.Bundle;
import android.os.SystemClock;
import android.util.DisplayMetrics;
import android.view.Display;
import android.view.InputDevice;
import android.view.MotionEvent;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityNodeInfo;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.HashSet;
import org.json.JSONArray;
import org.json.JSONObject;
/** Hierarchy-first native bridge. No screenshot in dump/find/click/setText/back.
 * Screenshots occur ONLY in the explicitly requested visual fallback operation.
 * Business authorization and durable single-attempt journal belong to the host.
 */
public final class UiHierarchyBridge {
 private final Instrumentation owner;private final UiAutomation auto;
 public boolean attempted=false;private int matchCalls=0;
 private static final String PKG="drug.vokrug";
 public static final class Result {
  public final String state;public final JSONObject data;
  Result(String s,JSONObject d){state=s;data=d;}
 }
 private static final class Tree {
  final ArrayList<AccessibilityNodeInfo> nodes=new ArrayList<>();
  final ArrayList<Integer> parents=new ArrayList<>();final JSONArray rows=new JSONArray();
  int width,height,rotation,density;boolean truncated=false;String sha;
  JSONObject json()throws Exception{return new JSONObject().put("package",PKG).put("width",width).put("height",height).put("rotation",rotation).put("density_dpi",density).put("truncated",truncated).put("nodes",rows).put("tree_sha256",sha).put("identity_verified",false).put("empty_chat_verified",false).put("ui_hierarchy_supported",true);}
 }
 public UiHierarchyBridge(Instrumentation owner,UiAutomation auto){this.owner=owner;this.auto=auto;AccessibilityServiceInfo info=auto.getServiceInfo();if(info!=null){info.flags|=AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS;auto.setServiceInfo(info);}}
 private static String text(CharSequence c){return c==null?"":c.toString();}
 private static String value(AccessibilityNodeInfo n){return n.isShowingHintText()?"":text(n.getText());}
 private static String hex(byte[] bytes)throws Exception{StringBuilder out=new StringBuilder();for(byte b:bytes)out.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return out.toString();}
 private static String hash(String s)throws Exception{return hex(MessageDigest.getInstance("SHA-256").digest(s.getBytes(StandardCharsets.UTF_8)));}
 private static void keys(JSONObject o,String... allowed)throws Exception{
  HashSet<String> set=new HashSet<>();for(String s:allowed)set.add(s);
  Iterator<String> it=o.keys();while(it.hasNext())if(!set.contains(it.next()))throw new Exception();
 }
 private static boolean selectorValid(JSONObject s,int depth)throws Exception{
  if(depth>2 || s.length()<1 || s.length()>15)return false;
  keys(s,"resource_id","description","text","text_contains","class_name","clickable","enabled","editable","focused","checked","checkable","selected","parent","ancestor","child","below","first");
  boolean semantic=false;Iterator<String> it=s.keys();
  while(it.hasNext()){
   String k=it.next();Object v=s.get(k);
   if("first".equals(k)){if(!Boolean.TRUE.equals(v))return false;}
   else if("parent".equals(k)||"ancestor".equals(k)||"child".equals(k)||"below".equals(k)){if(!(v instanceof JSONObject)||!selectorValid((JSONObject)v,depth+1))return false;semantic=true;}
   else if("resource_id".equals(k)||"description".equals(k)||"text".equals(k)||"text_contains".equals(k)||"class_name".equals(k)){
    if(!(v instanceof String)||((String)v).length()<1||((String)v).length()>256)return false;
    for(char c:((String)v).toCharArray())if(c<32)return false;semantic=true;
   }else{if(!(v instanceof Boolean))return false;if("editable".equals(k)&&Boolean.TRUE.equals(v))semantic=true;}
  }return semantic || depth>0;
 }
 private Tree tree()throws Exception{
  AccessibilityNodeInfo root=auto.getRootInActiveWindow();if(root==null || !root.refresh() || !PKG.equals(text(root.getPackageName())))throw new Exception();
  Tree t=new Tree();WindowManager wm=(WindowManager)owner.getContext().getSystemService(Context.WINDOW_SERVICE);
  Display display=wm.getDefaultDisplay();Point size=new Point();display.getRealSize(size);DisplayMetrics m=new DisplayMetrics();display.getRealMetrics(m);
  t.width=size.x;t.height=size.y;t.rotation=display.getRotation();t.density=m.densityDpi;
  if(t.width<200||t.height<200||t.width>4096||t.height>4096||(long)t.width*t.height>10000000)throw new Exception();
  ArrayList<AccessibilityNodeInfo> pending=new ArrayList<>();ArrayList<Integer> parents=new ArrayList<>();pending.add(root);parents.add(-1);
  for(int i=0;i<pending.size();i++){
   if(i>=1000){t.truncated=true;break;}
   AccessibilityNodeInfo n=pending.get(i);if(!n.refresh())throw new Exception();
   int visibleParent=parents.get(i);
   if(n.isVisibleToUser() && PKG.equals(text(n.getPackageName()))){
    int index=t.nodes.size();t.nodes.add(n);t.parents.add(visibleParent);Rect b=new Rect();n.getBoundsInScreen(b);
    boolean secret=n.isPassword();
    JSONObject row=new JSONObject().put("index",index).put("parent",visibleParent).put("package",PKG)
     .put("bounds",new JSONArray(new int[]{b.left,b.top,b.right,b.bottom})).put("resource_id",text(n.getViewIdResourceName()))
     .put("class_name",text(n.getClassName())).put("description",secret?"":text(n.getContentDescription())).put("text",secret?"":value(n))
     .put("clickable",n.isClickable()).put("enabled",n.isEnabled()).put("editable",n.isEditable()).put("focused",n.isFocused())
     .put("checked",n.isChecked()).put("checkable",n.isCheckable()).put("selected",n.isSelected()).put("visible",true).put("password",secret);
    t.rows.put(row);visibleParent=index;
   }
   for(int j=0;j<n.getChildCount();j++){
    if(pending.size()>=1000){t.truncated=true;break;}
    AccessibilityNodeInfo c=n.getChild(j);if(c!=null){pending.add(c);parents.add(visibleParent);}
   }
  }
  t.sha=hash(t.width+":"+t.height+":"+t.rotation+":"+t.density+":"+t.rows.toString());return t;
 }
 private boolean matches(Tree t,int index,JSONObject s,int depth)throws Exception{
  if(++matchCalls>100000)throw new Exception();if(depth>10)return false;JSONObject n=t.rows.getJSONObject(index);if(n.getBoolean("password"))return false;
  Iterator<String> it=s.keys();while(it.hasNext()){
   String k=it.next();Object wanted=s.get(k);
   if("first".equals(k))continue;
   if("below".equals(k)){int anchor=-1;for(int j=0;j<t.nodes.size();j++)if(matches(t,j,(JSONObject)wanted,depth+1)){if(anchor>=0)throw new Exception();anchor=j;}
    if(anchor<0||n.getJSONArray("bounds").getInt(1)<t.rows.getJSONObject(anchor).getJSONArray("bounds").getInt(3))return false;
   }else if("parent".equals(k)){int p=t.parents.get(index);if(p<0||!matches(t,p,(JSONObject)wanted,depth+1))return false;}
   else if("ancestor".equals(k)){boolean found=false;int p=t.parents.get(index);for(int j=0;j<32&&p>=0;j++){if(matches(t,p,(JSONObject)wanted,depth+1)){found=true;break;}p=t.parents.get(p);}if(!found)return false;}
   else if("child".equals(k)){boolean found=false;for(int j=0;j<t.nodes.size();j++)if(t.parents.get(j)==index&&matches(t,j,(JSONObject)wanted,depth+1)){found=true;break;}if(!found)return false;}
   else if("text_contains".equals(k)){if(!n.getString("text").contains((String)wanted))return false;}
   else if(!wanted.equals(n.get(k)))return false;
  }return true;
 }
 private int find(Tree t,JSONObject s)throws Exception{
  if(t.truncated)return -3;matchCalls=0;int found=-1;
  for(int i=0;i<t.nodes.size();i++)if(matches(t,i,s,0)){
   if(found!=-1){if(!s.optBoolean("first",false))return -2;
    JSONArray a=t.rows.getJSONObject(found).getJSONArray("bounds"),b=t.rows.getJSONObject(i).getJSONArray("bounds");
    if(b.getInt(1)<a.getInt(1)||b.getInt(1)==a.getInt(1)&&b.getInt(0)<a.getInt(0))found=i;
   }else found=i;
  }
  if(found<0)return found;Rect b=new Rect();t.nodes.get(found).getBoundsInScreen(b);
  if(b.left<0||b.top<0||b.right>t.width||b.bottom>t.height||b.width()<1||b.height()<1)return -3;
  return found;
 }
 private Result refused(int found){return new Result(found==-1?"denied_not_found":found==-2?"denied_ambiguous":"denied_incomplete",null);}
 private String screenshotHash(Bitmap image)throws Exception{
  MessageDigest md=MessageDigest.getInstance("SHA-256");int w=image.getWidth(),h=image.getHeight();
  if(w<200||h<200||w>4096||h>4096||(long)w*h>10000000)throw new Exception();
  md.update((w+":"+h+":").getBytes(StandardCharsets.US_ASCII));int[] row=new int[w];byte[] rgb=new byte[w*3];
  for(int y=0;y<h;y++){image.getPixels(row,0,w,0,y,w,1);for(int x=0;x<w;x++){int c=row[x];rgb[x*3]=(byte)(c>>16);rgb[x*3+1]=(byte)(c>>8);rgb[x*3+2]=(byte)c;}md.update(rgb);}return hex(md.digest());
 }
 private void tap(int x,int y)throws Exception{
  long now=SystemClock.uptimeMillis();MotionEvent down=MotionEvent.obtain(now,now,MotionEvent.ACTION_DOWN,x,y,0);down.setSource(InputDevice.SOURCE_TOUCHSCREEN);
  MotionEvent up=MotionEvent.obtain(now,now+1,MotionEvent.ACTION_UP,x,y,0);up.setSource(InputDevice.SOURCE_TOUCHSCREEN);
  attempted=true;try{if(!auto.injectInputEvent(down,true))throw new Exception();if(!auto.injectInputEvent(up,true))throw new Exception();}finally{down.recycle();up.recycle();}
 }
 public Result run(JSONObject request)throws Exception{
  String op=request.getString("op");
  if("ui_dump".equals(op)){keys(request,"op");return new Result("inspection_ok",tree().json());}
  if("ui_visual_click".equals(op)){
   keys(request,"op","expected_tree_sha256","expected_frame_sha256","bounds");Tree t=tree();
   if(t.truncated||!t.sha.equals(request.getString("expected_tree_sha256")))return new Result("denied_screen_changed",null);
   JSONArray a=request.getJSONArray("bounds");if(a.length()!=4)return new Result("denied_arguments",null);
   for(int i=0;i<4;i++)if(!(a.get(i) instanceof Integer))return new Result("denied_arguments",null);
   Rect b=new Rect(a.getInt(0),a.getInt(1),a.getInt(2),a.getInt(3));
   if(b.left<0||b.top<0||b.right>t.width||b.bottom>t.height||b.width()<1||b.height()<1)return new Result("denied_arguments",null);
   String expected=request.getString("expected_frame_sha256");if(!expected.matches("[0-9a-f]{64}"))return new Result("denied_arguments",null);
   for(int i=0;i<2;i++){Bitmap image=auto.takeScreenshot();if(image==null)throw new Exception();try{if(!expected.equals(screenshotHash(image)))return new Result("denied_screen_changed",null);}finally{image.recycle();}}
   Tree finalTree=tree();if(!t.sha.equals(finalTree.sha))return new Result("denied_screen_changed",null);
   tap(b.centerX(),b.centerY());return new Result("input_injected",new JSONObject().put("method","visual_bounds").put("result_verified",false));
  }
  if("ui_back".equals(op)){
   keys(request,"op","expected_tree_sha256");Tree t=tree();if(t.truncated||!t.sha.equals(request.getString("expected_tree_sha256")))return new Result("denied_screen_changed",null);
   attempted=true;if(!auto.performGlobalAction(android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_BACK))throw new Exception();return new Result("input_injected",null);
  }
  if(!"ui_click".equals(op)&&!"ui_set_text".equals(op))return new Result("denied_arguments",null);
  if("ui_click".equals(op))keys(request,"op","selector","expected_tree_sha256","allow_coordinate_fallback");
  else keys(request,"op","selector","expected_tree_sha256","text","expected_text");
  JSONObject s=request.getJSONObject("selector");if(!selectorValid(s,0))return new Result("denied_arguments",null);
  String expected=request.getString("expected_tree_sha256");if(!expected.matches("[0-9a-f]{64}"))return new Result("denied_arguments",null);
  Tree before=tree();if(before.truncated||!expected.equals(before.sha))return new Result("denied_screen_changed",null);
  int index=find(before,s);if(index<0)return refused(index);
  Tree current=tree();if(current.truncated||!expected.equals(current.sha))return new Result("denied_screen_changed",null);
  index=find(current,s);if(index<0)return refused(index);AccessibilityNodeInfo n=current.nodes.get(index);
  if(!n.refresh()||!PKG.equals(text(n.getPackageName()))||!n.isVisibleToUser()||!n.isEnabled()||n.isPassword())return new Result("denied_context",null);
  Rect bounds=new Rect();n.getBoundsInScreen(bounds);JSONObject row=current.rows.getJSONObject(index);
  JSONArray prior=row.getJSONArray("bounds");if(bounds.left!=prior.getInt(0)||bounds.top!=prior.getInt(1)||bounds.right!=prior.getInt(2)||bounds.bottom!=prior.getInt(3))return new Result("denied_screen_changed",null);
  if(!text(n.getViewIdResourceName()).equals(row.getString("resource_id"))||!text(n.getContentDescription()).equals(row.getString("description"))||!value(n).equals(row.getString("text"))||n.isEditable()!=row.getBoolean("editable")||n.isClickable()!=row.getBoolean("clickable"))return new Result("denied_screen_changed",null);
  if("ui_set_text".equals(op)){
   String old=request.getString("expected_text"),value=request.getString("text");
   if(!n.isEditable()||old.length()>4096||value.length()>256||!old.equals(value(n)))return new Result("denied_field",null);
   for(int i=0;i<value.length();){int cp=value.codePointAt(i);if(cp<32||(cp>=127&&cp<=159)||(cp>=0xd800&&cp<=0xdfff)||cp==0x2028||cp==0x2029)return new Result("denied_arguments",null);i+=Character.charCount(cp);}
   if((n.getActions()&AccessibilityNodeInfo.ACTION_SET_TEXT)==0)return new Result("denied_unsupported",null);
   Bundle args=new Bundle();args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,value);attempted=true;
   if(!n.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,args))throw new Exception();
   long deadline=SystemClock.uptimeMillis()+1500;
   do{if(n.refresh()&&value.equals(value(n)))return new Result("text_verified",new JSONObject().put("native_readback_verified",true).put("message_sent",false));SystemClock.sleep(40);}while(SystemClock.uptimeMillis()<deadline);
   throw new Exception();
  }
  if((n.getActions()&AccessibilityNodeInfo.ACTION_CLICK)!=0){attempted=true;if(!n.performAction(AccessibilityNodeInfo.ACTION_CLICK))throw new Exception();return new Result("input_injected",new JSONObject().put("method","accessibility_action_click").put("result_verified",false));}
  if(!(request.get("allow_coordinate_fallback") instanceof Boolean))return new Result("denied_arguments",null);
  if(!request.getBoolean("allow_coordinate_fallback"))return new Result("denied_unsupported",null);
  tap(bounds.centerX(),bounds.centerY());return new Result("input_injected",new JSONObject().put("method","native_bounds_fallback").put("result_verified",false));
 }
}
