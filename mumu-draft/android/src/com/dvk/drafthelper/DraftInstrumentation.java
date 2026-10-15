package com.dvk.drafthelper;
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

/** Fixed draft only. No clicks, keys, IME actions or network. */
public final class DraftInstrumentation extends Instrumentation {
 private static final String DRAFT="Как настроение?)";
 private String operation,expectedHeader;
 private final org.json.JSONArray headerLabels=new org.json.JSONArray();
 @Override public void onCreate(Bundle args) {
  super.onCreate(args);
  operation=args==null?"":args.getString("op","");
  expectedHeader=args==null?"":args.getString("expected_header_sha256","");
  if(!"inspect".equals(operation) && !"draft".equals(operation)){done("denied_operation");return;}
  if("draft".equals(operation) && !expectedHeader.matches("[0-9a-f]{64}")){done("denied_header_argument");return;}
  start();
 }
 private void done(String status){Bundle out=new Bundle();out.putString("draft_status",status);out.putString("send_action","not_implemented");finish(0,out);}
 private static ArrayList<AccessibilityNodeInfo> nodes(AccessibilityNodeInfo root) throws Exception {
  ArrayList<AccessibilityNodeInfo> all=new ArrayList<>();all.add(root);
  for(int i=0;i<all.size();i++){
   if(all.size()>3000)throw new Exception();
   AccessibilityNodeInfo n=all.get(i);
   for(int j=0;j<n.getChildCount();j++){AccessibilityNodeInfo c=n.getChild(j);if(c!=null)all.add(c);}
  }
  return all;
 }
 private AccessibilityNodeInfo field(AccessibilityNodeInfo root) throws Exception {
  if(root==null || !"drug.vokrug".contentEquals(root.getPackageName()==null?"":root.getPackageName()))throw new Exception();
  AccessibilityNodeInfo edit=null;int count=0;
  for(AccessibilityNodeInfo n:nodes(root)){
   if(!n.isVisibleToUser())continue;
   Rect bounds=new Rect();n.getBoundsInScreen(bounds);
   String label=n.getText()==null?"":n.getText().toString().trim();
   if(bounds.top<224 && !label.isEmpty() && label.length()<=120 && headerLabels.length()<20)headerLabels.put(label);
   if(n.isEditable() || "android.widget.EditText".contentEquals(n.getClassName()==null?"":n.getClassName())){edit=n;count++;}
  }
  if(count!=1 || edit==null || !edit.isEnabled() || edit.isPassword() || !edit.isEditable())throw new Exception();
  return edit;
 }
 private static boolean hasDraft(AccessibilityNodeInfo f){return !f.isShowingHintText() && f.getText()!=null && f.getText().length()!=0;}
 private static String headerHash(UiAutomation automation) throws Exception {
  Bitmap bitmap=automation.takeScreenshot();
  if(bitmap==null || bitmap.getWidth()!=900 || bitmap.getHeight()!=1600)throw new Exception("unsupported layout");
  try{
   int[] colors=new int[900*176];bitmap.getPixels(colors,0,900,0,48,900,176);
   byte[] rgb=new byte[colors.length*3];int k=0;
   for(int color:colors){rgb[k++]=(byte)(color>>>16);rgb[k++]=(byte)(color>>>8);rgb[k++]=(byte)color;}
   byte[] hash=MessageDigest.getInstance("SHA-256").digest(rgb);
   StringBuilder hex=new StringBuilder();for(byte value:hash)hex.append(String.format(java.util.Locale.ROOT,"%02x",value&255));
   return hex.toString();
  } finally {bitmap.recycle();}
 }
 @Override public void onStart(){
  boolean attempted=false;
  try{
   UiAutomation automation=getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES);
   AccessibilityNodeInfo root=null;
   for(int i=0;i<10 && root==null;i++){root=automation.getRootInActiveWindow();if(root==null)SystemClock.sleep(200);}
   AccessibilityNodeInfo edit=field(root);
   if("inspect".equals(operation)){
    Bundle out=new Bundle();out.putString("draft_status","inspection_ok");
    out.putString("header_labels_b64",Base64.encodeToString(headerLabels.toString().getBytes(StandardCharsets.UTF_8),Base64.NO_WRAP));
    out.putString("field_empty",hasDraft(edit)?"false":"true");
    out.putString("visual_header_sha256",headerHash(automation));
    out.putString("send_action","not_implemented");finish(0,out);return;
   }
   if(hasDraft(edit)){done("denied_nonempty_draft");return;}
   if(!expectedHeader.equals(headerHash(automation))){done("denied_header_changed");return;}
   edit=field(automation.getRootInActiveWindow());
   if(hasDraft(edit)){done("denied_nonempty_draft");return;}
   Bundle text=new Bundle();text.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,DRAFT);
   attempted=true;
   if(!edit.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,text)){done("indeterminate_set_text");return;}
   SystemClock.sleep(250);
   edit=field(automation.getRootInActiveWindow());
   if(expectedHeader.equals(headerHash(automation)) && edit.getText()!=null && DRAFT.contentEquals(edit.getText()))done("draft_set_verified");
   else done("indeterminate_readback");
  }catch(Exception ignored){done(attempted?"indeterminate_after_attempt":"denied_context_or_field");}
 }
}
