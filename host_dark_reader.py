"""Experimental host-side known-dark-palette OCR. Read-only, no network or actions.

Requires an explicit conversation ROI. Bright-text masking suppresses dim service
labels in the observed palette but can also omit grey/coloured message content.
Emoji, timestamps, identities and message freshness are NOT verified.
"""
import argparse
import csv
from io import BytesIO, StringIO
import json
from pathlib import Path
import subprocess
from PIL import Image, ImageOps
from bubble_detector import detect, MAX_PIXELS
from chat_core import InputError

def bright_text_mask(crop):
    crop=crop.convert('RGB')
    mask=Image.new('L',crop.size,255)
    mask.putdata([0 if min(rgb)>=180 else 255 for rgb in crop.get_flattened_data()])
    return ImageOps.expand(mask,border=15,fill=255).resize(((crop.width+30)*2,(crop.height+30)*2))

def read_screen(image,roi):
    candidates=[]
    for bubble in detect(image,roi):
        x,y,w,h=bubble['bounds']
        crop=bright_text_mask(image.crop((x,y,x+w,y+h)))
        stream=BytesIO();crop.save(stream,format='PNG')
        try:
            proc=subprocess.run(['tesseract','stdin','stdout','-l','rus+eng','--psm','6','tsv'],
                input=stream.getvalue(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=20)
        except (OSError,subprocess.TimeoutExpired):
            raise InputError('Host Tesseract unavailable or timed out') from None
        if proc.returncode: raise InputError('Host Tesseract failed')
        words=[]
        for row in csv.DictReader(StringIO(proc.stdout.decode('utf-8')),delimiter='\t'):
            if row.get('level')=='5' and row.get('text','').strip():
                confidence=float(row['conf'])
                words.append({'text':row['text'],'confidence':confidence,'uncertain':confidence<85})
        candidates.append(dict(bubble,text=' '.join(word['text'] for word in words),words=words,
            text_verified=False,emoji_verified=False))
    return {'method':'experimental_dark_bright_text_mask_v1','roi':roi,'message_candidates':candidates,
        'warnings':['Mask may omit grey/coloured message text and corrupt emojis.',
                    'Explicit ROI excludes profile/UI; no general automatic screen segmentation.',
                    'Candidate directions, conversation identity and message freshness are not verified.'],
        'automatic_reply_enabled':False,'messages_sent':0}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',type=Path,required=True)
    parser.add_argument('--roi',type=int,nargs=4,required=True)
    args=parser.parse_args()
    try:
        with Image.open(args.image) as image:
            if image.width*image.height>MAX_PIXELS: raise InputError('Image too large')
            image=image.convert('RGB')
            rx,ry,rw,rh=args.roi
            from chat_core import rect
            rect(args.roi,image.width,image.height)
            # Do not apply this experimental dark-only preprocessing to a light UI.
            sample=[image.getpixel((rx+(rw-1)*i//4,ry+(rh-1)*j//4)) for i in range(5) for j in range(5)]
            if sum(max(p)<=80 for p in sample)<13: raise InputError('Dark ROI not confirmed')
            result=read_screen(image,args.roi)
        print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    except (InputError,OSError,ValueError,Image.DecompressionBombError):
        parser.exit(2,'Screen unavailable, unsupported or OCR failed. No action performed.\n')
    return 0

if __name__=='__main__':raise SystemExit(main())
