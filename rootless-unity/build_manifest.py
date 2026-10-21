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
}


def main(folder):
    folder = Path(folder)
    exe = folder / 'DvkAssistant.exe'
    config_hashes = {name: hashlib.sha256((folder / 'config' / name).read_bytes()).hexdigest()
                     for name in ('cities.json', 'greetings.json', 'groq-rules.txt')}
    manifest = dict(
        tool_version=VERSION, source_commit=os.environ.get('GITHUB_SHA'),
        sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
        device_scope='MuMu-4-only', auto_start=False, explicit_run_confirmation=True,
        per_message_confirmation=False, automatic_send=True, config_sha256=config_hashes,
        start_flow=['inbox-chain-pass', 'new-profiles-pass'],
        features=dict(inbox_chain_pass=True, new_profiles_pass=True, friends_limit='<50',
                      online_only_filter=True, random_city_from_config=True,
                      guided_open_chat=False, guided_reset=False, telegram_contact_only=False,
                      telegram_error_alerts=True, profile_interval_seconds=120,
                      default_dialog_interval_seconds=30, read_tracked_dialog_recovery=True,
                      groq_opt_in=True, groq_rules_file='config/groq-rules.txt',
                      openrouter_opt_in=True, openrouter_only_free=True,
                      openrouter_paid_fallback=False, provider_auto_switch=False,
                      entered_key_test=True, independent_ai_key_save=True,
                      telegram_test_message=True, clear_profile_history=True),
        live_verified=LIVE_VERIFIED,
        production_ready=all(LIVE_VERIFIED.values()))
    (folder / 'build-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                                encoding='utf-8')


if __name__ == '__main__':
    main(sys.argv[1])
