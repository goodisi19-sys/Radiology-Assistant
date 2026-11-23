"""Controlled Qt typing/idle/cancellation workload, not a whole-day CPU guarantee."""
import json,os,tempfile,time
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import psutil
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
import app

def run():
    q=QApplication.instance() or QApplication([]);process=psutil.Process();samples={};peak=0;gui_peak=0;worker_peak=0;latencies=[];start=time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp,patch.object(app,'app_data_dir',return_value=Path(tmp)):
        w=app.MainWindow();w.show();q.processEvents()
        def measure():
            nonlocal peak,gui_peak,worker_peak
            children=process.children(recursive=True);peak=max(peak,process.memory_info().rss+sum(c.memory_info().rss for c in children if c.is_running()))
            gui_peak=max(gui_peak,process.memory_info().rss)
            worker_peak=max(worker_peak,sum(c.memory_info().rss for c in children if c.is_running()))
            for c in [process]+children:
                try:
                    t=c.cpu_times();value=t.user+t.system
                    if c.pid not in samples:samples[c.pid]=[value,value]
                    samples[c.pid][1]=value
                except psutil.Error:pass
        measure();active=time.perf_counter()
        for ch in 'Срединные струткуры не смещны.\nКонтуры ровные; структура однородная.':
            t=time.perf_counter();w.editor.insertPlainText(ch);q.processEvents();latencies.append((time.perf_counter()-t)*1000);QTest.qWait(20);measure()
        w.editor.moveCursor(w.editor.textCursor().MoveOperation.Start)
        for _ in range(100):QTest.qWait(50);measure()
        t=time.perf_counter();w.hybrid.reset();cancel_ms=(time.perf_counter()-t)*1000
        wall=time.perf_counter()-active;cpu=sum(b-a for a,b in samples.values())
        result={'workload':'synthetic typing 20ms per character then 5s idle','wall_s':wall,'typing_p95_ms':sorted(latencies)[int(len(latencies)*.95)],'typing_max_ms':max(latencies),'cpu_core_equivalent_percent':100*cpu/wall,'cpu_machine_normalized_percent':100*cpu/wall/(os.cpu_count() or 1),'peak_parent_children_rss_mib':peak/2**20,'cancel_dispatch_ms':cancel_ms,'resource_policy':w.hybrid.resource_state,'status':w.hybrid.last_status}
        result['peak_gui_rss_mib']=gui_peak/2**20
        result['peak_worker_rss_mib']=worker_peak/2**20
        result['neural_stage_timings']=w.hybrid.backend.timing_snapshot()
        result['fts_lookup_ms']=list(w.completion_index.lookup_times)
        result['fts_initial_sync_ms']=w.completion_index.sync_ms
        result['memory_note']='Worker RSS includes ONNX runtime, tokenizer and SQLite; ONNX-only RSS is not separately attributed. Individual peaks need not coincide.'
        w.editor.document().setModified(False);w.close();QTest.qWait(100)
        result['children_after_close']=len([c for c in process.children() if c.is_running()])
    Path('hybrid-gui-benchmark.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':run()
