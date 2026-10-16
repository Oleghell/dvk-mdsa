package drug.vokrug;
import android.app.Activity;
import android.os.Bundle;
import android.widget.*;
public class FixtureActivity extends Activity {
 @Override public void onCreate(Bundle b){
  super.onCreate(b);
  if(getIntent().getStringExtra("scenario")!=null && getIntent().getStringExtra("scenario").startsWith("greeting")){
   greetingFixture();return;
  }
  if(getIntent().getStringExtra("scenario")!=null && getIntent().getStringExtra("scenario").startsWith("profile")){
   getWindow().setFlags(android.view.WindowManager.LayoutParams.FLAG_FULLSCREEN,android.view.WindowManager.LayoutParams.FLAG_FULLSCREEN);
   getWindow().getDecorView().setSystemUiVisibility(4096|1024|512|256|4|2);
   setContentView(new ProfileFixture());return;
  }
  getWindow().setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_HIDDEN);
  LinearLayout root=new LinearLayout(this);root.setOrientation(1);
  TextView title=new TextView(this);title.setText("SYNTHETIC NAVIGATION ONLY");root.addView(title);
  final TextView count=new TextView(this);count.setText("clicks=0");root.addView(count);
  Button nav=new Button(this);nav.setText("NAVIGATE");nav.setOnClickListener(new android.view.View.OnClickListener(){public void onClick(android.view.View v){count.setText("clicks=1");}});root.addView(nav);
  EditText draft=new EditText(this);draft.setSingleLine(true);draft.setText("KEEP_EXISTING");root.addView(draft);
  final TextView sent=new TextView(this);sent.setText("sent=0");root.addView(sent);
  Button send=new Button(this);send.setText("SEND (TEST ONLY)");send.setOnClickListener(new android.view.View.OnClickListener(){public void onClick(android.view.View v){sent.setText("sent=1");}});root.addView(send);
  root.setFocusableInTouchMode(true);root.requestFocus();setContentView(root);
 }
 private final class ProfileFixture extends android.view.View {
  private final android.graphics.Paint paint=new android.graphics.Paint();
  private final android.graphics.Bitmap icon;
  private int clicks=0,gifts=0;private boolean blue=false;
  ProfileFixture(){
   super(FixtureActivity.this);
   byte[] raw=android.util.Base64.decode("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",android.util.Base64.DEFAULT);
   icon=android.graphics.BitmapFactory.decodeByteArray(raw,0,raw.length);
   blue=getIntent().getStringExtra("scenario").equals("profile_b");
   setContentDescription("chat=0 gifts=0");setImportantForAccessibility(android.view.View.IMPORTANT_FOR_ACCESSIBILITY_YES);
   if(getIntent().getStringExtra("scenario").equals("profile_animated")){
    postDelayed(new Runnable(){public void run(){blue=!blue;invalidate();postDelayed(this,200);}},200);
   }
  }
  @Override protected void onDraw(android.graphics.Canvas c){
   c.drawColor(android.graphics.Color.WHITE);
   paint.setColor(android.graphics.Color.BLACK);paint.setTextSize(32);c.drawText("SYNTHETIC PROFILE",30,300,paint);
   if(getIntent().getStringExtra("scenario").equals("profile_other"))c.drawText("OTHER IDENTITY",30,400,paint);
   if(clicks>0)c.drawText("CHAT OPENED",30,500,paint);
   paint.setColor(blue?android.graphics.Color.BLUE:android.graphics.Color.RED);c.drawRect(727,830,879,981,paint);
   c.drawBitmap(icon,274,1468,null);
   if(getIntent().getStringExtra("scenario").equals("profile_corner")){paint.setColor(android.graphics.Color.MAGENTA);c.drawRect(274,1468,282,1476,paint);}
   if(getIntent().getStringExtra("scenario").equals("profile_bad_button")){paint.setColor(android.graphics.Color.WHITE);c.drawRect(300,1500,340,1530,paint);}
  }
  @Override public boolean onTouchEvent(android.view.MotionEvent e){
   if(e.getAction()==android.view.MotionEvent.ACTION_UP){
    if(e.getX()>=274 && e.getX()<370 && e.getY()>=1468 && e.getY()<1564)clicks++;
    if(e.getX()>=720 && e.getY()>=810 && e.getY()<1032)gifts++;
    setContentDescription("chat="+clicks+" gifts="+gifts);invalidate();
   }return true;
  }
 }

 private void greetingFixture(){
  getWindow().setFlags(android.view.WindowManager.LayoutParams.FLAG_FULLSCREEN,android.view.WindowManager.LayoutParams.FLAG_FULLSCREEN);
  getWindow().getDecorView().setSystemUiVisibility(4096|1024|512|256|4|2);
  getWindow().setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_HIDDEN|android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_NOTHING);
  android.widget.FrameLayout layout=new android.widget.FrameLayout(this);
  final TextView history=new TextView(this);history.setText("greeting_other".equals(getIntent().getStringExtra("scenario"))?"OTHER SYNTHETIC RECIPIENT":"NEW SYNTHETIC CHAT, NO NETWORK");
  android.widget.FrameLayout.LayoutParams h=new android.widget.FrameLayout.LayoutParams(880,800);h.leftMargin=10;h.topMargin=100;layout.addView(history,h);
  final TextView sent=new TextView(this);sent.setText("sent=0");android.widget.FrameLayout.LayoutParams sp=new android.widget.FrameLayout.LayoutParams(200,50);sp.topMargin=1000;layout.addView(sent,sp);
  final EditText input="greeting_blink".equals(getIntent().getStringExtra("scenario"))?new BlinkEditText():new EditText(this);input.setSingleLine(true);input.setPadding(0,0,0,0);input.setHint("Message");
  if("greeting_nonempty".equals(getIntent().getStringExtra("scenario")))input.setText("KEEP_EXISTING");
  if("greeting_password".equals(getIntent().getStringExtra("scenario")))input.setInputType(129);
  android.widget.FrameLayout.LayoutParams ip=new android.widget.FrameLayout.LayoutParams(596,56);ip.leftMargin=152;ip.topMargin=1488;layout.addView(input,ip);
  if("greeting_duplicate".equals(getIntent().getStringExtra("scenario"))){EditText second=new EditText(this);android.widget.FrameLayout.LayoutParams p=new android.widget.FrameLayout.LayoutParams(200,60);p.topMargin=1200;layout.addView(second,p);}
  if("greeting_switch_after_input".equals(getIntent().getStringExtra("scenario"))){
   input.addTextChangedListener(new android.text.TextWatcher(){public void beforeTextChanged(CharSequence s,int st,int c,int a){}public void onTextChanged(CharSequence s,int st,int b,int c){history.setText("CHANGED RECIPIENT");}public void afterTextChanged(android.text.Editable e){}});
  }
  Button send=new Button(this);send.setText("SEND");android.widget.FrameLayout.LayoutParams bp=new android.widget.FrameLayout.LayoutParams(120,80);bp.leftMargin=770;bp.topMargin=1480;
  send.setOnClickListener(new android.view.View.OnClickListener(){public void onClick(android.view.View v){sent.setText("sent=1");}});layout.addView(send,bp);
  layout.setFocusableInTouchMode(true);layout.requestFocus();setContentView(layout);
 }

 private final class BlinkEditText extends EditText {
  private boolean blink=false;private final android.graphics.Paint caret=new android.graphics.Paint();
  BlinkEditText(){super(FixtureActivity.this);caret.setColor(android.graphics.Color.BLACK);
   postDelayed(new Runnable(){public void run(){blink=!blink;invalidate();postDelayed(this,150);}},150);}
  @Override protected void onDraw(android.graphics.Canvas c){super.onDraw(c);if(blink)c.drawLine(8,9,8,getHeight()-9,caret);}
 }
}
