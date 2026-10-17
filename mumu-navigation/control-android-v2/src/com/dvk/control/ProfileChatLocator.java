package com.dvk.control;
import java.util.ArrayList;
/** Pure Java icon/panel locator. No device input, fixed tap point or screen mask. */
public final class ProfileChatLocator {
 public static final class Box {
  public final int left,top,right,bottom;
  public Box(int l,int t,int r,int b){left=l;top=t;right=r;bottom=b;}
  public int width(){return right-left;} public int height(){return bottom-top;}
 }
 private static final int[] CHAT={2016,8184,16380,32766,65535,65535,65535,65535,65535,65535,32766,16380,8184,2040,56,28};
 private static final int[] CLOSE={49155,61455,30750,31806,15996,7800,4080,960,960,4080,7800,15996,31806,30750,61455,49155};
 private static final int[] GIFT={7992,12620,12484,6284,65535,65407,65407,65407,32639,0,16255,8063,1919,383,127,62};
 private static int color(int p){int r=p>>16&255,g=p>>8&255,b=p&255;
  if(r<100 && g>100 && b>120 && g>r+50 && b>r+50)return 1;
  if(r>160 && g<150 && b>70 && r>g+50)return 2;
  return 0;
 }
 private static double score(int[] px,int w,Box b,int kind,int[] shape){
  int intersection=0,union=0;
  for(int y=0;y<16;y++)for(int x=0;x<16;x++){
   int sx=b.left+Math.min(b.width()-1,(2*x+1)*b.width()/32),sy=b.top+Math.min(b.height()-1,(2*y+1)*b.height()/32);
   boolean actual=color(px[sy*w+sx])==kind,expected=(shape[y]&(1<<x))!=0;
   if(actual && expected)intersection++;if(actual || expected)union++;
  }
  return union==0?0:(double)intersection/union;
 }
 public static Box locate(int[] pixels,int width,int height){
  if(width<320 || width>2160 || height<600 || height>3840 || height<=width || pixels.length!=width*height)return null;
  // Analyze a width-normalized raster; center/bounds are mapped back to the
  // actual screenshot. Different aspect ratios retain their actual height.
  int w=Math.min(450,width),h=(int)((long)height*w/width),cut=h*3/4;
  int[] px=new int[w*h];for(int y=0;y<h;y++)for(int x=0;x<w;x++)px[y*w+x]=pixels[(int)((long)y*height/h)*width+(int)((long)x*width/w)];
  byte[] seen=new byte[w*(h-cut)];int[] queue=new int[seen.length];
  ArrayList<Box> chats=new ArrayList<>(),closes=new ArrayList<>(),gifts=new ArrayList<>();
  for(int y=cut;y<h;y++)for(int x=0;x<w;x++){
   int index=(y-cut)*w+x,kind=color(px[y*w+x]);if(kind==0 || seen[index]!=0)continue;
   int head=0,tail=0,l=x,t=y,r=x+1,b=y+1;seen[index]=1;queue[tail++]=index;
   while(head<tail){int q=queue[head++],cx=q%w,cy=q/w+cut;
    l=Math.min(l,cx);t=Math.min(t,cy);r=Math.max(r,cx+1);b=Math.max(b,cy+1);
    // Join nearby pieces of ONE glyph (gift ribbons/body, X strokes), not rows.
    for(int dy=-3;dy<=3;dy++)for(int dx=-3;dx<=3;dx++){
     int nx=cx+dx,ny=cy+dy;if(nx<0 || nx>=w || ny<cut || ny>=h)continue;
     int ni=(ny-cut)*w+nx;if(seen[ni]==0 && color(px[ny*w+nx])==kind){seen[ni]=1;queue[tail++]=ni;}
    }
   }
   Box q=new Box(l,t,r,b);if(q.width()<6 || q.height()<6 || q.width()>60 || q.height()>60)continue;
   if(kind==1 && score(px,w,q,1,CHAT)>=0.80)chats.add(q);
   if(kind==1 && score(px,w,q,1,CLOSE)>=0.70)closes.add(q);
   if(kind==2 && score(px,w,q,2,GIFT)>=0.65)gifts.add(q);
  }
  Box selected=null;
  for(Box chat:chats){int row=(chat.top+chat.bottom)/2;boolean close=false,gift=false;
   for(Box c:closes)if(c.right<chat.left && chat.left-c.right>w/12 && chat.left-c.right<w/2 && Math.abs((c.top+c.bottom)/2-row)<Math.max(5,h/50))close=true;
   for(Box g:gifts)if(g.left>chat.right && g.left-chat.right>w/12 && g.left-chat.right<w/2 && Math.abs((g.top+g.bottom)/2-row)<Math.max(5,h/50))gift=true;
   if(close && gift){if(selected!=null)return null;selected=chat;}
  }
  if(selected==null)return null;
  return new Box(selected.left*width/w,selected.top*height/h,(selected.right*width+w-1)/w,(selected.bottom*height+h-1)/h);
 }
}
