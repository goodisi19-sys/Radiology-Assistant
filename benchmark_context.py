"""Reproducible real-library retrieval probe, not clinical or unseen-source validation."""
import json,tempfile,time,statistics,hashlib
from pathlib import Path
from collections import defaultdict
import app
from context_retrieval import ContextIndex,norm

def run():
 with tempfile.TemporaryDirectory() as tmp:
  app.app_data_dir=lambda:Path(tmp);lib=app.PhraseLibrary();idx=ContextIndex(lib);stats=idx.stats();samples=[];seen=set()
  for context,suffix,area,mode,source in idx.db.execute('SELECT context,suffix,area,modality,source_id FROM windows ORDER BY source_id,id'):
   key=(area,context,suffix)
   if key in seen or len(context.split())!=3:continue
   seen.add(key)
   # Deterministic held-out evaluation queries: no feedback/training calls.
   if int(hashlib.sha256(str(key).encode()).hexdigest()[:6],16)%13==0:samples.append((context,suffix,area,mode,source))
  samples=sorted(samples,key=lambda r:hashlib.sha256(str(r).encode()).hexdigest())[:400]
  groups=defaultdict(list);times=[];queries=idx.query_count
  for context,suffix,area,mode,source in samples:
   idx.shortlist=None;start=time.perf_counter();rows=idx.suggest('Обзор исследования. '+context+' ',area=area,kind=mode,limit=5);times.append((time.perf_counter()-start)*1000)
   found=next((i+1 for i,r in enumerate(rows) if norm(r['suffix'])==norm(suffix)),0);groups[area].append(found)
  def metrics(ranks):return {'n':len(ranks),'recall_at_5':sum(bool(x) for x in ranks)/max(1,len(ranks)),'mrr':sum(1/x if x else 0 for x in ranks)/max(1,len(ranks))}
  ranks=[v for rows in groups.values() for v in rows];result={'method':'Source-backed lookup; queries withheld from feedback; sources remain indexed. Not unseen-source or clinical validation.','index':stats,'protocols_preserved':lib.db.execute('SELECT count(*) FROM templates').fetchone()[0],'overall':metrics(ranks),'areas':{k:metrics(v) for k,v in groups.items()},'lookup_ms':{'p50':statistics.median(times),'p95':sorted(times)[int(.95*(len(times)-1))],'max':max(times)},'queries':idx.query_count-queries}
  from adaptive_completion import library_completions
  baseline=[]
  for context,suffix,area,mode,source in samples:
   rows=library_completions(lib.db,context+' ',area,limit=5)
   baseline.append(next((i+1 for i,r in enumerate(rows) if norm(r['suffix'])==norm(suffix)),0))
  result['previous_exact_prefix_baseline']=metrics(baseline)
  result['precision_note']='Multiple clinically plausible suffixes share short contexts; only retrieval of the original source suffix is scored. No adjudicated clinical precision estimate.'
  idx.close();start=time.perf_counter();idx=ContextIndex(lib);result['warm_index_open_ms']=(time.perf_counter()-start)*1000;idx.close();lib.db.close()
 return result
if __name__=='__main__':
 result=run();Path('reports').mkdir(exist_ok=True);Path('reports/context-retrieval.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
