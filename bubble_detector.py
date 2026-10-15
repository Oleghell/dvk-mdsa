"""Conservative light/known-dark-palette bubble candidates; no OCR or message identity.

Uses connected background-colour regions in an explicit conversation ROI.
Unsupported/ambiguous regions are left unassigned, never used for sending.
"""
from collections import Counter, deque
from PIL import Image, UnidentifiedImageError
from chat_core import InputError, rect

MAX_PIXELS = 16_000_000

def _family(rgb, theme='light', background=None):
    r, g, b = rgb
    if theme == 'dark':
        # Known DrugVokrug dark palette, not arbitrary themes or photos.
        # Suppress the dominant background even when its shade looks bubble-like.
        if background is not None and max(abs(a-c) for a,c in zip(rgb,background)) <= 10:
            return 0
        if 35 <= r <= 58 and 36 <= g <= 61 and 40 <= b <= 68 and max(rgb)-min(rgb) <= 18:
            return 1
        if r <= 20 and 32 <= g <= 68 and 30 <= b <= 68 and g-r >= 22 and abs(g-b) <= 14:
            return 2
        return 0
    if r >= 245 and g >= 245 and b >= 245 and max(rgb)-min(rgb) <= 10:
        return 1
    if 150 <= r <= 238 and g >= 195 and b >= 195 and g-r >= 7 and b-r >= 7 and abs(g-b) <= 28:
        return 2
    return 0

def detect(image, roi):
    width, height = image.size
    if width*height > MAX_PIXELS or width < 64 or height < 64:
        raise InputError('Unsupported image dimensions')
    rect(roi, width, height)
    if any(type(n) is not int for n in roi): raise InputError('ROI must be integer pixels')
    rx, ry, rw, rh = roi
    # Grid is bounded in both axes. Downsampling can lose small/narrow objects;
    # no claim of complete detection is made.
    step = max(1, (max(rw, rh)+599)//600)
    gw, gh = (rw+step-1)//step, (rh+step-1)//step
    pixels = image.convert('RGB').load()
    # Theme is inferred from a bounded 11x11 sample of this explicit ROI only.
    # A dominant dark neutral colour is required; do not mix light text into
    # incoming candidates on a dark screen.
    sample = [pixels[rx+(rw-1)*i//10,ry+(rh-1)*j//10] for i in range(11) for j in range(11)]
    background, frequency = Counter(sample).most_common(1)[0]
    dark = frequency >= 24 and max(background) <= 80 and max(background)-min(background) <= 28
    theme = 'dark' if dark else 'light'
    def classify(rgb):
        return _family(rgb, theme, background)
    grid = bytearray(gw*gh)
    for gy in range(gh):
        for gx in range(gw):
            x, y = min(rx+gx*step+step//2, rx+rw-1), min(ry+gy*step+step//2, ry+rh-1)
            grid[gy*gw+gx] = classify(pixels[x, y])
    visited = bytearray(len(grid))
    candidates = []
    for seed, family in enumerate(grid):
        if family == 0 or visited[seed]: continue
        queue = deque([seed]); visited[seed] = 1
        x0=x1=seed%gw; y0=y1=seed//gw; area=0
        while queue:
            pos=queue.popleft(); x,y=pos%gw,pos//gw; area+=1
            x0=min(x0,x); x1=max(x1,x); y0=min(y0,y); y1=max(y1,y)
            for nx,ny in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if 0 <= nx < gw and 0 <= ny < gh:
                    nxt=ny*gw+nx
                    if not visited[nxt] and grid[nxt] == family:
                        visited[nxt]=1; queue.append(nxt)
        bw,bh=(x1-x0+1)*step,(y1-y0+1)*step
        # Reject clipped bubbles, full-screen backgrounds, small icons and
        # sparse/text-shaped regions. Rectangularity is only a heuristic.
        if x0 == 0 or y0 == 0 or x1 == gw-1 or y1 == gh-1: continue
        if not (rw*.10 <= bw <= rw*.85 and max(12, rw*.018) <= bh <= rh*.65): continue
        if area / ((x1-x0+1)*(y1-y0+1)) < .68: continue
        left,right=x0*step,(x1+1)*step
        # A one-pixel gap may disappear on the bounded grid. Recheck every
        # full-resolution row across the component interior; if a complete
        # separator exists, reject the merged region rather than merge chats.
        margin=max(3,step*2)
        sample_left=rx+left+max(2,bw//10)
        sample_right=rx+right-max(2,bw//10)-1
        xs=sorted(set(sample_left+(sample_right-sample_left)*i//20 for i in range(21)))
        separated=False
        for py in range(ry+y0*step+margin,ry+(y1+1)*step-margin):
            if not any(classify(pixels[px,py]) == family for px in xs):
                separated=True
                break
        if separated: continue
        if family == 1:
            if left > rw*.18: continue
            direction='incoming_candidate'
        else:
            if right < rw*.82 or left < rw*.08: continue
            direction='outgoing_candidate'
        candidates.append({'bounds':[rx+left,ry+y0*step,bw,bh], 'direction':direction})
    candidates.sort(key=lambda b:(b['bounds'][1],b['bounds'][0]))
    # Any overlapping boxes are removed, rather than guessing an ownership.
    def overlaps(a,b):
        x,y,w,h=a; u,v,s,t=b
        return x < u+s and u < x+w and y < v+t and v < y+h
    result=[]
    for i,candidate in enumerate(candidates):
        if any(i != j and overlaps(candidate['bounds'],other['bounds']) for j,other in enumerate(candidates)):
            continue
        result.append(dict(id='candidate-'+str(len(result)+1), **candidate))
    return result

def detect_file(path, roi):
    # Inspect dimensions before decoding an untrusted file. No external URLs.
    try:
        with Image.open(path) as image:
            if image.width*image.height > MAX_PIXELS: raise InputError('Image too large')
            return detect(image, roi), image.size
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise InputError('Invalid or unsupported image') from None


def detect_png_bytes(data, roi):
    from io import BytesIO
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != 'PNG' or image.width*image.height > MAX_PIXELS:
                raise InputError('Unsupported PNG')
            return detect(image, roi), image.size
    except (OSError, ValueError, Image.DecompressionBombError):
        raise InputError('Invalid PNG') from None
