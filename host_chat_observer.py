"""Read-only host observer. Baseline + conservative visible-content deduplication.

Visual context is NOT a verified account/conversation ID. A changed candidate
is NOT proof of a new message. This module cannot draft, click, type or send.
SQLite persists hashes only, not chat text, avatars, screenshots or labels.
"""
import argparse
import csv
from contextlib import closing
import hashlib
from io import BytesIO, StringIO
import json
from pathlib import Path
import sqlite3
import subprocess
import unicodedata
from PIL import Image
from chat_core import InputError, rect
from host_dark_reader import bright_text_mask, read_screen

MAX_CONTEXTS=100
MAX_SEEN_PER_CONTEXT=1000

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def content_key(candidate):
    # Conservative suppression: two genuine identical messages may collapse.
    text=' '.join(unicodedata.normalize('NFC',candidate['text']).split())
    return digest({'direction':candidate['direction'],'text':text})

class Observer:
    def __init__(self,path):
        self.path=path
        with closing(sqlite3.connect(path,timeout=10)) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS contexts (context_id TEXT PRIMARY KEY, last_frame TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS seen (context_id TEXT NOT NULL, signature TEXT NOT NULL,
                    PRIMARY KEY(context_id, signature));
            ''')
    def observe(self,context_id,frame_id,candidates,context_readable=True):
        common={'identity_verified':False,'freshness_verified':False,'automatic_reply_enabled':False,'messages_sent':0}
        def result(status,review=None): return dict(common,status=status,review_candidates=review or [])
        if not context_readable or not context_id or not frame_id:
            return result('blocked_unreadable_context')
        incoming=[c for c in candidates if c.get('direction')=='incoming_candidate']
        if any(not c.get('text','').strip() or not c.get('words') or
               any(w.get('uncertain',True) for w in c['words']) for c in incoming):
            return result('blocked_uncertain_incoming_ocr')
        unique={content_key(c):c for c in incoming}
        with closing(sqlite3.connect(self.path,timeout=10)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT last_frame FROM contexts WHERE context_id=?',(context_id,)).fetchone()
            if previous is None:
                if db.execute('SELECT COUNT(*) FROM contexts').fetchone()[0]>=MAX_CONTEXTS:
                    return result('blocked_state_capacity')
                if len(unique)>MAX_SEEN_PER_CONTEXT:return result('blocked_state_capacity')
                db.execute('INSERT INTO contexts VALUES (?,?)',(context_id,frame_id))
                db.executemany('INSERT INTO seen VALUES (?,?)',[(context_id,sig) for sig in unique])
                return result('baseline_only')
            if previous[0]==frame_id:return result('unchanged_visible_region')
            seen={row[0] for row in db.execute('SELECT signature FROM seen WHERE context_id=?',(context_id,))}
            new=[sig for sig in unique if sig not in seen]
            if len(seen)+len(new)>MAX_SEEN_PER_CONTEXT:return result('blocked_state_capacity')
            db.executemany('INSERT INTO seen VALUES (?,?)',[(context_id,sig) for sig in new])
            db.execute('UPDATE contexts SET last_frame=? WHERE context_id=?',(frame_id,context_id))
            review=[dict(unique[sig],requires_human_review=True,reason='Unseen visible text; may be old history, not a verified new message') for sig in new]
            return result('changed_incoming_candidate_requires_review' if review else 'no_unseen_incoming_content',review)

def observe_image(image,conversation_roi,header_roi,avatar_roi,state_path):
    for roi in (conversation_roi,header_roi,avatar_roi):
        rect(roi,image.width,image.height)
        if any(type(n) is not int for n in roi):raise InputError('Integer ROI required')
    def crop(roi):
        x,y,w,h=roi;return image.crop((x,y,x+w,y+h)).convert('RGB')
    header=crop(header_roi)
    stream=BytesIO();bright_text_mask(header).save(stream,format='PNG')
    try:
        proc=subprocess.run(['tesseract','stdin','stdout','-l','rus+eng','--psm','7','tsv'],
            input=stream.getvalue(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=20)
    except (OSError,subprocess.TimeoutExpired):raise InputError('Header OCR unavailable') from None
    if proc.returncode:raise InputError('Header OCR failed')
    words=[row for row in csv.DictReader(StringIO(proc.stdout.decode()),delimiter='\t') if row.get('level')=='5' and row.get('text','').strip()]
    label=' '.join(row['text'] for row in words)
    readable=bool(words) and all(float(row['conf'])>=85 for row in words)
    context_id=digest({'size':image.size,'header_roi':header_roi,'avatar_roi':avatar_roi,'conversation_roi':conversation_roi,
        'header_pixels':hashlib.sha256(header.tobytes()).hexdigest(),
        'avatar_pixels':hashlib.sha256(crop(avatar_roi).tobytes()).hexdigest()})
    frame_id=digest({'roi':conversation_roi,'pixels':hashlib.sha256(crop(conversation_roi).tobytes()).hexdigest()})
    # The experimental reader is dark-palette only; fail closed on a light ROI.
    area=crop(conversation_roi)
    samples=[area.getpixel(((area.width-1)*i//4,(area.height-1)*j//4)) for i in range(5) for j in range(5)]
    if sum(max(p)<=80 for p in samples)<13:raise InputError('Dark ROI not confirmed')
    ocr=read_screen(image,conversation_roi)
    result=Observer(state_path).observe(context_id,frame_id,ocr['message_candidates'],readable)
    return dict(result,context_label_candidate=label,context_matching='exact_visual_fingerprint_only',
        visible_candidates=ocr['message_candidates'],warnings=ocr['warnings']+[
            'Same name/avatar is not a unique account identity; dynamic avatars can create a new baseline.',
            'Scrolled-in old text can be unseen here. Repeated genuine identical text may be suppressed.',
            'Explicit ROIs are layout-specific; no unattended loop or automatic replies.'])

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',type=Path,required=True)
    parser.add_argument('--roi',nargs=4,type=int,required=True)
    parser.add_argument('--header-roi',nargs=4,type=int,required=True)
    parser.add_argument('--avatar-roi',nargs=4,type=int,required=True)
    parser.add_argument('--state',type=Path,required=True)
    args=parser.parse_args()
    try:
        from bubble_detector import MAX_PIXELS
        with Image.open(args.image) as source:
            if source.width*source.height>MAX_PIXELS:raise InputError('Image too large')
            result=observe_image(source.convert('RGB'),args.roi,args.header_roi,args.avatar_roi,args.state)
        print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    except (InputError,OSError,ValueError,sqlite3.Error,Image.DecompressionBombError):
        parser.exit(2,'Observation failed safely. No action performed.\n')
    return 0
if __name__=='__main__':raise SystemExit(main())
