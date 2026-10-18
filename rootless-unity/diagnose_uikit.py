"""Explicit opt-in GUI for the bounded UIKit root probe; test MuMu #4 only."""
import sys
from diagnose_device import launch_gui

if __name__=='__main__':
    if sys.argv[1:] not in ([],['--self-check']):raise SystemExit(2)
    launch_gui(self_check=sys.argv[1:]==['--self-check'],uikit_root_probe=True)
