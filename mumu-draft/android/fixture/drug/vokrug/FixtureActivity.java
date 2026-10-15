package drug.vokrug;
import android.app.Activity;
import android.os.Bundle;
import android.widget.*;
public class FixtureActivity extends Activity {
 @Override public void onCreate(Bundle b) {
  super.onCreate(b);
  getWindow().setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_HIDDEN);
  LinearLayout root=new LinearLayout(this);root.setOrientation(1);
  TextView name=new TextView(this);name.setText("TEST_RECIPIENT");name.setTextSize(24);root.addView(name);
  TextView history=new TextView(this);history.setText("SYNTHETIC CHAT, NO NETWORK");root.addView(history,new LinearLayout.LayoutParams(-1,0,1));
  EditText input=new EditText(this);input.setHint("Message");input.setSingleLine(true);
  if("nonempty".equals(getIntent().getStringExtra("scenario")))input.setText("KEEP_EXISTING");
  root.addView(input);
  TextView sent=new TextView(this);sent.setText("sent=0");root.addView(sent);
  Button send=new Button(this);send.setText("SEND");send.setOnClickListener(v -> sent.setText("sent=1"));root.addView(send);
  setContentView(root);
 }
}
