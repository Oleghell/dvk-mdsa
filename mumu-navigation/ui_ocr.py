"""On-demand local Tesseract TSV fallback. No capture or OCR at import/startup.

Only text selectors can fall back; OCR cannot verify native class/capabilities.
No files, recognised text or screenshots are written to the diagnostic log.
"""
import csv,hashlib,math,shutil,subprocess,sys
from io import BytesIO,StringIO
from pathlib import Path
from PIL import Image
from ui_model import ElementNotFound,AmbiguousElement,UIError,UnsupportedUI
from ui_runtime import Element

MAX_PIXELS=10000000

def frame_hash(image):
    return hashlib.sha256((str(image.width)+':'+str(image.height)+':').encode('ascii')+image.convert('RGB').tobytes()).hexdigest()

def parse_tsv(raw,width,height,min_confidence=90):
    if not isinstance(raw,str) or len(raw)>2000000:raise UIError('Invalid OCR response')
    lines={}
    try:
        for row in csv.DictReader(StringIO(raw),delimiter='\t'):
            if row.get('level')!='5' or not row.get('text','').strip():continue
            x,y,w,h=(int(row[k]) for k in ('left','top','width','height'));conf=float(row['conf'])
            if not math.isfinite(conf) or not 0<=conf<=100 or not (0<=x<x+w<=width and 0<=y<y+h<=height):raise ValueError()
            key=tuple(row[k] for k in ('page_num','block_num','par_num','line_num'))
            lines.setdefault(key,[]).append((row['text'],conf,(x,y,x+w,y+h)))
    except (ValueError,KeyError,TypeError):raise UIError('Malformed OCR bounds/confidence') from None
    result=[]
    for words in lines.values():
        # Never silently discard an uncertain word to create a false exact match.
        if min(w[1] for w in words)<min_confidence:continue
        bounds=[min(w[2][0] for w in words),min(w[2][1] for w in words),max(w[2][2] for w in words),max(w[2][3] for w in words)]
        result.append({'text':' '.join(w[0] for w in words),'bounds':bounds,'confidence':min(w[1] for w in words)})
    return result

class TesseractFallback:
    def __init__(self,capture,executable=None,runner=subprocess.run):
        self.capture=capture;self.executable=executable;self.runner=runner
    def find(self,runtime,query,tree):
        if set(query)-{'text','text_contains'}:raise ElementNotFound('OCR cannot establish native selector properties')
        portable=Path(sys.executable).resolve().parent/'runtime/tesseract/tesseract.exe'
        exe=self.executable or (str(portable) if portable.is_file() else shutil.which('tesseract'))
        if not exe:raise UnsupportedUI('Local Tesseract rus+eng required for this fallback; native UI remains available')
        png=self.capture()
        with Image.open(BytesIO(png)) as source:
            if source.format!='PNG' or source.width*source.height>MAX_PIXELS or min(source.size)<200:raise UIError('Invalid fallback frame')
            image=source.convert('RGB');sha=frame_hash(image)
            if image.size!=(tree.width,tree.height):raise UIError('Viewport changed before OCR')
            try:
                out=self.runner([str(exe),'stdin','stdout','-l','rus+eng','--psm','11','tsv'],input=png,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=15)
            except (OSError,subprocess.TimeoutExpired):raise UnsupportedUI('Local OCR unavailable or timed out') from None
            if out.returncode:raise UnsupportedUI('Local OCR failed; no action taken')
            lines=parse_tsv(out.stdout.decode('utf-8'),image.width,image.height)
            matches=[n for n in lines if (n['text']==query['text'] if 'text' in query else query['text_contains'] in n['text'])]
        if not matches:raise ElementNotFound('OCR target not found with sufficient confidence')
        if len(matches)!=1:raise AmbiguousElement('OCR matched multiple regions')
        n=matches[0]
        return Element(runtime,query,n,tree.context,'ocr',{'sha256':sha,'width':tree.width,'height':tree.height})
