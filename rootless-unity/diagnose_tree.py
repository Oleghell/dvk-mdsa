"""Dedicated bounded UIKit structure-only GUI. No OCR, input or text reads."""
import sys
from diagnose_device import launch_gui
if __name__=='__main__':
    if sys.argv[1:] not in ([],['--self-check']):raise SystemExit(2)
    launch_gui(self_check=sys.argv[1:]==['--self-check'],uikit_tree_probe=True)
