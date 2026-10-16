package com.dvk.city;
/** Catalog version city-v1. Index meanings never change in-place. */
public final class CityPolicy {
 private CityPolicy() {}
 private static final String[] CITIES = {"Нальчик","Таганрог","Нижнекамск","Благовещенск","Комсомольск-на-Амуре","Петрозаводск","Сыктывкар","Королёв","Братск","Шахты","Люберцы","Дзержинск","Ангарск","Старый Оскол","Орск","Псков","Бийск","Энгельс","Южно-Сахалинск","Прокопьевск","Балаково","Армавир","Северодвинск","Абакан","Петропавловск-Камчатский","Норильск","Рыбинск","Сызрань","Новочеркасск","Каменск-Уральский"};
 public static final String CATALOG = "city-v1";
 public static int size(){return CITIES.length;}
 public static boolean validIndex(int index){return index>=0 && index<CITIES.length;}
 public static String city(int index){if(!validIndex(index))throw new IllegalArgumentException();return CITIES[index];}
 // previous=-1 is an EMPTY query; all other previous values are catalog indices.
 public static boolean matchesPrevious(String text,int previous){
  return previous==-1 ? "".equals(text) : validIndex(previous) && city(previous).equals(text);
 }
 public static boolean validArgs(String op,String expected,int x,int y){
  if(expected==null || !expected.matches("[0-9a-f]{64}"))return false;
  if("inspect_city".equals(op))return x==0 && y==0;
  return "city_input".equals(op) && validIndex(x) && y>=0 && y<=CITIES.length;
 }
}
