"""Build-time extraction of SHA-pinned, repository-owned model assets; no downloads."""
import hashlib,json,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent

def prepare():
    lock=json.loads((ROOT/'model-lock.json').read_text())
    for key in ('encoder_archive','sage_archive'):
        info=lock[key];archive=ROOT/info['path']
        if hashlib.sha256(archive.read_bytes()).hexdigest()!=info['sha256']:raise ValueError('Model archive checksum mismatch')
        with zipfile.ZipFile(archive) as z:
            for item in z.infolist():
                if Path(item.filename).is_absolute() or '..' in Path(item.filename).parts:raise ValueError('Invalid archive path')
            z.extractall(ROOT/'models')
    sys.path.insert(0,str(ROOT))
    from model_assets import verify_files
    verify_files(ROOT);print('Pinned INT8 model/tokenizer/license files verified.')
if __name__=='__main__':prepare()
