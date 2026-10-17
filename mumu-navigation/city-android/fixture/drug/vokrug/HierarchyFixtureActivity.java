package drug.vokrug;
import android.app.Activity;
import android.os.Bundle;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.view.MotionEvent;
import android.view.View;
import android.widget.*;
/** No-network synthetic UI. Android nodes and a separately drawn fallback label. */
public final class HierarchyFixtureActivity extends Activity {
 private int dp(int value){return (int)(getResources().getDisplayMetrics().density*value+.5f);}
 @Override public void onCreate(Bundle state){
  super.onCreate(state);getWindow().setFlags(1024,1024);getWindow().getDecorView().setSystemUiVisibility(4096|1024|512|256|4|2);
  if("visual".equals(getIntent().getStringExtra("scenario"))){setContentView(new Visual());return;}
  final LinearLayout root=new LinearLayout(this);root.setOrientation(1);root.setPadding(dp(8),dp(8),dp(8),dp(8));root.setFocusableInTouchMode(true);
  TextView title=new TextView(this);title.setText("Поиск города");root.addView(title);
  final EditText edit=new EditText(this);edit.setId(android.R.id.edit);edit.setSingleLine(true);edit.setHint("Поиск");edit.setShowSoftInputOnFocus(false);edit.setCursorVisible(false);root.addView(edit,new LinearLayout.LayoutParams(-1,dp(48)));
  final TextView result=new TextView(this);result.setText("clicks=0");result.setContentDescription("Action result");
  Button button=new Button(this);button.setId(android.R.id.button1);button.setAllCaps(false);button.setText("Написать");button.setContentDescription("Открыть чат");
  button.setOnClickListener(new View.OnClickListener(){int count=0;public void onClick(View view){result.setText("clicks="+(++count));}});
  root.addView(button,new LinearLayout.LayoutParams(-1,dp(48)));
  Button duplicate=new Button(this);duplicate.setId(android.R.id.button2);duplicate.setAllCaps(false);duplicate.setText("Написать");duplicate.setContentDescription("Открыть чат");root.addView(duplicate,new LinearLayout.LayoutParams(-1,dp(48)));
  CheckBox online=new CheckBox(this);online.setText("Только онлайн");root.addView(online);
  root.addView(result);
  EditText password=new EditText(this);password.setId(android.R.id.text2);password.setInputType(129);password.setText("SECRET_PASSWORD");password.setShowSoftInputOnFocus(false);password.setCursorVisible(false);root.addView(password,new LinearLayout.LayoutParams(-1,dp(40)));
  setContentView(root);root.requestFocus();
 }
 private final class Visual extends View {
  private int clicks=0;
  Visual(){super(HierarchyFixtureActivity.this);setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_YES);setContentDescription("visual-clicks=0");}
  @Override protected void onDraw(Canvas canvas){
   canvas.drawColor(Color.WHITE);Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);p.setColor(Color.BLACK);p.setTextSize(dp(36));
   String text="Написать";canvas.drawText(text,(getWidth()-p.measureText(text))/2,getHeight()/2,p);
  }
  @Override public boolean onTouchEvent(MotionEvent event){
   if(event.getAction()==MotionEvent.ACTION_UP){clicks++;setContentDescription("visual-clicks="+clicks);return true;}return true;
  }
 }
}
