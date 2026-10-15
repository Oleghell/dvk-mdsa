package drug.vokrug;
import android.app.Activity;
import android.os.Bundle;
import android.widget.*;
public class FixtureActivity extends Activity {
 @Override public void onCreate(Bundle b){
  super.onCreate(b);
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
}
