package drug.vokrug;
import android.app.Activity;
import android.os.Bundle;
import android.graphics.Color;
import android.view.View;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.TextView;
/** Disposable synthetic UI: no network, accounts or real recipients. */
public final class GestureFixtureActivity extends Activity {
 private int taps=0;
 @Override public void onCreate(Bundle state){
  super.onCreate(state);
  getWindow().setFlags(1024,1024);
  getWindow().getDecorView().setSystemUiVisibility(4096|1024|512|256|4|2);
  getWindow().setSoftInputMode(3|48);
  final FrameLayout layout=new FrameLayout(this);layout.setBackgroundColor(Color.rgb(24,28,33));
  final EditText input=new EditText(this);input.setSingleLine(true);input.setPadding(0,0,0,0);
  input.setText("Нижнекамск");input.setTextColor(Color.WHITE);input.setCursorVisible(true);
  FrameLayout.LayoutParams field=new FrameLayout.LayoutParams(668,80);field.leftMargin=118;field.topMargin=196;layout.addView(input,field);
  final TextView result=new TextView(this);result.setText("Нижнекамск · Республика Татарстан · Россия");result.setTextColor(Color.WHITE);
  FrameLayout.LayoutParams row=new FrameLayout.LayoutParams(820,100);row.leftMargin=40;row.topMargin=330;layout.addView(result,row);
  final TextView counter=new TextView(this);counter.setText("candidate_taps=0");counter.setTextColor(Color.WHITE);
  FrameLayout.LayoutParams count=new FrameLayout.LayoutParams(700,80);count.leftMargin=40;count.topMargin=500;layout.addView(counter,count);
  result.setOnClickListener(new View.OnClickListener(){public void onClick(View v){counter.setText("candidate_taps="+(++taps));}});
  // Deterministic continuous rendering changes wholly INSIDE the exact editor.
  // This tests normalization without needing to catch a native cursor blink.
  final View cursor=new View(this);cursor.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
  FrameLayout.LayoutParams stripe=new FrameLayout.LayoutParams(3,70);stripe.leftMargin=410;stripe.topMargin=201;layout.addView(cursor,stripe);
  cursor.post(new Runnable(){private boolean on;public void run(){on=!on;cursor.setBackgroundColor(on?Color.WHITE:Color.BLACK);cursor.postDelayed(this,80);}});
  setContentView(layout);input.requestFocus();
  ((android.view.inputmethod.InputMethodManager)getSystemService(INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(input.getWindowToken(),0);
 }
}
