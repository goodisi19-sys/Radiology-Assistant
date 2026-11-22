"""Reproducible CPU-only measurements; source-run and EXE checks are distinct."""
import ctypes,json,os,statistics,tempfile,time
from pathlib import Path
from unittest.mock import patch

def rss():
    if os.name=='nt':
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
        c=Counters();c.cb=ctypes.sizeof(c)
        ctypes.windll.kernel32.GetCurrentProcess.restype=wintypes.HANDLE
        call=ctypes.windll.psapi.GetProcessMemoryInfo
        call.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
        if not call(ctypes.windll.kernel32.GetCurrentProcess(),ctypes.byref(c),c.cb):raise OSError('Cannot measure working set')
        return c.WorkingSetSize
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024

def run():
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    import app
    from PySide6.QtWidgets import QApplication
    from spell_check import dictionary,find_typos
    q=QApplication.instance() or QApplication([])
    before=rss();start=time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp,patch.object(app,'app_data_dir',return_value=Path(tmp)):
        library=app.PhraseLibrary();dictionary()
        warm=[];cold=[]
        for word,before_text,after_text in [('струткуры','Срединные ',' не смещены'),('смещны','Срединные структуры не ','')]:
            t=time.perf_counter();values=library.ai.corrections(word,before_text,after_text,'ГМ');cold.append((time.perf_counter()-t)*1000)
            for _ in range(200):
                t=time.perf_counter();library.ai.corrections(word,before_text,after_text,'ГМ');warm.append((time.perf_counter()-t)*1000)
        t=time.perf_counter();find_typos('\n'.join(['Срединные струткуры не смещны.']*100));scan=(time.perf_counter()-t)*1000
        result={'platform':os.name,'mode':'Быстрый','protocol_count':library.db.execute('SELECT count(*) FROM templates').fetchone()[0],
                'startup_seconds':time.perf_counter()-start,'warm_correction_p95_ms':sorted(warm)[int(len(warm)*.95)],
                'warm_correction_max_ms':max(warm),'cold_correction_ms':cold,'scan_100_paragraphs_ms':scan,
                'incremental_rss_mib':max(0,rss()-before)/1048576,
                'additional_binary_dependencies':0,'network_required':False,'gpu_required':False}
        library.db.close()
    Path('performance-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':run()
