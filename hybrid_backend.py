"""Bounded external CPU backends, hard cancellation, no external service calls."""
import json,os,queue,subprocess,sys,threading
from model_assets import installation_root,models_root

class Cancelled(Exception):pass

class NeuralBackend:
    def __init__(self):self.encoder=None;self.running=None;self.answers=queue.Queue();self.lock=threading.Lock();self.dead=False;self.epoch=0
    def cancel(self):
        with self.lock:
            self.epoch+=1;self.answers.put('')
            for p in (self.encoder,self.running):
                if p and p.poll() is None:
                    try:p.kill()
                    except OSError:pass
                    def reap(process=p):
                        try:process.wait(timeout=3)
                        except Exception:pass
                        for stream in (process.stdin,process.stdout):
                            if stream:
                                try:stream.close()
                                except OSError:pass
                    threading.Thread(target=reap,daemon=True).start()
            self.encoder=None;self.running=None;self.answers=queue.Queue()
    def close(self):self.dead=True;self.cancel()
    def semantic(self,context,options,threads=2,cache=None,timeout=1.0,kind='encoder'):
        if self.dead:raise Cancelled()
        epoch=self.epoch;answers=self.answers
        cold=self.encoder is None or self.encoder.poll() is not None
        if cold:
            cmd=[sys.executable,'--hybrid-worker'] if getattr(sys,'frozen',False) else [sys.executable,str(installation_root()/'hybrid_worker.py')]
            p=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            with self.lock:
                if self.dead or epoch!=self.epoch:
                    p.kill();p.wait();raise Cancelled()
                self.encoder=p
            def read():
                try:
                    for line in p.stdout:answers.put(line)
                finally:answers.put('')
            threading.Thread(target=read,daemon=True).start()
        p=self.encoder
        task={'kind':kind,'root':str(models_root()/('sage' if kind=='sage' else 'rubert-tiny2')),'context':context[:1500],'options':[s[:1500] for s in options[:600]],'threads':threads,'cache':str(cache) if cache else None}
        try:
            p.stdin.write(json.dumps(task,ensure_ascii=False)+'\n');p.stdin.flush()
            raw=answers.get(timeout=12 if cold else timeout)
            result=json.loads(raw)
            if 'error' in result:raise RuntimeError(result['error'])
            return result
        except Exception:
            self.cancel();raise
    def deep(self,context,candidates,threads=2,cache=None):
        return self.semantic(context,candidates,threads,cache,timeout=3,kind='sage')
