package com.dvk.control;
import android.app.UiAutomation;
import android.graphics.Bitmap;
import android.graphics.Rect;
import android.view.accessibility.AccessibilityNodeInfo;
import java.security.MessageDigest;
import java.util.ArrayList;
import org.json.JSONArray;
import org.json.JSONObject;
/** Locate a single profile-chat target, preferring a real clickable native node.
 * Unity fallback recognizes the glyph AND close/chat/gift panel. No remote ROI.
 * The visual context is not a verified account ID. No messages/purchases here. */
public final class SemanticProfileTarget {
 public static final class Target {
  public final ProfileChatLocator.Box bounds;public final String context,method;public final int width,height;
  public final AccessibilityNodeInfo node;
  Target(ProfileChatLocator.Box b,String c,int w,int h,AccessibilityNodeInfo n){bounds=b;context=c;width=w;height=h;node=n;method=n==null?"visual_profile_panel":"accessibility_click";}
  public JSONObject report()throws Exception{return new JSONObject().put("target","profile_chat").put("bounds",new JSONArray(new int[]{bounds.left,bounds.top,bounds.right,bounds.bottom})).put("width",width).put("height",height).put("context_sha256",context).put("method",method).put("identity_verified",false);}
 }
 private static AccessibilityNodeInfo nativeNode(AccessibilityNodeInfo root,int width,int height)throws Exception{
  ArrayList<AccessibilityNodeInfo> q=new ArrayList<>();q.add(root);AccessibilityNodeInfo found=null;
  for(int i=0;i<q.size();i++){
   if(q.size()>1000)throw new Exception();AccessibilityNodeInfo n=q.get(i);
   if(!n.refresh())throw new Exception();
   String id=n.getViewIdResourceName();CharSequence description=n.getContentDescription();CharSequence text=n.getText();
   boolean label="drug.vokrug:id/profile_chat".equals(id) || "drug.vokrug:id/open_profile_chat".equals(id)
       || "Открыть чат".contentEquals(description==null?"":description) || "Открыть чат".contentEquals(text==null?"":text);
   if(label && n.isVisibleToUser() && n.isEnabled() && n.isClickable() && n.getPackageName()!=null && "drug.vokrug".contentEquals(n.getPackageName())){
    Rect r=new Rect();n.getBoundsInScreen(r);
    // Restrict native labels to a compact, visible control in the bottom panel.
    if(r.left>=0 && r.right<=width && r.top>=height*3/4 && r.bottom<=height
       && r.width()>0 && r.height()>0 && r.width()<=width/3 && r.height()<=height/5){
     if(found!=null)throw new Exception();found=n;
    }
   }
   for(int j=0;j<n.getChildCount();j++){AccessibilityNodeInfo c=n.getChild(j);if(c!=null)q.add(c);}
  }
  return found;
 }
 public static boolean nativeStillMatches(Target target){
  AccessibilityNodeInfo n=target.node;if(n==null)return true;
  if(!n.refresh() || !n.isVisibleToUser() || !n.isEnabled() || !n.isClickable() || n.getPackageName()==null || !"drug.vokrug".contentEquals(n.getPackageName()))return false;
  String id=n.getViewIdResourceName();CharSequence d=n.getContentDescription(),text=n.getText();
  boolean label="drug.vokrug:id/profile_chat".equals(id) || "drug.vokrug:id/open_profile_chat".equals(id)
   || "Открыть чат".contentEquals(d==null?"":d) || "Открыть чат".contentEquals(text==null?"":text);
  Rect b=new Rect();n.getBoundsInScreen(b);
  return label && b.left==target.bounds.left && b.top==target.bounds.top && b.right==target.bounds.right && b.bottom==target.bounds.bottom;
 }
 public static Target find(UiAutomation auto,AccessibilityNodeInfo root)throws Exception{
  if(root==null || root.getPackageName()==null || !"drug.vokrug".contentEquals(root.getPackageName()))throw new Exception();
  Bitmap image=auto.takeScreenshot();if(image==null)throw new Exception();
  try{
   int w=image.getWidth(),h=image.getHeight();if(w<320 || w>2160 || h<600 || h>3840 || h<=w || (long)w*h>8300000)return null;
   int[] pixels=new int[w*h];image.getPixels(pixels,0,w,0,0,w,h);
   AccessibilityNodeInfo nativeTarget=nativeNode(root,w,h);
   ProfileChatLocator.Box box;
   if(nativeTarget!=null){Rect b=new Rect();nativeTarget.getBoundsInScreen(b);box=new ProfileChatLocator.Box(b.left,b.top,b.right,b.bottom);}
   else box=ProfileChatLocator.locate(pixels,w,h);
   if(box==null)return null;
   // Bind intended photo + observed target to inspection. Animated gifts and
   // live-status labels are outside this COMPILED context, not caller masks.
   MessageDigest digest=MessageDigest.getInstance("SHA-256");
   String geometry=w+":"+h+":"+box.left+":"+box.top+":"+box.right+":"+box.bottom+":";
   digest.update(geometry.getBytes(java.nio.charset.StandardCharsets.US_ASCII));
   for(int y=0;y<128;y++)for(int x=0;x<256;x++){
    int sx=w*8/100+(w*62/100)*x/256,sy=h*12/100+(h*30/100)*y/128;
    int c=pixels[sy*w+sx];digest.update((byte)(c>>16));digest.update((byte)(c>>8));digest.update((byte)c);
   }
   StringBuilder hash=new StringBuilder();for(byte c:digest.digest())hash.append(String.format(java.util.Locale.ROOT,"%02x",c&255));
   return new Target(box,hash.toString(),w,h,nativeTarget);
  }finally{image.recycle();}
 }
}
