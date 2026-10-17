"""Rotating metadata-only UI diagnostics. No selectors, text or screenshots."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

def configure(directory):
    logger=logging.getLogger('dvk.ui');logger.setLevel(logging.INFO);logger.propagate=False
    if logger.handlers:return
    path=Path(directory);path.mkdir(parents=True,exist_ok=True)
    handler=RotatingFileHandler(path/'ui-actions.log',maxBytes=1048576,backupCount=2,encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler)
