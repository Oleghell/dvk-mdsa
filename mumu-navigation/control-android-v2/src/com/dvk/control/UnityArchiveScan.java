package com.dvk.control;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/** Static ZIP-directory inspection only. Never extract, load or execute code. */
public final class UnityArchiveScan {
 public static final int MAX_ARCHIVES=33,MAX_ENTRIES=150000,MAX_MARKERS=128;
 public static final String METADATA="assets/bin/Data/Managed/Metadata/global-metadata.dat";
 public static final String ASSEMBLY="assets/bin/Data/Managed/Assembly-CSharp.dll";
 private static final Pattern LIB=Pattern.compile("lib/([a-zA-Z0-9_-]{1,32})/(libunity\\.so|libil2cpp\\.so|libmono\\.so|libmonobdwgc-2\\.0\\.so|libmonosgen-2\\.0\\.so|libmono-2\\.0-bdwgc\\.so)");
 public static final class Marker {
  public final int archive;public final String kind,abi;
  Marker(int archive,String kind,String abi){this.archive=archive;this.kind=kind;this.abi=abi;}
 }
 public static final class Archive {
  public final int index;public String status="not_scanned";public int entries=0;
  Archive(int index){this.index=index;}
 }
 public static final class Report {
  public boolean complete=true;public int archiveCount,entries=0;
  public final ArrayList<Marker> markers=new ArrayList<>();public final ArrayList<Archive> archives=new ArrayList<>();
 }
 public static boolean knownLibrary(String name){return LIB.matcher(name).matches();}
 private static Marker marker(int index,String name){
  Matcher match=LIB.matcher(name);
  if(match.matches()){
   String lib=match.group(2);String kind="libunity.so".equals(lib)?"unity_library":"libil2cpp.so".equals(lib)?"il2cpp_library":"mono_library";
   return new Marker(index,kind,match.group(1));
  }
  if(METADATA.equals(name))return new Marker(index,"il2cpp_metadata","");
  if(ASSEMBLY.equals(name))return new Marker(index,"managed_assembly","");
  return null;
 }
 public static Report scan(List<File> paths){
  Report r=new Report();r.archiveCount=paths.size();Set<String> seen=new HashSet<>();Set<String> evidence=new HashSet<>();
  if(paths.isEmpty()||paths.size()>MAX_ARCHIVES)r.complete=false;
  long deadline=System.nanoTime()+4000000000L;
  for(int i=0;i<Math.min(paths.size(),MAX_ARCHIVES);i++){
   Archive a=new Archive(i);r.archives.add(a);File path=paths.get(i);
   try{
    if(path==null||!path.isAbsolute()||!path.isFile()||!seen.add(path.getCanonicalPath())){a.status="unavailable";r.complete=false;continue;}
    try(ZipFile zip=new ZipFile(path)){
     a.status="scanned";Set<String> archiveMarkers=new HashSet<>();Enumeration<? extends ZipEntry> entries=zip.entries();
     while(entries.hasMoreElements()){
      if(r.entries>=MAX_ENTRIES||System.nanoTime()>deadline){a.status="limit_reached";r.complete=false;break;}
      ZipEntry entry=entries.nextElement();r.entries++;a.entries++;
      if(entry.isDirectory())continue;String name=entry.getName();
      if(name.length()>512){r.complete=false;continue;}
      Marker marker=marker(i,name);if(marker==null)continue;
      if(!archiveMarkers.add(name)){r.complete=false;continue;}
      if(!evidence.add(i+":"+marker.kind+":"+marker.abi))continue;
      if(r.markers.size()>=MAX_MARKERS){a.status="limit_reached";r.complete=false;break;}
      r.markers.add(marker);
     }
    }
   }catch(IOException|SecurityException e){a.status="unreadable";r.complete=false;}
  }
  return r;
 }
 private UnityArchiveScan(){}
}
