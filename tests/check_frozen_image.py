"""Execute the packaged program, rather than importing checkout code."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from synthetic_image import scene
ROOT=Path(__file__).resolve().parents[1]
exe=Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix='frozen image with spaces ') as folder:
    image=Path(folder)/'synthetic image.png'
    scene().save(image)
    completed=subprocess.run([str(exe),'--image',str(image),'--roi','0','0','800','600','--input',str(ROOT/'examples/synthetic-chat.json')],capture_output=True,timeout=60)
    if completed.returncode: raise RuntimeError('Frozen image pipeline failed')
    result=json.loads(completed.stdout)
    assert result['bubble_detection']['candidate_count']==3
    assert len(result['message_candidates'])==2
    assert result['message_candidates'][0]['source_indices']==[0,1]
    assert result['messages_sent']==0 and not result['automatic_reply_enabled']
    print('Actual Windows EXE passed image detection and multiline grouping.')
