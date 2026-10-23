"""Avoid hashing 140 MB before every UI read. Invalidate on any file metadata change.
The original pinned SHA256/Gadget config validator is the ONLY token source.
No persistence, no cached device/history/identity data and no integrity fallback.
"""
from pathlib import Path
import stat
import threading

class VerifiedBundle:
    def __init__(self,validator):
        self.validator=validator;self.cache={};self.lock=threading.Lock()
    def signature(self,folder):
        rows=[]
        for name in ('base.apk','split-001.apk'):
            path=folder/name
            if path.is_symlink():raise OSError('APK symlink is not supported')
            s=path.stat()
            if not stat.S_ISREG(s.st_mode):raise OSError('APK is not a regular file')
            rows.append((s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns))
        return tuple(rows)
    def __call__(self,folder):
        folder=Path(folder).resolve(strict=True)
        with self.lock:
            before=self.signature(folder)
            entry=self.cache.get(folder)
            if entry is not None and entry[0]==before:return entry[1]
            self.cache.pop(folder,None)
            token=self.validator(folder)
            if self.signature(folder)!=before:raise OSError('APK changed during verification')
            self.cache[folder]=(before,token)
            return token
