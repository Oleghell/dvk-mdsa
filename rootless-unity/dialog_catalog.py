"""Offline navigation definitions ONLY. A catalogue is not a live navigator."""
import json
from pathlib import Path
from assistant_store import data_directory
from friends_catalog import inspect_bundle
from search_catalog import collect as collect_definitions, CatalogCancelled, MAX_REPORT_BYTES

ROOTS = (('DV.Messages.dll', 'DV.Messages', 'ChatsViewController'),
         ('DV.Messages.dll', 'DV.Messages', 'MessagesViewController'),
         ('DV.Messages.dll', 'DV.Routers.Messages', 'MessagesRouter'))
WORDS = ('chat', 'message', 'conversation', 'tabbar', 'tabcontroller', 'mainmenu', 'mainview', 'navigation', 'unread')
MEMBERS = WORDS + ('select', 'item', 'count', 'delegate', 'show', 'open', 'back', 'close', 'return', 'ready', 'loaded', 'user', 'current', 'search')


def collect(metadata, cancelled=lambda: False):
    # Include real route owners found by their METHOD definitions, not guessed
    # class names. This catches application/menu controllers outside Messages.
    extra = []
    hints = ('onmessages', 'onchat', 'showchats', 'showmessages', 'selecttab', 'get_messagesrouter', 'get_tabbar')
    for t in metadata.types:
        if cancelled():
            raise CatalogCancelled()
        if not t['image'].startswith('DV') or t['name'].startswith('<'):
            continue
        methods = metadata.methods[t['method_start']:t['method_start'] + t['method_count']]
        key = (t['image'], t['namespace'], t['name'])
        if key not in ROOTS and any(any(h in m['name'].lower() for h in hints) for m in methods):
            extra.append(key)
    extra = sorted(set(extra))
    result = collect_definitions(metadata, cancelled, root_specs=ROOTS + tuple(extra[:48]), topic_words=WORDS,
                               member_words=MEMBERS, priority_image='DV.Messages.dll',
                               purpose='private-dialog-list-navigation-definitions-only')
    if len(extra) > 48:
        result['truncated'] = True
    return result


def write_report(folder, cancelled=lambda: False, *, destination=None, expected_hashes=None):
    try:
        report = inspect_bundle(folder, cancelled, expected_hashes,
                                collector=lambda metadata: collect(metadata, cancelled))
    except CatalogCancelled:
        report = dict(status='catalog-stopped', reason='cancelled', catalog=None,
                      ui_actions_attempted=False, messages_sent=0, method_values_read=False)
    if cancelled():
        report.update(status='catalog-stopped', reason='cancelled', catalog=None)
    report.update(mode='offline-dialog-navigation-definitions', adb_used=False,
                  emulator_contacted=False, chat_content_read=False, gadget_config_read=False,
                  personal_data_exported=False, live_cycle_available=False)
    text = json.dumps(report, ensure_ascii=False, separators=(',', ':'))
    if len(text.encode('utf-8')) > MAX_REPORT_BYTES:
        report.update(status='catalog-stopped', reason='report-size-limit', catalog=None)
        text = json.dumps(report, ensure_ascii=False, separators=(',', ':'))
    directory = data_directory() if destination is None else Path(destination)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / 'messages-navigation-definitions.json'
    temporary = target.with_suffix('.tmp')
    try:
        temporary.write_text(text, encoding='utf-8')
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return report, target
