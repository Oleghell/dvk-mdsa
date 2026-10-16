"""Read-only recognition of the observed 900x1600 city picker.

Only the static title and magnifier are pinned, never user results/photos.
Native accessibility exposes the search editor, NOT Unity city result rows.
This module cannot authorize city selection, filter confirmation or text input.
"""
import hashlib
import hmac
from io import BytesIO
from PIL import Image

CITY_EDITOR_BOUNDS = [118, 196, 786, 276]
CITY_FOCUS_POINT = (400, 236)
CITY_ANCHORS = (((330, 116, 574, 162), '50331b5d952f8fe1023158c36ad14853544677498c9dba2c3ec79c6f748b8633'), ((60, 216, 100, 258), '0f46440361d98a420a6263bcbe0c0a42d5e6be8a1b10f9e5b448164b4eb0ee8e'))


def check_city_field(png, layout, content_sha256):
    """Return only supported field evidence; malformed/unknown fails closed.

    Caller must acquire PNG + native tree afresh and compare their full content
    hashes, then recheck the complete PNG immediately before a physical action.
    A successful result proves neither complete search results nor applied city.
    """
    denied = {'city_picker_verified': False, 'reason': 'unsupported_city_picker'}
    try:
        with Image.open(BytesIO(png)) as im:
            if im.size != (900,1600) or im.format != 'PNG':
                return denied
            rgb = im.convert('RGB')
            if not all(hmac.compare_digest(hashlib.sha256(rgb.crop(box).tobytes()).hexdigest(), expected)
                       for box,expected in CITY_ANCHORS):
                return denied
        # Do not trust a caller-supplied digest without recomputing it.
        actual = hashlib.sha256(rgb.crop((0,48,900,1600)).tobytes()).hexdigest()
        if (not isinstance(content_sha256,str) or actual != content_sha256
                or not isinstance(layout,dict) or layout.get('truncated') is not False
                or layout.get('content_sha256') != actual):
            return dict(denied,reason='stale_or_incomplete_layout')
        nodes = layout.get('nodes')
        if not isinstance(nodes,list) or len(nodes)>200 or any(not isinstance(n,dict) for n in nodes):
            return dict(denied,reason='unsupported_native_nodes')
        edits = [n for n in nodes if n.get('editable')]
        if len(edits) != 1:
            return dict(denied,reason='non_unique_native_editor')
        edit = edits[0]
        bounds = edit.get('bounds')
        if (edit.get('class') != 'android.widget.EditText' or edit.get('enabled') is not True
                or edit.get('editable') is not True or edit.get('password',False) is not False
                or not isinstance(bounds,list) or len(bounds)!=4
                or any(type(v) is not int for v in bounds) or bounds!=CITY_EDITOR_BOUNDS
                or type(edit.get('focused')) is not bool or not isinstance(edit.get('text'),str)
                or len(edit['text'])>128):
            return dict(denied,reason='unsupported_native_editor')
        return {'city_picker_verified':True,'reason':'observed_native_city_editor',
                'query':edit['text'],'focused':edit['focused'],'bounds':list(bounds),
                'result_rows_available':False,'city_selection_supported':False,
                'city_input_supported':False,'applied_city_verified':False}
    except (OSError,ValueError,TypeError,KeyError):
        return denied
