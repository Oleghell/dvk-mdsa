"""Write build-manifest.json beside the packaged EXE (CI only, no device access)."""
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mumu_version import VERSION, ENGINE_VERSION  # noqa: E402

# Honest readiness: True only for what a real MuMu #4 run has confirmed.
LIVE_VERIFIED = {
    'dialog_list_navigation_and_return': True,     # 0.4.5 device report
    'unread_only_dialog_reading': True,            # 0.4.6, confirmed by the user
    'guided_chain_question_and_contact_request': True,  # 0.4.11 device report
    'contact_received_and_telegram_notification': False,
    'start_inbox_chain_pass': False,
    'start_new_profiles_with_greeting': False,
    'city_rotation_and_online_filter_in_start': False,
    'read_tracked_dialog_recovery': False,
    'groq_live_replies': False,
    'openrouter_live_device_replies': False,
    'repeated_profile_batches': False,
    'dynamic_ai_reply_native_send': False,
    'chat_local_error_isolation': False,
    'contextual_contact_followup': False, 'identity_recheck_budget_recovery': False, 'history_read_budget_recovery': False, 'history_loading_local_deferral': False, 'contact_choice_clarification': False,
    'incoming_during_returned_send': False,
    'labelled_telegram_contact': False, 'voluntary_contact_during_pending': False,
    'returned_city_transition_verification': False, 'time_sliced_model_scan': False, 'unverified_greeting_local_isolation': False,
    'dialog_cached_model_scan': False, 'contact_profile_photo': False, 'api_key_failover': False,
}


def main(folder):
    folder = Path(folder)
    exe = folder / 'DvkAssistant.exe'
    config_hashes = {name: hashlib.sha256((folder / 'config' / name).read_bytes()).hexdigest()
                     for name in ('cities.json', 'greetings.json', 'groq-rules.txt')}
    manifest = dict(
        tool_version=VERSION,engine_version=ENGINE_VERSION,source_commit=os.environ.get('GITHUB_SHA'),
        sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
        device_scope='explicit-local-MuMu-port-list', auto_start=False, explicit_run_confirmation=False, explicit_start_click=True,
        per_message_confirmation=False, automatic_send=True, config_sha256=config_hashes,
        start_flow=['inbox-chain-pass', 'new-profiles-pass'],
        features=dict(parallel_mumu_workers=True, shared_peer_claims=True, atomic_cross_account_deduplication=True, legacy_mumu4_journal_preserved=True, duplicate_peer_verified_native_return=True, persistent_gadget_reuse=False, immutable_apk_validation_cache=True, adb_read_socket=True, apk_auto_install=False, city_count_limit=None, shared_core_manifest=True, model_scan_rows_per_frame=1, readonly_scan_budget_yields=12, telegram_statistics_commands=['/today','/yesterday','/week','/month','/city'], statistics_historical_backfill=False, inbox_chain_pass=True, new_profiles_pass=True, friends_limit='<50',
                      online_only_filter=True, random_city_from_config=True,
                      guided_open_chat=False, guided_reset=False, telegram_contact_only=False,
                      telegram_error_alerts=True, profile_interval_seconds=120, typing_words_per_minute=35,
                      default_dialog_interval_seconds=5, read_tracked_dialog_recovery=True,
                      groq_opt_in=True, groq_rules_file='config/groq-rules.txt',
                      openrouter_opt_in=True, openrouter_only_free=True,
                      openrouter_paid_fallback=False, provider_auto_switch=True, provider_order=['groq','openrouter'], city_read_budget_retries=4,
                      entered_key_test=True, independent_ai_key_save=True,
                      validated_dynamic_ai_send=True, chat_local_error_isolation=True,
                      unknown_send_auto_retry=False, api_key_pool_file='config/ai-keys.txt',
                      same_provider_key_failover=True, fixed_dialog_limit=None, dialog_paging=False, screen_scroll=False,
                      dialog_cached_model_scan=True, unloaded_server_archive_fetch=False,
                      bad_header_local_skip=True, identity_recheck_budget_recovery=True,
                      contextual_contact_followup_once=True, history_read_budget_attempts=4,
                      history_read_budget_retry_interval_seconds=0.5, history_read_budget_local_deferral=True,
                      history_loading_wait_seconds=15,
                      history_loading_peer_cooldown_seconds=60,
                      contact_choice_clarification_once=True, contextual_incoming_batch=True,
                      labelled_telegram_contact=True, voluntary_contact_during_pending=True,
                      returned_city_transition_verification=True, city_transition_max_overruns=5,
                      model_scan_slice_milliseconds=4000, model_scan_max_slice_rows=64,
                      unverified_greeting_local_isolation=True,
                      telegram_peer_excerpt_on_skip=True, contact_profile_photo=True,
                      contact_single_telegram_message=True,
                      telegram_test_message=True, clear_profile_history=True),
        files_sha256={str(f.relative_to(folder)).replace('\\','/'):hashlib.sha256(f.read_bytes()).hexdigest() for f in folder.rglob('*') if f.is_file() and f.suffix.lower() in ('.exe','.dll','.pyd','.zip')},
        multi_device_live_verified=False, live_verified=LIVE_VERIFIED,
        production_ready=all(LIVE_VERIFIED.values()))
    (folder / 'build-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                                encoding='utf-8')


if __name__ == '__main__':
    main(sys.argv[1])
