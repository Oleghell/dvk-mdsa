"""Stage unsigned candidate sources in an explicit new directory; no installs/signing."""
from pathlib import Path
import shutil
import sys


def prepare(destination):
    here=Path(__file__).resolve().parent
    destination=Path(destination).resolve()
    pinned=here.parent/'control-android'
    if destination.exists():
        raise ValueError('Destination already exists; will not overwrite any files')
    if destination==pinned or pinned in destination.parents or here==destination or here in destination.parents:
        raise ValueError('Candidate must not overwrite pinned/candidate sources')
    shutil.copytree(pinned,destination,ignore=shutil.ignore_patterns('out','__pycache__'))
    for name in ('ControlInstrumentation.java','ProfileChatLocator.java','SemanticProfileTarget.java'):
        relative=Path('src/com/dvk/control')/name
        shutil.copyfile(here/relative,destination/relative)
    return destination


if __name__=='__main__':
    if len(sys.argv)!=2:
        raise SystemExit('Usage: python prepare_candidate.py NEW_OUTPUT_DIRECTORY')
    print(prepare(sys.argv[1]))
