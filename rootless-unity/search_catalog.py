"""Bounded offline search/online/location definitions, never application values.

Reads only the pinned APKs already used by the working assistant. No ADB,
Gadget config/token, process memory, images, literals, chat data or UI handlers.
The resulting catalogue is evidence for implementing bindings, NOT permission
or proof that a city or online filter has been applied.
"""
import json
from pathlib import Path
import struct

from assistant_store import data_directory
from chat_catalog import parameter_layout
from friends_catalog import definition_fields, inspect_bundle as inspect_definitions, label

ROOTS = (('DV.Search.dll', 'DV.Search', 'SearchTabController'),
         ('DV.Search.dll', 'DV.Search', 'SearchSettingsCardController'))
WORDS = ('search', 'filter', 'online', 'location', 'city', 'cities', 'region', 'country', 'geo')
MEMBER_WORDS = WORDS + ('settings', 'parameter', 'option', 'delegate', 'select', 'value',
                        'item', 'count', 'ready', 'loaded', 'actual', 'confirm', 'apply', 'close', 'cancel')
MAX_TYPES = 192
MAX_DEPTH = 4
MAX_METHODS = 128
MAX_FIELDS = 64
MAX_PARAMETERS = 24
MAX_TOTAL_METHODS = 4096
MAX_TOTAL_FIELDS = 1536
MAX_TOTAL_PARAMETERS = 6144
MAX_REPORT_BYTES = 4 * 1024 * 1024


class CatalogCancelled(Exception):
    pass


def collect(metadata, cancelled=lambda: False, *, root_specs=None, topic_words=None,
            member_words=None, priority_image='DV.Search.dll', purpose='search-online-and-city-definitions-only'):
    root_specs = ROOTS if root_specs is None else root_specs
    topic_words = WORDS if topic_words is None else topic_words
    member_words = MEMBER_WORDS if member_words is None else member_words
    def checkpoint():
        if cancelled():
            raise CatalogCancelled()
    checkpoint()
    parameter_offset, _ = parameter_layout(metadata)
    fields_by_owner = {}
    for owner, name, type_index in definition_fields(metadata):
        checkpoint()
        fields_by_owner.setdefault(owner, []).append((name, type_index))
    byval = {}
    for index, t in enumerate(metadata.types):
        checkpoint()
        if t['byval_type_index'] >= 0:
            byval.setdefault(t['byval_type_index'], []).append(index)

    def identity(t):
        if (not label(t['image']) or not label(t['name'])
                or (t['namespace'] and not label(t['namespace']))):
            return None
        return dict(image=t['image'], namespace=t['namespace'], type=t['name'])

    def supported(t):
        return (identity(t) is not None and
                (t['image'].startswith('DV') and t['image'].endswith('.dll')
                 or t['image'] == 'Core.dll' and t['namespace'].startswith(('UIKit', 'DataKit'))))

    def resolve(type_index):
        result = dict(type_index=type_index)
        matches = byval.get(type_index, [])
        if len(matches) != 1:
            return dict(result, status='unresolved' if not matches else 'ambiguous')
        target = identity(metadata.types[matches[0]])
        return (dict(result, status='resolved', target=target) if target
                else dict(result, status='unsupported-name'))

    queue, queued = [], set()
    truncated = False
    def enqueue(owner, depth, role):
        nonlocal truncated
        if owner in queued or not supported(metadata.types[owner]):
            return
        if len(queued) >= MAX_TYPES or depth > MAX_DEPTH:
            truncated = True
            return
        queued.add(owner)
        queue.append((owner, depth, role))

    def follow(type_index, depth):
        matches = byval.get(type_index, [])
        if len(matches) == 1:
            enqueue(matches[0], depth, 'linked-definition')

    roots = []
    for image, namespace, name in root_specs:
        checkpoint()
        matches = [i for i, t in enumerate(metadata.types)
                   if (t['image'], t['namespace'], t['name']) == (image, namespace, name)]
        roots.append(dict(image=image, namespace=namespace, type=name,
                          status='found' if len(matches) == 1 else 'missing' if not matches else 'ambiguous'))
        if len(matches) == 1:
            enqueue(matches[0], 0, 'known-controller')
    # Select definitions, never object instances. Search-owned nested delegates
    # and geo providers are included, even if an offline generic edge is unresolved.
    candidates = []
    for index, t in enumerate(metadata.types):
        checkpoint()
        if not supported(t) or t['name'].startswith('<'):
            continue
        owner = (t['namespace'] + '.' + t['name']).lower()
        if t['image'] == priority_image:
            priority = 0
        elif t['image'].startswith('DV') and any(word in owner for word in topic_words):
            priority = 1
        else:
            continue
        candidates.append((priority, t['image'], t['namespace'], t['name'], index))
    candidates.sort()
    for *_, index in candidates:
        enqueue(index, 0, 'topic-definition')

    nodes = []
    totals = dict(methods=0, fields=0, parameters=0)
    for owner, depth, role in queue:
        checkpoint()
        t = metadata.types[owner]
        node = dict(identity(t), role=role, depth=depth,
                    type_definition_index=owner, byval_type_index=t['byval_type_index'],
                    declaring_type_index=t['declaring_type_index'],
                    parent=resolve(t['parent_type_index']), methods=[], fields=[])
        methods = [m for m in metadata.methods[t['method_start']:t['method_start'] + t['method_count']]
                   if label(m['name'])]
        methods.sort(key=lambda m: (not any(w in m['name'].lower() for w in member_words),
                                    m['name'], m['parameter_count']))
        exported = methods[:min(MAX_METHODS, max(0, MAX_TOTAL_METHODS - totals['methods']))]
        for method in exported:
            checkpoint()
            count = min(method['parameter_count'], MAX_PARAMETERS,
                        max(0, MAX_TOTAL_PARAMETERS - totals['parameters']))
            parameters = []
            for index in range(count):
                type_index = struct.unpack_from('<i', metadata.data,
                    parameter_offset + (method['parameter_start'] + index) * 12 + 8)[0]
                parameters.append(resolve(type_index))
                totals['parameters'] += 1
                # Include exact parameter owners such as city result models or
                # online-mode enums; no attempt to guess a primitive or generic.
                follow(type_index, depth + 1)
            node['methods'].append(dict(method=method['name'], arity=method['parameter_count'],
                static=method['static'], virtual=bool(method['method_flags'] & 64),
                abstract=bool(method['method_flags'] & 1024),
                return_type=resolve(method['return_type_index']), parameters=parameters,
                parameters_truncated=method['parameter_count'] != len(parameters)))
            totals['methods'] += 1
            if any(w in method['name'].lower() for w in member_words):
                follow(method['return_type_index'], depth + 1)
        fields = [(name, ti) for name, ti in fields_by_owner.get(owner, []) if label(name)]
        fields.sort(key=lambda f: (not any(w in f[0].lower() for w in member_words), f[0]))
        exported_fields = fields[:min(MAX_FIELDS, max(0, MAX_TOTAL_FIELDS - totals['fields']))]
        for name, type_index in exported_fields:
            checkpoint()
            node['fields'].append(dict(field=name, declared_type=resolve(type_index)))
            totals['fields'] += 1
            if any(w in name.lower() for w in member_words):
                follow(type_index, depth + 1)
        follow(t['parent_type_index'], depth + 1)
        node.update(method_total=len(methods), field_total=len(fields),
                    truncated=(len(exported) != len(methods) or len(exported_fields) != len(fields)
                               or any(m['parameters_truncated'] for m in node['methods'])))
        nodes.append(node)
    checkpoint()
    return dict(purpose=purpose, roots=roots,
                types=nodes, candidate_total=len(candidates), exported_totals=totals,
                truncated=truncated or any(n['truncated'] for n in nodes))


