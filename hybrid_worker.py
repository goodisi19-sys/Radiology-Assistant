"""Disposable CPU encoder process. No network, GUI, learning or patient-text logs."""
import hashlib, json, os, sqlite3, sys, time
from pathlib import Path

class Encoder:
    def __init__(self,root,threads=2,cache_path=None):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
        ort.disable_telemetry_events()
        from model_assets import verify_files
        root=Path(root);verify_files(root.parent.parent, prefix=root.name+'/')
        opts=ort.SessionOptions();opts.intra_op_num_threads=threads;opts.inter_op_num_threads=1
        opts.log_severity_level=3
        self.session=ort.InferenceSession(str(root/'model.int8.onnx'),sess_options=opts,providers=['CPUExecutionProvider'])
        self.tokenizer=Tokenizer.from_file(str(root/'tokenizer.json'));self.tokenizer.enable_truncation(max_length=128);self.tokenizer.enable_padding()
        self.np=np;self.cache={};self.model=hashlib.sha256((root/'model.int8.onnx').read_bytes()).hexdigest()
        self.db=sqlite3.connect(str(cache_path)) if cache_path else None
        if self.db:self.db.execute('CREATE TABLE IF NOT EXISTS vectors(model TEXT,digest TEXT,vector BLOB,PRIMARY KEY(model,digest))')
    def embed(self,texts):
        np=self.np;keys=[hashlib.sha256(t[:2000].encode()).hexdigest() for t in texts];missing=[]
        for key,text in zip(keys,texts):
            if key in self.cache:continue
            row=self.db.execute('SELECT vector FROM vectors WHERE model=? AND digest=?',(self.model,key)).fetchone() if self.db else None
            vector=np.frombuffer(row[0],dtype=np.float32).copy() if row else None
            if vector is not None and vector.size==312 and np.isfinite(vector).all():self.cache[key]=vector
            else:missing.append((key,text[:2000]))
        for start in range(0,len(missing),8):
            batch=missing[start:start+8];encoded=self.tokenizer.encode_batch([t for _,t in batch])
            inputs={k:np.array([getattr(e,attr) for e in encoded],dtype=np.int64) for k,attr in [('input_ids','ids'),('attention_mask','attention_mask'),('token_type_ids','type_ids')]}
            inputs={k:v for k,v in inputs.items() if k in {i.name for i in self.session.get_inputs()}}
            vectors=self.session.run(None,inputs)[0]
            for (key,_),v in zip(batch,vectors):
                self.cache[key]=v
                if self.db:self.db.execute('INSERT OR REPLACE INTO vectors VALUES(?,?,?)',(self.model,key,v.astype(np.float32).tobytes()))
        result=np.stack([self.cache[k] for k in keys])
        if self.db:
            self.db.execute('DELETE FROM vectors WHERE rowid IN (SELECT rowid FROM vectors ORDER BY rowid DESC LIMIT -1 OFFSET 5000)');self.db.commit()
        if len(self.cache)>1024:self.cache={k:self.cache[k] for k in keys[-64:]}
        return result
    def rank(self,context,options):
        vectors=self.embed([context]+options)
        return [float(x) for x in vectors[1:]@vectors[0]]

def main():
    # PyInstaller windowed builds expose None for sys.std* despite redirected pipes.
    # Recover inherited handles only inside the disposable worker, never in the GUI.
    if os.name=='nt' and (sys.stdin is None or sys.stdout is None):
        import ctypes,msvcrt
        from ctypes import wintypes
        get=ctypes.windll.kernel32.GetStdHandle;get.argtypes=[wintypes.DWORD];get.restype=wintypes.HANDLE
        if sys.stdin is None:sys.stdin=os.fdopen(msvcrt.open_osfhandle(get(-10 & 0xffffffff),os.O_RDONLY),'r',encoding='utf8')
        if sys.stdout is None:sys.stdout=os.fdopen(msvcrt.open_osfhandle(get(-11 & 0xffffffff),os.O_WRONLY),'w',encoding='utf8',buffering=1)
    try:
        import psutil
        p=psutil.Process();p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name=='nt' else 10)
    except Exception:pass
    encoder=None;sage=None
    for line in sys.stdin:
        try:
            task=json.loads(line)
            start=time.perf_counter()
            if task.get('kind')=='sage':
                if sage is None:sage=SageScorer(task['root'],task.get('threads',2))
                scores=sage.rank(task['context'],task['options'][:6])
            else:
                if encoder is None:encoder=Encoder(task['root'],task.get('threads',2),task.get('cache'))
                scores=encoder.rank(task['context'],task['options'][:600])
            result={'scores':scores,'ms':(time.perf_counter()-start)*1000,'loaded':{'rubert':encoder is not None,'sage':sage is not None},'context_key':task.get('context_key')}
        except Exception as exc:
            import traceback
            frame=traceback.extract_tb(exc.__traceback__)[-1]
            result={'error':'encoder_unavailable','error_type':type(exc).__name__,'stage':Path(frame.filename).name+':'+str(frame.lineno)}
            if task.get('diagnostic'):result['traceback']=traceback.format_exc()
        print(json.dumps(result),flush=True)


class SageScorer:
    """Scores existing full-sentence candidates; never generates new clinical text."""
    def __init__(self,root,threads=2):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
        ort.disable_telemetry_events()
        from model_assets import verify_files
        root=Path(root);verify_files(root.parent.parent,prefix='sage/')
        opts=ort.SessionOptions();opts.intra_op_num_threads=threads;opts.inter_op_num_threads=1;opts.log_severity_level=3
        self.session=ort.InferenceSession(str(root/'scorer.int8.onnx'),sess_options=opts,providers=['CPUExecutionProvider'])
        self.tokenizer=Tokenizer.from_file(str(root/'tokenizer.json'));self.tokenizer.enable_truncation(max_length=96);self.np=np
        config=json.loads((root/'config.json').read_text());self.start=config['decoder_start_token_id']
    def rank(self,source,candidates):
        np=self.np;encoded=self.tokenizer.encode(source);scores=[]
        for candidate in candidates[:6]:
            labels=self.tokenizer.encode(candidate).ids
            if len(labels)<2:raise ValueError('Empty candidate')
            inputs={'input_ids':np.array([encoded.ids],dtype=np.int64),'attention_mask':np.array([encoded.attention_mask],dtype=np.int64),
                    'decoder_input_ids':np.array([[self.start]+labels[:-1]],dtype=np.int64),'labels':np.array([labels],dtype=np.int64)}
            scores.append(float(self.session.run(None,inputs)[0][0]))
        return scores

if __name__=='__main__':main()
