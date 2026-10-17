package com.dvk.keyboard;
import android.inputmethodservice.InputMethodService;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputConnection;
import android.view.View;
/** No network, learning, clipboard, logs or persistence. Only the current editor. */
public final class BridgeIme extends InputMethodService {
 static volatile BridgeIme live;
 volatile long generation;
 @Override public void onCreate(){super.onCreate();live=this;}
 @Override public void onStartInput(EditorInfo info,boolean restarting){super.onStartInput(info,restarting);generation=android.os.SystemClock.elapsedRealtimeNanos();}
 @Override public void onFinishInput(){generation=android.os.SystemClock.elapsedRealtimeNanos();super.onFinishInput();}
 @Override public void onDestroy(){live=null;super.onDestroy();}
 // Keep the current InputConnection, but never resize/pan the app or display an
 // IME banner. The bridge UI owns consent/status; this service has no visual UI.
 @Override public boolean onEvaluateInputViewShown(){return false;}
 @Override public boolean onEvaluateFullscreenMode(){return false;}
 @Override public View onCreateInputView(){return null;}
 static boolean safe(EditorInfo i){
  if(i==null || !"drug.vokrug".equals(i.packageName))return false;
  int variation=i.inputType&android.text.InputType.TYPE_MASK_VARIATION;
  int cls=i.inputType&android.text.InputType.TYPE_MASK_CLASS;
  return cls==android.text.InputType.TYPE_CLASS_TEXT && variation!=android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD && variation!=android.text.InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD && variation!=android.text.InputType.TYPE_TEXT_VARIATION_WEB_PASSWORD;
 }
}
