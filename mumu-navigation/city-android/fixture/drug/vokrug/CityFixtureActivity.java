package drug.vokrug;
import android.app.Activity;
import android.os.Bundle;
import android.widget.*;
/** Synthetic city controls only. No network or real accounts. */
public final class CityFixtureActivity extends Activity {
 private String scenario;
 private boolean badAnchor=false;
 @Override public void onCreate(Bundle b){
  super.onCreate(b);scenario=getIntent().getStringExtra("scenario");
  if(scenario==null)scenario="city_empty";
  getWindow().setFlags(1024,1024);getWindow().getDecorView().setSystemUiVisibility(4096|1024|512|256|4|2);
  getWindow().setSoftInputMode(3|48);
  final FrameLayout layout=new FrameLayout(this);final android.view.View background=new Background();layout.addView(background,new FrameLayout.LayoutParams(-1,-1));
  EditText input=new EditText(this){
   private int reports=0;
   @Override public void onInitializeAccessibilityNodeInfo(android.view.accessibility.AccessibilityNodeInfo info){
    super.onInitializeAccessibilityNodeInfo(info);
    if("city_settling_bounds".equals(scenario) && reports++<6 || "city_reported_badbounds".equals(scenario)){
     info.setBoundsInScreen(new android.graphics.Rect(118,197,786,277));
    }
   }
  };input.setSingleLine(true);input.setPadding(0,0,0,0);input.setHint("Поиск");
  if("city_old".equals(scenario))input.setText("Нальчик");
  if("city_nonempty".equals(scenario))input.setText("KEEP_EXISTING");
  if("city_password".equals(scenario))input.setInputType(129);
  FrameLayout.LayoutParams ip=new FrameLayout.LayoutParams(668,80);ip.leftMargin=118;ip.topMargin="city_badbounds".equals(scenario)?197:196;layout.addView(input,ip);
  if("city_duplicate".equals(scenario)){EditText second=new EditText(this);FrameLayout.LayoutParams sp=new FrameLayout.LayoutParams(300,80);sp.topMargin=600;layout.addView(second,sp);}
  if("city_switch_after_input".equals(scenario)){
   input.addTextChangedListener(new android.text.TextWatcher(){public void beforeTextChanged(CharSequence s,int a,int c,int n){}public void afterTextChanged(android.text.Editable e){}public void onTextChanged(CharSequence s,int a,int b,int c){badAnchor=true;background.invalidate();}});
  }
  layout.setFocusableInTouchMode(true);setContentView(layout);
  if("city_unfocused".equals(scenario))layout.requestFocus();else input.requestFocus();
  ((android.view.inputmethod.InputMethodManager)getSystemService(INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(input.getWindowToken(),0);
 }
 private final class Background extends android.view.View {
  Background(){super(CityFixtureActivity.this);}
  @Override protected void onDraw(android.graphics.Canvas c){
   c.drawColor(android.graphics.Color.rgb(24,28,33));
   byte[] title=android.util.Base64.decode("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",android.util.Base64.DEFAULT);
   c.drawBitmap(android.graphics.BitmapFactory.decodeByteArray(title,0,title.length),330,116,null);
   byte[] search_icon=android.util.Base64.decode("iVBORw0KGgoAAAANSUhEUgAAACgAAAAqCAIAAABOVI4xAAAEkElEQVR4nMWXy4obOxCG/wwKVEMHqsCGFnggWgSOw9mc93+PzCILBTygBhskSIMKosVZSL6M3Z7xZHKphWnr9qlKparSu/W//+FviLl9IBmCAZnu2FigJWtRlN8AJiKiTj5w/QBRZwAgF6CoalZVnTTmqJP+GjAZkqUwM/VdR0znvQAIPQPQojxxSiluo+pN+KtgZrHLQRZC5khUKApQkIEOIKLDFi1b6YXZpl0I2/Ci8efB1tphsF3ftFRonjSlqJPmHycKvYcQU0/CQobIkGUSIjLkg3+ePQO21g4rJ0QAFMhTGh9D/B5RoOXcjMlEMhQ+jHYxNDyRXVkYeO9fAbZLO6zsgRpGHzbhuWMr0KKqqjEnScPKSs9kyA4WeI79BMwsw8oKcf3rvz2ETbicUw9CC9IYwrYN0KJhG/IPxScnxGTIrpyqhjCzwhMwGbJ2kOqlUP/Nz1Kpp8PmLPOwsv7Rp22svSlF/xX4tBYiAtxHF+O8n98dvkREekG18GOYpaJ2KxRtLen58z/r9Xp98PCU4vjoqzeQIefc7DJ3B3WZuU7OU7pmHwBa1HsfHkOcUlsdJAtxznEvdUzYhphi3ZqwMMvlOs3U1HfCVV0dx3DpvaeSppimSCaIlYFtx0QgWVgAusk6KQq898ICQwBEOKU4r3H3gdDU1RjjLbFXi4ZNePj6Je6iQgmQhdilrQFHVePUrM38JAodwUTE+1iR0k3UI17Vex93UQEC2YUVaYZN4/68DFHfnU28AwADog6AQnXS5+08yw5hzFNqOjBX/WKM1Qc7g66b1RhdO+uCJxHxZklTHHfNM6hvq52my0tTm/rT1Y7Xp9UmBXEbmZj67tQ3syr1BAOcc59GrvyzXOwPGwbzdcFFSwPnAjLobq5H5tnXSpG5xjsAWjKqcQzw/k3sM6kBeJZ9V1tVM2oMIr69DnteDoEMBVHTDFgLDnGcmC498OdEllw/clH9fu4/VePj9ZVe6p1+oxCRrUEUrSCcAwMxxzhF1OS4HN6utLW2XaGCsBsvBzRwLVGb0guR5Uw+uV24F14IgQDEKaZ4niGOYBSEbYiTKkCGhpWdzWU3Uq0bulo8FQ2b8ep1qqKTpl2AKgAhdp8cv15v7sXeD8JN3bALaZpR9wkYQNiGsA94Qvz549pa+woqi3WD7I2sRUO4WmC/O3+0Gbh7Z4d9Wi0aUwyb8drGq5AhsTIMriPQSVyOKT08fJlNdxdgAIBzzq5s2ziAit+NGvPZKswiS7YLC3NEatG2byBfYc+DAVhr3UcHQ2cXS1VzqVmW2hPytLdo2IUQwtp97pgJUCCm4L/6s6t8FYwaBO7tmTazUt9UWdU/hhQDCsjQen1ga9xF75+wnwM3fE92aZmlqtjE7ON+QS6qmtMuxRhPTUqG3NpVD79kvww+rEJ913XU6mdDKKqqOc9HxDaLyDlX/byxN74+o2/NRFpUk6Z04/D9rFodAJUtC0GB33hVvXtx8hvlpAxVAhG3JPSLcu+L7I1HAbGkFGru/xNgADqp33jajgeH+ENg1AR44oO//YyvyV8D/w8BirWMpYK6KwAAAABJRU5ErkJggg==",android.util.Base64.DEFAULT);
   c.drawBitmap(android.graphics.BitmapFactory.decodeByteArray(search_icon,0,search_icon.length),60,216,null);
   if(badAnchor || "city_badanchor".equals(scenario)){android.graphics.Paint p=new android.graphics.Paint();p.setColor(android.graphics.Color.RED);c.drawRect(330,116,574,162,p);}
  }
 }
}
