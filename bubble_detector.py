"""Conservative light-theme bubble candidates; no OCR or message identity.

Uses connected background-colour regions in an explicit conversation ROI.
Unsupported/ambiguous regions are left unassigned, never used for sending.
"""
from collections import deque
from PIL import Image, UnidentifiedImageError
from chat_core import InputError, rect

MAX_PIXELS = 16_000_000

def _family(rgb):
    r, g, b = rgb
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
    grid = bytearray(gw*gh)
    for gy in range(gh):
        for gx in range(gw):
            x, y = min(rx+gx*step+step//2, rx+rw-1), min(ry+gy*step+step//2, ry+rh-1)
            grid[gy*gw+gx] = _family(pixels[x, y])
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
