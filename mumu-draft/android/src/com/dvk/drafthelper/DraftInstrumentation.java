package com.dvk.drafthelper;

import android.app.Instrumentation;
import android.app.UiAutomation;
import android.graphics.Rect;
import android.os.Bundle;
import android.os.SystemClock;
import android.util.Base64;
import android.view.accessibility.AccessibilityNodeInfo;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;

/** Only ACTION_SET_TEXT with one compiled-in phrase. No clicks, keys or IME actions. */
public final class DraftInstrumentation extends Instrumentation {
    private static final String TARGET = "drug.vokrug";
    private static final String DRAFT = "Как настроение?)";
    private String expectedName;
    @Override public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        try {
            if (arguments == null || !"draft".equals(arguments.getString("op"))) { done("denied_operation"); return; }
            expectedName = new String(Base64.decode(arguments.getString("expected_name_b64", ""), Base64.NO_WRAP), StandardCharsets.UTF_8).trim();
            if (expectedName.isEmpty() || expectedName.length() > 80 || expectedName.contains("\n") || expectedName.contains("\r")) { done("denied_name"); return; }
            start();
        } catch (Exception ignored) { done("denied_arguments"); }
    }
    private void done(String status) {
        Bundle out = new Bundle(); out.putString("draft_status", status); out.putString("send_action", "not_implemented");
        finish(0, out);
    }
    private static ArrayList<AccessibilityNodeInfo> nodes(AccessibilityNodeInfo root) throws Exception {
        ArrayList<AccessibilityNodeInfo> all = new ArrayList<>(); all.add(root);
        for (int i=0; i<all.size(); i++) {
            if (all.size()>3000) throw new Exception("too many nodes");
            AccessibilityNodeInfo node=all.get(i);
            for (int j=0;j<node.getChildCount();j++) { AccessibilityNodeInfo child=node.getChild(j); if(child!=null) all.add(child); }
        }
        return all;
    }
    private AccessibilityNodeInfo checkedField(AccessibilityNodeInfo root) throws Exception {
        if (root==null || !TARGET.contentEquals(root.getPackageName()==null?"":root.getPackageName())) throw new Exception("wrong package");
        Rect outer=new Rect();root.getBoundsInScreen(outer);
        int headerBottom=outer.top+Math.max(120,outer.height()/7);
        boolean headerMatch=false; AccessibilityNodeInfo field=null; int count=0;
        for(AccessibilityNodeInfo node:nodes(root)) {
            if (!node.isVisibleToUser()) continue;
            Rect bounds=new Rect();node.getBoundsInScreen(bounds);
            String label=node.getText()==null?"":node.getText().toString().trim();
            if(bounds.top<headerBottom && expectedName.equals(label)) headerMatch=true;
            if(node.isEditable() || "android.widget.EditText".contentEquals(node.getClassName()==null?"":node.getClassName())) {
                count++;field=node;
            }
        }
        if(!headerMatch) throw new Exception("name not confirmed");
        if(count!=1 || field==null || !field.isEnabled() || field.isPassword() || !field.isEditable()) throw new Exception("field not unique");
        return field;
    }
    private static boolean hasDraft(AccessibilityNodeInfo field) {
        return !field.isShowingHintText() && field.getText()!=null && field.getText().length()!=0;
    }
    @Override public void onStart() {
        boolean attempted=false;
        try {
            // Do not suppress or change the user's enabled accessibility services.
            UiAutomation automation=getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES);
            AccessibilityNodeInfo root=null;
            for(int i=0;i<10 && root==null;i++) {root=automation.getRootInActiveWindow();if(root==null)SystemClock.sleep(200);}
            AccessibilityNodeInfo field=checkedField(root);
            if(hasDraft(field)) {done("denied_nonempty_draft");return;}
            // Re-resolve the active tree immediately before the one allowed mutation.
            field=checkedField(automation.getRootInActiveWindow());
            if(hasDraft(field)) {done("denied_nonempty_draft");return;}
            Bundle text=new Bundle();text.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,DRAFT);
            attempted=true;
            if(!field.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,text)) {done("indeterminate_set_text");return;}
            SystemClock.sleep(250);
            field=checkedField(automation.getRootInActiveWindow());
            if(field.getText()!=null && DRAFT.contentEquals(field.getText())) done("draft_set_verified");
            else done("indeterminate_readback");
        } catch(Exception ignored) {done(attempted?"indeterminate_after_attempt":"denied_context_or_field");}
    }
}
