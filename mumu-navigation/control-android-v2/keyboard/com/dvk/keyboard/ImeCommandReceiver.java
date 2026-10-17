package com.dvk.keyboard;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.inputmethod.ExtractedText;
import android.view.inputmethod.ExtractedTextRequest;
import android.view.inputmethod.InputConnection;
/** Exported only behind the APK's signature permission; payloads are never logged. */
public final class ImeCommandReceiver extends BroadcastReceiver {
 static String text(InputConnection c){ExtractedText e=c.getExtractedText(new ExtractedTextRequest(),0);if(e==null || e.text==null || e.startOffset!=0 || e.partialStartOffset>=0 || e.partialEndOffset>=0 || e.text.length()>4096)throw new IllegalStateException();return e.text.toString();}
 static boolean same(BridgeIme ime,InputConnection c,long g){return BridgeIme.live==ime && ime.generation==g && ime.getCurrentInputConnection()==c && BridgeIme.safe(ime.getCurrentInputEditorInfo());}
 static boolean plain(String s){if(s==null || s.codePointCount(0,s.length())>128)return false;for(int p=0;p<s.length();){int cp=s.codePointAt(p);if(Character.isISOControl(cp) || cp==0x2028 || cp==0x2029 || cp>=0xd800 && cp<=0xdfff)return false;p+=Character.charCount(cp);}return true;}
 @Override public void onReceive(Context context,Intent intent){
  final PendingResult pending=goAsync();
  new Thread(new Runnable(){public void run(){
   boolean attempted=false;Bundle report=new Bundle();String state="denied_ime";
   try{
    long deadline=SystemClock.uptimeMillis()+65000;
    String op=intent.getStringExtra("op"),expected=intent.getStringExtra("expected_text"),value=intent.getStringExtra("text");int delay=intent.getIntExtra("delay_ms",343);
    if(!("clear".equals(op) || "type".equals(op)) || expected==null || expected.length()>4096 || !plain(value) || delay<20 || delay>500)throw new IllegalArgumentException();
    BridgeIme ime=BridgeIme.live;if(ime==null || !BridgeIme.safe(ime.getCurrentInputEditorInfo()))throw new IllegalStateException();
    long g=ime.generation;InputConnection c=ime.getCurrentInputConnection();if(c==null || !same(ime,c,g) || !expected.equals(text(c)))throw new IllegalStateException();
    if("type".equals(op) && value.codePointCount(0,value.length())!=1)throw new IllegalStateException();
    long previous=intent.getLongExtra("generation",-1);if(previous!=-1 && previous!=g)throw new IllegalStateException();
    report.putLong("generation",g);
    if("clear".equals(op)){
     if(!same(ime,c,g) || !expected.equals(text(c)))throw new IllegalStateException();
     attempted=true;if(!c.setSelection(0,expected.length()) || !c.commitText("",1))throw new IllegalStateException();
     if(!same(ime,c,g) || !"".equals(text(c)))throw new IllegalStateException();
    }else{
     String prefix=expected;
     for(int p=0;p<value.length();){
      if(SystemClock.uptimeMillis()>deadline || !same(ime,c,g) || !prefix.equals(text(c)))throw new IllegalStateException();
      int cp=value.codePointAt(p);String letter=new String(Character.toChars(cp));
      attempted=true;if(!c.commitText(letter,1))throw new IllegalStateException();prefix+=letter;p+=Character.charCount(cp);
      SystemClock.sleep(delay);
      if(SystemClock.uptimeMillis()>deadline || !same(ime,c,g) || !prefix.equals(text(c)))throw new IllegalStateException();
     }
    }
    state="text_verified";
   }catch(Exception e){state=attempted?"indeterminate_after_attempt":"denied_ime";}
   report.putString("control_status",state);pending.setResultExtras(report);pending.finish();
  }},"supervised-ime").start();
 }
}
