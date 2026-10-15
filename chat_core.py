"""Portable, offline OCR grouping core. No network, ADB, GUI or sending.

Input rectangles are candidate bubbles supplied by a detector/fixture, NOT
validated message identities. Geometry alone never establishes a new message.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import sys

MAX_INPUT = 8 * 1024 * 1024
ROLES = {'content', 'timestamp', 'status', 'ui'}
DIRECTIONS = {'incoming_candidate', 'outgoing_candidate', 'unknown'}

class InputError(ValueError):
    pass

def rect(value, width, height):
    if not isinstance(value, list) or len(value) != 4:
        raise InputError('Invalid rectangle')
    if any(type(n) not in (int, float) or (type(n) is float and not math.isfinite(n)) for n in value):
        raise InputError('Invalid rectangle')
    x, y, w, h = value
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > width or y+h > height:
        raise InputError('Rectangle outside image')
    return value

def contains(outer, inner):
    x, y, w, h = outer
    a, b, c, d = inner
    return a >= x and b >= y and a+c <= x+w and b+d <= y+h

def process(document):
    if not isinstance(document, dict) or type(document.get('schema_version')) is not int or document.get('schema_version') != 1:
        raise InputError('Unsupported input schema')
    width, height = document.get('image_width'), document.get('image_height')
    if any(type(n) is not int or not 1 <= n <= 32768 for n in (width, height)):
        raise InputError('Invalid image size')
    bubbles, lines = document.get('bubbles'), document.get('lines')
    if not isinstance(bubbles, list) or not isinstance(lines, list) or len(bubbles) > 1000 or len(lines) > 10000:
        raise InputError('Invalid item list')
    ids = set()
    validated = []
    for bubble in bubbles:
        if not isinstance(bubble, dict): raise InputError('Invalid bubble')
        key, direction = bubble.get('id'), bubble.get('direction', 'unknown')
        if not isinstance(key, str) or not 1 <= len(key) <= 100 or key in ids:
            raise InputError('Invalid bubble id')
        if not isinstance(direction, str) or direction not in DIRECTIONS: raise InputError('Invalid direction')
        ids.add(key)
        validated.append({'id': key, 'direction': direction, 'bounds': rect(bubble.get('bounds'), width, height)})
    # Overlapping candidate rectangles are ambiguous. Never use order to guess.
    grouped = {b['id']: [] for b in validated}
    raw, unassigned, excluded = [], [], []
    for index, line in enumerate(lines):
        if not isinstance(line, dict): raise InputError('Invalid OCR line')
        text, role = line.get('text'), line.get('role', 'content')
        if not isinstance(text, str) or len(text) > 10000 or not isinstance(role, str) or role not in ROLES:
            raise InputError('Invalid OCR line')
        bounds = rect(line.get('bounds'), width, height)
        item = {'source_index': index, 'text': text, 'bounds': bounds, 'role': role}
        raw.append(item)
        if role != 'content':
            # Only explicitly labelled service elements are excluded. A message
            # containing '17:30', 'OK', an emoji or a typo remains untouched.
            excluded.append(index)
            continue
        owners = [b for b in validated if contains(b['bounds'], bounds)]
        if len(owners) == 1 and text.strip():
            grouped[owners[0]['id']].append(item)
        else:
            unassigned.append(index)
    candidates = []
    for bubble in sorted(validated, key=lambda b: (b['bounds'][1], b['bounds'][0], b['id'])):
        items = sorted(grouped[bubble['id']], key=lambda r: (r['bounds'][1], r['bounds'][0], r['source_index']))
        if items:
            candidates.append({'bubble_id': bubble['id'], 'direction': bubble['direction'],
                'text': ' '.join(item['text'].strip() for item in items),
                'source_indices': [item['source_index'] for item in items]})
    return {'schema_version': 1, 'message_candidates': candidates,
            'raw_lines': raw, 'unassigned_source_indices': unassigned,
            'excluded_service_source_indices': excluded,
            'directions_verified': False, 'bubble_boundaries_verified': False,
            'new_messages_detected': False, 'automatic_reply_enabled': False,
            'messages_sent': 0}

def decode(data):
    if len(data) > MAX_INPUT: raise InputError('Input too large')
    try:
        return json.loads(data.decode('utf-8-sig'), parse_constant=lambda _: (_ for _ in ()).throw(InputError('Invalid number')))
    except (UnicodeError, ValueError, RecursionError):
        raise InputError('Invalid JSON input') from None

def main():
    parser = argparse.ArgumentParser(description='Offline OCR candidate grouping; no sending')
    parser.add_argument('--input', type=Path, help='UTF-8 JSON; otherwise stdin')
    parser.add_argument('--output', type=Path, help='Local UTF-8 JSON; otherwise stdout')
    args = parser.parse_args()
    try:
        if args.input:
            with args.input.open('rb') as stream: data = stream.read(MAX_INPUT+1)
        else: data = sys.stdin.buffer.read(MAX_INPUT+1)
        result = process(decode(data))
        output = (json.dumps(result, ensure_ascii=False, allow_nan=False)+'\n').encode('utf-8')
        if args.output: args.output.write_bytes(output)
        else: sys.stdout.buffer.write(output)
    except (InputError, OSError, TypeError, RecursionError):
        # No raw OCR, keys, filenames or remote data in error diagnostics.
        sys.stderr.write('Invalid input or unavailable local file. No action performed.\n')
        return 2
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
