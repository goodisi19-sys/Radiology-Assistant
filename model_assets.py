"""Runtime model discovery and SHA-256 verification; never downloads at runtime."""
import hashlib,json,sys
from functools import lru_cache
from pathlib import Path

def installation_root():
    return Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent

def models_root():return installation_root()/'models'

@lru_cache(maxsize=16)
def _verified(path,size,mtime,expected):
    digest=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):digest.update(block)
    if digest.hexdigest()!=expected:raise ValueError('Model checksum mismatch')

def verify_files(root=None,prefix=''):
    root=Path(root or installation_root())
    lock=json.loads((root/'model-lock.json').read_text(encoding='utf8'))
    selected=[(name,sha) for name,sha in lock['files'].items() if name.startswith(prefix)]
    if not selected:raise ValueError('No pinned model assets')
    for name,sha in selected:
        file=root/'models'/name;s=file.stat();_verified(str(file),s.st_size,s.st_mtime_ns,sha)
    return True