def inspect_bundle(folder, cancelled=lambda: False, expected_hashes=None):
    try:
        report = inspect_definitions(folder, cancelled, expected_hashes,
                                     collector=lambda metadata: collect(metadata, cancelled))
    except CatalogCancelled:
        # Match the safe envelope of the shared reader; do not serialize an
        # exception, a path or a partly collected metadata object.
        report = dict(status='catalog-stopped', reason='cancelled', catalog=None,
                      ui_actions_attempted=False, messages_sent=0, method_values_read=False)
    report.update(tool='DvkAssistant', tool_version='search-definitions',
                  mode='offline-search-settings-definitions', adb_used=False,
                  emulator_contacted=False, chat_content_read=False,
                  gadget_config_read=False, personal_data_exported=False,
                  search_settings_applied=False, online_verified=False, city_verified=False)
    if report['status'] == 'catalog-ready':
        catalog = report['catalog']
        report['review_status'] = ('definitions-incomplete' if catalog['truncated']
            or any(r['status'] != 'found' for r in catalog['roots']) else 'definitions-collected')
    else:
        report['review_status'] = 'collection-stopped'
    return report


def write_report(folder, cancelled=lambda: False, *, destination=None):
    report = inspect_bundle(folder, cancelled)
    if cancelled():
        # Cancel late too: a completed report must not be mistaken for the
        # outcome of an operation the user has explicitly stopped.
        report.update(status='catalog-stopped', reason='cancelled', catalog=None,
                      review_status='collection-stopped')
    text = json.dumps(report, ensure_ascii=False, separators=(',', ':')) + '\n'
    if len(text.encode('utf-8')) > MAX_REPORT_BYTES:
        report.update(status='catalog-stopped', reason='report-size-limit', catalog=None,
                      review_status='collection-stopped')
        text = json.dumps(report, ensure_ascii=False, separators=(',', ':')) + '\n'
    destination = data_directory() if destination is None else Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / 'search-settings-definitions.json'
    temporary = target.with_suffix('.tmp')
    try:
        temporary.write_text(text, encoding='utf-8')
        temporary.replace(target)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return report, target
