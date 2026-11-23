"""Reproducible diagnostic ablation. Synthetic development cases, NOT clinical accuracy."""
import sys,json,math,tempfile,subprocess,types,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from benchmark_hybrid import GENERAL
from medical_evaluation import MEDICAL_CASES
from hybrid_worker import Encoder,SageScorer
from hybrid_safety import safe_pair
from word_scoring import word_key,local_window,safe_word_correction,WORD,folded
from radiology_ai import classify
from spell_check import suggest
from rapidfuzz.distance import DamerauLevenshtein
import app

NEW_CASES=[('однороденая','Паренхима {}.','однородная'),('гладкые','Поверхности {}.','гладкие'),('утолщнная','Стенка {}.','утолщенная'),('обычног','Костный мозг {} сигнала.','обычного'),('свобден','Позвоночный канал {}.','свободен'),('тонкя','Капсула {}.','тонкая'),('целсные','Связки {}.','целостные'),('уплотнна','Ткань {}.','уплотнена')]

def run():
    baseline=types.ModuleType('published_word_baseline');sys.modules[baseline.__name__]=baseline
    code=subprocess.check_output(['git','show','bebe3b4:radiology_ai.py'],cwd=ROOT,text=True)
    exec(compile(code,'published_radiology_ai.py','exec'),baseline.__dict__)
    encoder=Encoder(ROOT/'models/rubert-tiny2');sage=SageScorer(ROOT/'models/sage')
    out=[]
    with tempfile.TemporaryDirectory() as tmp,patch.object(app,'app_data_dir',return_value=Path(tmp)):
        lib=app.PhraseLibrary();ai=lib.ai
        old=object.__new__(baseline.LocalAI);old.__dict__=ai.__dict__.copy();old.neural_scores={};old.deep_scores={}
        cases=[(w,t,g[0],'previous_24') for w,t,g in GENERAL+MEDICAL_CASES]+[(w,t,g,'additional_development') for w,t,g in NEW_CASES]
        for word,template,gold,group in cases:
            before,after=template.split('{}');area=classify(template.format(word));kind=''
            old_values=tuple(dict.fromkeys(old.ranked_completion(word,before,area)+old.ranked_corrections(word,before,'',area)))
            fallback_ms=0
            if not ai.correction_candidates(word,before,after,area,kind):
                start=time.perf_counter()
                values=tuple(c for c in suggest(word) if WORD.fullmatch(c) and DamerauLevenshtein.distance(word.casefold(),c.casefold())<=2 and safe_word_correction(word,c,ai.words))[:6]
                fallback_ms=(time.perf_counter()-start)*1000
                if values:ai.extra_candidates[word_key(word,before,after,area,kind)]=values
            pool=ai.editor_candidates(word,before,after,area,kind)
            ai.deep_scores.clear();lexical=ai.editor_options(word,before,after,area,kind)
            left,_,right=local_window(before,word,after);rendered=[left+c+right for c in pool]
            semantic=encoder.rank(left+word+right,rendered) if pool else []
            deep=[]
            start=time.perf_counter()
            for i in range(0,len(pool),6):deep.extend(sage.rank(left+word+right,rendered[i:i+6]))
            sage_ms=(time.perf_counter()-start)*1000
            bert_rank=ai.ranker.rank(word,pool,area,kind,semantic=dict(zip(pool,semantic)),mode='editor',trusted=ai.words)
            ai.deep_scores[word_key(word,before,after,area,kind)]=dict(zip(pool,deep))
            sage_rank=ai.editor_options(word,before,after,area,kind)
            weights={c:math.exp(v-max(deep)) for c,v in zip(pool,deep)} if deep else {}
            combined=ai.ranker.rank(word,pool,area,kind,semantic=dict(zip(pool,semantic)),deep=weights,mode='editor',trusted=ai.words)
            no_change=folded(word)==folded(gold)
            def correct(values):return (not values and no_change) or bool(values and folded(values[0])==folded(gold))
            out.append({'word':word,'template':template,'gold':gold,'group':group,'area':area,'no_change_case':no_change,'candidate_coverage':no_change or any(folded(c)==folded(gold) for c in pool),'candidates':list(pool),'A_published_editor_words':old_values[0] if old_values else None,'B_candidates_lexical':lexical[0] if lexical else None,'C_word_bert_experimental':bert_rank[0] if bert_rank else None,'D_sage':sage_rank[0] if sage_rank else None,'E_combined_experimental':combined[0] if combined else None,'correct':dict(zip('ABCDE',[correct(v) for v in [old_values,lexical,bert_rank,sage_rank,combined]])),'fallback_ms':fallback_ms,'sage_ms':sage_ms})
        lib.db.close()
    result={'baseline':'bebe3b4','scope':'Development diagnostic, not independent clinical validation (the previous 24 include rank_guard controls); A models the old visible word union, excluding library phrase groups; no-change is a correct abstention only if no replacement is proposed. B differs in candidates/safety, C-E share B candidates and memory. Production does not use word cosine.','counts':{g:{'n':sum(r['group']==g for r in out),'correct':{k:sum(r['correct'][k] for r in out if r['group']==g) for k in 'ABCDE'},'candidate_coverage':sum(r['candidate_coverage'] for r in out if r['group']==g)} for g in ['previous_24','additional_development']},'cases':out}
    (ROOT/'reports/neural-word-value.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result['counts'],ensure_ascii=False))
if __name__=='__main__':run()
