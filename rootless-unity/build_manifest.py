"""Write build-manifest.json beside the packaged EXE (CI only, no device access)."""
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from version import VERSION  # noqa: E402

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
    'dialog_cached_model_scan': False, 'contact_profile_photo': False, 'api_key_failover': False,
}


def main(folder):
    folder = Path(folder)
    exe = folder / 'DvkAssistant.exe'
    config_hashes = {name: hashlib.sha256((folder / 'config' / name).read_bytes()).hexdigest()
                     for name in ('cities.json', 'greetings.json', 'groq-rules.txt')}
    manifest = dict(
        tool_version=VERSION, source_commit=os.environ.get('GITHUB_SHA'),
        sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
        device_scope='MuMu-4-only', auto_start=False, explicit_run_confirmation=False, explicit_start_click=True,
        per_message_confirmation=False, automatic_send=True, config_sha256=config_hashes,
        start_flow=['inbox-chain-pass', 'new-profiles-pass'],
        features=dict(inbox_chain_pass=True, new_profiles_pass=True, friends_limit='<50',
                      online_only_filter=True, random_city_from_config=True,
                      guided_open_chat=False, guided_reset=False, telegram_contact_only=False,
                      telegram_error_alerts=True, profile_interval_seconds=300, typing_words_per_minute=35,
                      default_dialog_interval_seconds=5, read_tracked_dialog_recovery=True,
                      groq_opt_in=True, groq_rules_file='config/groq-rules.txt',
                      openrouter_opt_in=True, openrouter_only_free=True,
                      openrouter_paid_fallback=False, provider_auto_switch=False,
                      entered_key_test=True, independent_ai_key_save=True,
                      validated_dynamic_ai_send=True, chat_local_error_isolation=True,
                      unknown_send_auto_retry=False, api_key_pool_file='config/ai-keys.txt',
                      same_provider_key_failover=True, fixed_dialog_limit=None, dialog_paging=False, screen_scroll=False,
                      dialog_cached_model_scan=True, unloaded_server_archive_fetch=False,
                      bad_header_local_skip=True,
                      telegram_peer_excerpt_on_skip=True, contact_profile_photo=True,
                      contact_single_telegram_message=True,
                      telegram_test_message=True, clear_profile_history=True),
        live_verified=LIVE_VERIFIED,
        production_ready=all(LIVE_VERIFIED.values()))
    (folder / 'build-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                                encoding='utf-8')


if __name__ == '__main__':
    main(sys.argv[1])
