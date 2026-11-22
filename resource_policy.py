"""Sampled resource policy; no inference imports and no blocking CPU sampling."""
import os, time
from dataclasses import dataclass

@dataclass(frozen=True)
class Resources:
    cores:int; total_gb:float; available_gb:float; cpu:float; avx2:bool

def sample():
    import psutil
    avx2=False
    if os.name=='nt':
        import ctypes
        avx2=bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(40)) # PF_AVX2_INSTRUCTIONS_AVAILABLE
    else:
        try:
            with open('/proc/cpuinfo') as f:avx2='avx2' in f.read().lower()
        except OSError:pass
    m=psutil.virtual_memory()
    return Resources(os.cpu_count() or 1,m.total/2**30,m.available/2**30,psutil.cpu_percent(interval=None),avx2)

class ResourcePolicy:
    def __init__(self):self.mode='Экономичный';self.changed=0;self.bert_allowed=False;self.deep_allowed=False
    def choose(self,r,requested='Автоматический',now=None):
        now=time.monotonic() if now is None else now
        target='Расширенный' if r.available_gb>=6 and r.cores>=8 and r.cpu<35 else ('Сбалансированный' if r.available_gb>=2.5 and r.cores>=4 and r.cpu<65 else 'Экономичный')
        if requested!='Автоматический':
            order=['Экономичный','Сбалансированный','Расширенный'];target=order[min(order.index(target),order.index(requested) if requested in order else 1)]
        urgent=r.available_gb<1.5 or r.cpu>=85
        if target!=self.mode and (urgent or now-self.changed>=20):self.mode=target;self.changed=now
        if not r.avx2 or r.available_gb<1.0 or r.cpu>=80:self.bert_allowed=False
        elif r.available_gb>=1.5 and r.cpu<60:self.bert_allowed=True
        if self.mode=='Экономичный' or not r.avx2 or r.available_gb<2.5 or r.cpu>=70:self.deep_allowed=False
        elif r.available_gb>=3.5 and r.cpu<50:self.deep_allowed=True
        bert=self.bert_allowed;deep=self.deep_allowed
        return {'mode':self.mode,'bert':bert,'deep':deep,'threads':max(1,min(2,r.cores//2)), 'resources':r.__dict__}
