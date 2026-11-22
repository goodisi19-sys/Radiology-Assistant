"""Deterministic, source-hashed conversion cache; no Actions transfer artifact needed."""
import argparse,gzip,hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
OUTPUTS=('protocols_legacy.json','protocol_sources.json')
def sources():
    result={}
    for p in sorted(ROOT.glob('drive_doc_*.json')):
        text=p.read_text(encoding='utf-8-sig').strip()
        canonical=json.dumps(json.loads(text),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode() if text else b''
        result[p.name]=hashlib.sha256(canonical).hexdigest()
    return result
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--pack',action='store_true');args=parser.parse_args()
    bundle=ROOT/'converted_catalog.json.gz'
    if args.pack:
        payload={'source_hashes':sources(),'outputs':{n:json.loads((ROOT/n).read_text(encoding='utf8')) for n in OUTPUTS}}
        assert len(payload['outputs'][OUTPUTS[0]])==128 and len(payload['outputs'][OUTPUTS[1]])==180
        bundle.write_bytes(gzip.compress(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode(),mtime=0))
    else:
        payload=json.loads(gzip.decompress(bundle.read_bytes()))
        if payload['source_hashes']!=sources():raise RuntimeError('DOC sources changed: regenerate converted catalog with convert_legacy.py and prepare_catalog.py --pack')
        assert len(payload['outputs'][OUTPUTS[0]])==128 and len(payload['outputs'][OUTPUTS[1]])==180
        for n in OUTPUTS:
            temp=ROOT/(n+'.tmp');temp.write_text(json.dumps(payload['outputs'][n],ensure_ascii=False),encoding='utf8');temp.replace(ROOT/n)
        print('Verified original DOC hashes; restored 128 legacy protocols and 180 complete sources')
if __name__=='__main__':main()
