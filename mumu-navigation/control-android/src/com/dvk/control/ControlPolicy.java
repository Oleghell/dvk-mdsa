package com.dvk.control;
public final class ControlPolicy {
 public static boolean point(int x,int y){return x>=0 && x<900 && y>=48 && y<1600;}
 public static boolean key(int key){return key==4 || key==66 || key==67 || key==61 || key>=19 && key<=23 || key==112 || key==122 || key==123;}
 public static boolean plain(String s){if(s==null || s.codePointCount(0,s.length())>128)return false;for(int p=0;p<s.length();){int cp=s.codePointAt(p);if(Character.isISOControl(cp) || cp==0x2028 || cp==0x2029 || cp>=0xd800 && cp<=0xdfff)return false;p+=Character.charCount(cp);}return true;}
}
