package com.dvk.control;

import android.content.Context;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.os.Build;
import java.io.File;
import java.util.ArrayList;
import org.json.JSONArray;
import org.json.JSONObject;

/** Fixed-package, read-only metadata. No user data, screenshots, root or shell. */
public final class UnityDiagnostics {
 private static final String PKG="drug.vokrug";
 private static String safeVersion(String s){
  if(s==null||s.length()>128)return "";
  for(int i=0;i<s.length();i++)if(Character.isISOControl(s.charAt(i)))return "";
  return s;
 }
 public static JSONObject inspect(Context context)throws Exception{
  PackageInfo pkg=context.getPackageManager().getPackageInfo(PKG,0);
  ApplicationInfo app=context.getPackageManager().getApplicationInfo(PKG,0);
  if(!PKG.equals(pkg.packageName)||!PKG.equals(app.packageName))throw new Exception();
  ArrayList<File> paths=new ArrayList<>();paths.add(app.sourceDir==null?null:new File(app.sourceDir));
  String[] splits=app.splitSourceDirs;
  // PackageManager alone supplies paths; callers can never choose files.
  boolean pathLimit=splits!=null&&splits.length>32;
  if(splits!=null)for(int i=0;i<Math.min(32,splits.length);i++)paths.add(splits[i]==null?null:new File(splits[i]));
  UnityArchiveScan.Report scan=UnityArchiveScan.scan(paths);if(pathLimit)scan.complete=false;
  JSONArray markers=new JSONArray(),archives=new JSONArray(),deviceAbis=new JSONArray();
  for(UnityArchiveScan.Marker m:scan.markers)markers.put(new JSONObject().put("archive",m.archive).put("kind",m.kind).put("abi",m.abi));
  for(UnityArchiveScan.Archive a:scan.archives)archives.put(new JSONObject().put("index",a.index).put("role",a.index==0?"base":"split").put("status",a.status).put("entries_scanned",a.entries));
  for(String abi:Build.SUPPORTED_ABIS)if(abi.matches("[a-zA-Z0-9_-]{1,32}"))deviceAbis.put(abi);
  long version=Build.VERSION.SDK_INT>=28?pkg.getLongVersionCode():pkg.versionCode;
  if(version<0)throw new Exception();
  return new JSONObject().put("unity_diagnostics_version",1).put("package",PKG).put("version_name",safeVersion(pkg.versionName)).put("version_code",Long.toString(version))
   .put("debuggable",(app.flags&ApplicationInfo.FLAG_DEBUGGABLE)!=0).put("test_only",(app.flags&ApplicationInfo.FLAG_TEST_ONLY)!=0)
   .put("device_supported_abis",deviceAbis).put("archive_count",1+(splits==null?0:splits.length)).put("archives",archives).put("entries_scanned",scan.entries).put("markers",markers).put("complete",scan.complete)
   .put("classification_scope","installed_apk_entries_only").put("runtime_objects_access","not_tested").put("sdk_integration_status","not_assessed")
   .put("images_captured",0).put("actions_attempted",0).put("root_attempted",false).put("apk_modified",false).put("private_data_read",false);
 }
 private UnityDiagnostics(){}
}
