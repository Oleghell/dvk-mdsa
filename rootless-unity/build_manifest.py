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
    'whatsapp_spaced_choice_and_reverse_availability': False,
    'manual_ban_silent_queue_exclusion': False,
    'installation_city_and_journal_scopes': False, 'sample_wrong_screen_read_retry': False,
    'navigation_targets_data_bootstrap': False, 'navigation_unloaded_reconnect': False,
    'inbox_targets_postgres_readonly_select': False,
    'hotpath_readonly_preparation': False, 'adb_preflight_process_reduction': False,
    'profile_host_finalization': False, 'city_precommit_diagnostic': False,
    'profile_history_data_bootstrap': False, 'pending_city_early_root_wait': False,
    'idle_cloud_connection_recovery': False, 'readonly_chat_transport_reconnect': False,
    'automatic_pending_city_recovery': False,
    'global_city_allocation': False, 'global_initial_greeting_dedup': False, 'pause_transient_reconnect': False,
    'supabase_windows_cutover': False,
    'profile_disabled_input_local_skip': False, 'post_contact_two_reply_limit': False, 'indifferent_choice_fixed_number_request': False,
    'one_hour_reply_window': False, 'new_profiles_start': False, 'readonly_list_change_retry': False,
    'max_choice_fixed_clarification': False, 'fresh_same_boot_reconnect': False,
    'extended_stay_here_terminal_skip': False, 'invalid_message_scalar_isolation': False,
    'independent_contact_receipts': False, 'adb_forward_recovery': False, 'contact_review_reconciliation': False,
    'port_local_safe_supervision': False, 'bare_stay_here_terminal_skip': False,
    'native_latest_legacy_recovery': False, 'isolated_reply_journals': False, 'immediate_exit_after_observed_send': False,
    'compact_main_window': False, 'profile_search_budget_recovery': False, 'continuous_mumu_work': False, 'immediate_first_greeting': False, 'four_row_cached_scan': False,
    'dialog_list_navigation_and_return': True,     # 0.4.5 device report
    'unread_only_dialog_reading': True,            # 0.4.6, confirmed by the user
    'guided_chain_question_and_contact_request': True,  # 0.4.11 device report
    'contact_received_and_telegram_notification': False,
    'start_inbox_chain_pass': False,
    'start_new_profiles_with_greeting': False,
    'city_rotation_and_online_filter_in_start': False,
    'read_tracked_dialog_recovery': False,
    'groq_live_replies': False, 'gemini_live_device_replies': False, 'zai_live_device_replies': False,
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
        features=dict(whatsapp_spaced_choice=True, whatsapp_reverse_availability=True, contact_terminal_auto_reset=False, manual_ban_queue_exclusion=True, manual_ban_exit_notifications=False, manual_ban_mid_open_verified_back=True, manual_ban_cached_permissions=False, manual_silence_preserves_terminal_provenance=True, installation_loader_imports_engine=False, sqlite_internal_index_name_parameterized=True, postgres_identifier_limit=63, installation_id_persistent=True, installation_id_machine_bound=True,
                      installation_id_in_exported_cloud_config=False, city_owner_installation_and_port=True,
                      journals_installation_and_port=True, conservative_legacy_journal_copy=True,
                      copied_unknown_send_replayed=False, account_owner_persistent=True,
                      account_owner_automatic_transfer=False, copied_outbox_requires_account_owner=True,
                      global_greeting_dedup_across_installations=True, telegram_installation_label=True,
                      sample_wrong_screen_same_bound_read_retries=1, sample_wrong_screen_send_retry=False,
                      navigation_targets_compiled_into_script=False, navigation_targets_one_shot_rpc=True, navigation_script_create_retries=2, navigation_retry_after_script_load=False, inbox_targets_select_subquery=True, cloud_readonly_guard_relaxed=False, postgres_smoke_covers_full_inbox_targets=True, store_successful_schema_once=True, schema_cache_contains_rows=False, inbox_readonly_preparation=True, reply_exclusions_one_snapshot_per_pass=True, adb_version_binary_fingerprint_cache=True, adb_connected_preflight_fresh_probe=True, adb_recovery_cli_connect_preserved=True, profile_host_finalize_rpc_guard_seconds=60, profile_authorization_drain_timeout_seconds=30, profile_authorization_original_failure=True, profile_prechecks_readonly=True, profile_host_failure_retains_native_result=True, profile_no_send_requires_validated_drained_result=True, city_native_diagnostic_before_commit=True, city_claim_conflict_overwrite=False, profile_history_compiled_into_script=False, profile_history_data_bootstrap=True, profile_history_rpc_max_ids=10000, profile_root_requires_history=True, profile_setup_max_attempts=6, pending_city_early_root_wait=True, closed_city_recovery_root_diagnostic=True, profile_history_readonly_snapshot=True, cloud_idle_checkout_verification_seconds=10, cloud_failed_sessions_reused=False, readonly_chat_transport_retries=2, profile_preexecution_forward_refresh=True, profile_history_closed_database_diagnostic=True, automatic_pending_city_recovery=True, city_state_readonly_samples=2, city_recovery_no_ui_actions=True, city_recovery_preserves_send_journals=True, early_wrong_screen_same_bound_read_retries=1, current_read_failure_safe_repair=True, city_native_used_scoped=True, city_inputs_preflight_before_claim=True, global_city_allocation=True, city_reservation_before_native=True, city_pending_claim_expiry=False, global_initial_greeting_dedup=True, greeting_claim_is_terminal_ban=False, pause_transient_readonly_reconnect=True, stop_while_paused_is_cancelled=True, postgres_batched_inbox_targets=True, postgres_seen_ids_chat_batch=128, postgres_seen_ids_overflow_signal=129, postgres_all_store_constructor_startup_scope=True, postgres_preparation_diagnostics=True, postgres_set_based_contact_backfill=True, postgres_single_startup_store=True, postgres_bootstrap_lock_timeout_ms=60000, postgres_closed_startup_diagnostics=True, postgres_primary_opt_in=True, postgres_session_pooler_port=5432, postgres_tls_verify_full=True, postgres_local_fallback=False, postgres_private_schema=True, postgres_windows_dpapi=True, postgres_latest_local_cutover=True, postgres_verified_import=True, postgres_active_overwrite=False, profile_back_after_fresh_native_profile=True, profile_post_back_read_retries=2, capture_setup_no_send_proof=True, unsent_snapshot_replan_limit=2, retained_send_failure_diagnostics=True, closed_city_failure_diagnostics=True, recent_circular_position_hint=True, recent_hint_persistent=False, recent_hint_cached_identity=False, profile_photo_pre_tap_local_deferral=True, saved_contact_receipt_only_resume=True, photo_failure_stage_diagnostics=True, adaptive_short_history_batches=True, history_batch_max_messages=4, history_frame_reserve_ms=30, history_getter_cost_factor=2, chat_stage_timings=True, separate_ai_wait_status=True, sample_message_scalar_read_recovery=True, global_ban_notice_actual_reason=True, unknown_send_notice_journal_detail=True, bound_read_initial_delay_ms=0, bound_read_stability_interval_ms=1000, bound_read_complete_samples=2, indifferent_choice_fixed_number_request=True, profile_disabled_input_local_skip=True, post_contact_additional_outgoing_limit=2, post_contact_budget_persistent=True, reply_window_seconds=None, requested_incoming_reply_window_seconds=3600, incoming_message_time_verified=False, reply_age_basis="not-enforced-without-verified-incoming-sent-at", reply_age_unverified="no-age-exclusion", new_start_existing_dialogs="persistently-excluded-port-account", readonly_scan_change_retries=2, port_local_safe_supervision=True, recovery_skip_before_back=True, recovery_unknown_send_replay=False, recovery_unknown_back_replay=False, recovery_unverified_screen_actions=False, bare_stay_here_terminal_skip=True, native_latest_legacy_recovery=True, isolated_reply_journals=True, redundant_post_send_read=False, legacy_recovery_basis='journal-greeting-exact-question-native-latest-peer', parallel_mumu_workers=True, shared_peer_claims=True, atomic_cross_account_deduplication=True, legacy_mumu4_journal_preserved=True, duplicate_peer_verified_native_return=True, persistent_gadget_reuse=False, immutable_apk_validation_cache=True, adb_read_socket=True, apk_auto_install=False, city_count_limit=None, shared_core_manifest=True, model_scan_rows_per_frame=4, readonly_scan_budget_yields=12, telegram_statistics_commands=['/today','/yesterday','/week','/month','/city'], telegram_manual_deny_command='/num', manual_deny_private_chat_only=True, statistics_historical_backfill=False, inbox_chain_pass=True, new_profiles_pass=True, friends_limit='<50',
                      online_only_filter=True, random_city_from_config=True,
                      guided_open_chat=False, guided_reset=False, telegram_contact_only=False,
                      telegram_error_alerts=True, profile_interval_seconds=120, typing_words_per_minute_default=35, typing_speed_configurable=True, typing_words_per_minute_range=[1,300], immediate_first_greeting=True, typing_countdown=True, compact_main_window=[600,350], profile_search_budget_recovery=True, profile_read_poll_ms=100, continuous_mumu_work=True, inbox_outgoing_poll_delay_seconds=0, early_profile_rotation=True,
                      default_dialog_interval_seconds=5, read_tracked_dialog_recovery=True,
                      groq_opt_in=True, groq_rules_file='config/groq-rules.txt',
                      openrouter_opt_in=True, openrouter_only_free=True, gemini_opt_in=True, gemini_developer_api=True,
                      gemini_hidden_fallback=False, all_configured_provider_failover=True, gemini_quota_and_billing_external=True, zai_opt_in=True, zai_only_flash=True, zai_paid_fallback=False,
                      provider_selection_strategies={p: __import__('mumu_ai').strategy(p) for p in ('groq','openrouter','gemini','zai')},
                      openrouter_paid_fallback=False, history_chunk_loading_recovery=True, ai_stage_repair_attempts=1, ai_validation_reason_diagnostics=True, navigation_entry_read_budget_retries=3, navigation_observation_budget_retries=3, navigation_stable_return_frames=2, navigation_search_reentry=True, telegram_device_numbers=True, sample_read_budget_recovery=True, history_frame_chunk_messages=4, history_max_messages=128, history_max_text_characters=8192, history_max_total_characters=65536, reply_receipts=True, post_send_recheck=True, profile_batch_without_inbox_interleaving=True, safe_greeting_after_provider_exhaustion=True, compact_mumu_window=True, city_query_split_frames=True, history_recheck_budget_recovery=True, startup_bound_chat_return=True, ai_retry_after=True, exit_photo_before_back=True, exit_photo_single_caption=True, oversized_history_local_deferral=True, ai_failure_per_key_diagnostics=True, ai_retry_cooldown_seconds=60, groq_max_completion_tokens=1024, provider_auto_switch=True, provider_order=['selected-first','groq','openrouter','gemini','zai'], city_read_budget_retries=4,
                      independent_key_check_tab=True, corrupt_ready_draft_chat_isolation=True, entered_key_test=True, independent_ai_key_save=True,
                      validated_dynamic_ai_send=True, chat_local_error_isolation=True,
                      unknown_send_auto_retry=False, api_key_pool_file='config/ai-keys.txt',
                      same_provider_key_failover=True, fixed_dialog_limit=None, dialog_paging=False, screen_scroll=False,
                      dialog_cached_model_scan=True, unloaded_server_archive_fetch=False,
                      bad_header_local_skip=True, identity_recheck_budget_recovery=True,
                      contextual_contact_followup_once=False, observed_followup_recycling=True, history_read_budget_attempts=4,
                      history_read_budget_retry_interval_seconds=0.5, history_read_budget_local_deferral=True,
                      history_loading_wait_seconds=15,
                      history_loading_peer_cooldown_seconds=60,
                      contact_choice_clarification_once=True, contextual_incoming_batch=True,
                      labelled_telegram_contact=True, voluntary_contact_during_pending=True,
                      returned_city_transition_verification=True, city_transition_max_overruns=6,
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
