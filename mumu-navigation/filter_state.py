"""Conservative ON/OFF/unknown recognition for one fixed 900x1600 Unity UI.

Not an identity or message guard. Exact dialog/label anchors + fixed control ROI;
white thumb geometry + interior colour constraints, not a screenshot checksum.
Only anti-aliased/shadow boundary bands are excluded from colour cores. All core
pixels must match. Unknown never authorizes a toggle or filter confirmation.
The caller still supplies a fresh FULL-screen hash, independently checked by
Python and Android immediately before the physical input. No learned templates,
user masks, calibration, broad image similarity or operator bypass.
"""
import hashlib
import hmac
from io import BytesIO
from PIL import Image

FILTER_BOX = (360, 244, 543, 289)
FILTER_SHA = '263efd838fe25309f9da855d3c23893e2edb303dfc5ac4322b8d9e2292f44b18'
LABEL_BOX = (42, 998, 284, 1029)
LABEL_SHA = 'ce3aaf72a05c0de19eaa0e8f53c2b8baa64fa947357f62d64a9efc52dfdd4368'
SWITCH_BOX = (756, 981, 858, 1044)


def _white(rgb):
    return min(rgb) >= 240 and max(rgb) - min(rgb) <= 12


def _track(rgb, state):
    r, g, b = rgb
    if state == 'on':
        return r <= 12 and 145 <= g <= 190 and 132 <= b <= 180 and 0 <= g-b <= 28
    return (36 <= r <= 57 and 36 <= g <= 60 and 36 <= b <= 57
            and max(rgb)-min(rgb) <= 16)


# Fixed core masks, not externally supplied or expanded at runtime. Radius 23
# lies inside the 27px thumb; 32 excludes its shadow; 27 is inside pill radius31.
# Every core pixel must pass; there is no allowed proportion of failed pixels.
def _masks(cx):
    white, track, background = [], [], []
    for y in range(63):
        for x in range(102):
            pill = (x-min(71, max(31, x)))**2 + (y-31)**2
            thumb = (x-cx)**2 + (y-31)**2
            if thumb <= 23**2:
                white.append((x, y))
            elif pill <= 27**2 and thumb >= 32**2:
                track.append((x, y))
            elif pill >= 34**2:
                background.append((x, y))
    return white, track, background


_MASKS = {'on': _masks(71), 'off': _masks(31)}


def classify_switch(crop):
    """Internal fixed-ROI classifier; public full-frame wrapper checks anchors."""
    if crop.mode != 'RGB' or crop.size != (102, 63):
        return 'unknown'
    px = crop.load()
    points = [(x, y) for y in range(63) for x in range(102) if _white(px[x, y])]
    if not 2140 <= len(points) <= 2270:
        return 'unknown'
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    if not (52 <= max(xs)-min(xs)+1 <= 55 and 52 <= max(ys)-min(ys)+1 <= 55):
        return 'unknown'
    cx, cy = sum(xs)/len(xs), sum(ys)/len(ys)
    if not 29.5 <= cy <= 31.5:
        return 'unknown'
    candidates = []
    for state, center in [('on', 71), ('off', 31)]:
        if not center-1.5 <= cx <= center+0.5:
            continue
        # Reject additional white blobs, deformed thumbs and partial overlays.
        if any((x-center)**2+(y-31)**2 > 28.5**2 for x,y in points):
            continue
        white, track, background = _MASKS[state]
        if (all(_white(px[x,y]) for x,y in white)
                and all(_track(px[x,y], state) for x,y in track)
                and all(all(abs(a-b) <= 8 for a,b in zip(px[x,y], (24,28,33)))
                        for x,y in background)):
            candidates.append(state)
    return candidates[0] if len(candidates) == 1 else 'unknown'


def online_filter_state(png):
    """Return on/off/unknown. Never acts or modifies state; fail closed."""
    try:
        with Image.open(BytesIO(png)) as im:
            if im.format != 'PNG' or im.size != (900,1600):
                return 'unknown'
            im = im.convert('RGB')
            for box, expected in [(FILTER_BOX, FILTER_SHA), (LABEL_BOX, LABEL_SHA)]:
                if not hmac.compare_digest(hashlib.sha256(im.crop(box).tobytes()).hexdigest(), expected):
                    return 'unknown'
            return classify_switch(im.crop(SWITCH_BOX))
    except (OSError, ValueError):
        return 'unknown'
