"""MoreLogin build identity, no inherited claims of MuMu live verification."""
import hashlib,json,os,sys
from pathlib import Path
from morelogin_version import VERSION, ENGINE_VERSION

def main(folder):
    folder=Path(folder)
    sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    result=dict(platform='MoreLogin',tool_version=VERSION,engine_version=ENGINE_VERSION,
        source_commit=os.environ.get('GITHUB_SHA'),production_ready=False,
        packaging='shared-onedir',
        runtime_sha256={x.relative_to(folder).as_posix():sha(x) for x in sorted((folder/'_internal').rglob('*')) if x.is_file()},
        exe_sha256={name:sha(folder/name) for name in ('DvkAssistant.exe','DvkCloudWorker.exe','DvkCloudInstaller.exe')},
        config_sha256={x.name:sha(x) for x in sorted((folder/'config').iterdir()) if x.is_file()},
        features=dict(city_count_limit=None, shared_core_manifest=True, model_scan_rows_per_frame=1, readonly_scan_budget_yields=12, telegram_statistics_commands=['/today','/yesterday','/week','/month','/city'], statistics_historical_backfill=False, explicit_cloud_ids=True,parallel_phone_processes=True,
            common_local_sqlite=True,shared_atomic_peer_claims=True,phone_isolated_journals=True,
            app_id_secret_key=True,windows_dpapi=True,ssh_host_key_pinning=True,
            auto_start=False,unknown_send_auto_retry=False,automatic_app_install=False,explicit_single_phone_installer=True,typed_delete_confirmation=True,apk_only_backup=True,read_only_installed_gadget_check=True,post_install_apk_hash_check=True,file_first_package_session=True,remote_apk_sha256_check=True,commit_auto_retry=False,
            compatible_gadget_bundle_required=True,stock_apk_supported=False,
            direct_adb_fallback=False,direct_adb_supported=True,direct_adb_code_via_argv=False,automatic_phone_power_on=False),
        live_verified=dict(cloud_api=False,cloud_installer=False,direct_adb_android15=False,ssh_android14=False,ssh_android15=False,
            gadget_android14=False,gadget_android15=False,parallel_cloud_phones=False,
            cloud_message_send=False,cloud_contact_photo_telegram=False))
    (folder/'build-manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=1),encoding='utf-8')
if __name__=='__main__':main(sys.argv[1])
