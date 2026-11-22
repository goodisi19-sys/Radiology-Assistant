"""Synthetic held-out radiology candidate selection; not a clinical validation dataset."""
import json, math, os, tempfile, time
from pathlib import Path
from unittest.mock import patch
import psutil
from hybrid_worker import Encoder,SageScorer
from medical_evaluation import MEDICAL_CASES,PROTECTED_CASES
from hybrid_safety import safe_pair
GENERAL=[('струткуры','Срединные {} не смещены.',['структуры','структура']),('смещны','Срединные структуры не {}.',['смещены','смещена']),('контруы','{} ровные.',['Контуры','Контур']),('однороднй','Сигнал {}.',['однородный','однородной']),('сужен','Суставная щель {}.',['сужена','сужены']),('обычнй','Желудочки {} формы.',['обычной','обычный']),('изменна','Структура не {}.',['изменена','изменены']),('ровны','Контуры {}.',['ровные','ровный'])]
SEARCH=[('исследование головного мозга',['МРТ головного мозга.','МРТ коленного сустава.','МРТ малого таза.'],0),('межпозвонковые диски поясничного отдела',['МРТ позвоночника.','МРТ головного мозга.','МРТ плечевого сустава.'],0),('предстательная железа',['МРТ малого таза, простата.','МРТ головного мозга.','МРТ колена.'],0),('печень и желчные протоки',['КТ брюшной полости. Печень.','МРТ малого таза.','МРТ головного мозга.'],0)]

def probabilities(scores):
    top=max(scores);values=[math.exp(s-top) for s in scores];return values

def run():
    result={'synthetic_only':True,'clinical_validation':False,'base_model_weights_unchanged':True,'general_calibration_cases':8,'medical_control_not_used_for_training':True,'comparison':{},'medical_cases':len(MEDICAL_CASES)}
    encoders={};proc=psutil.Process()
    for name in ('rubert-tiny','rubert-tiny2','sage'):
        before=proc.memory_info().rss;t=time.perf_counter();model=SageScorer(Path('models/sage')) if name=='sage' else Encoder(Path('models')/name)
        load=time.perf_counter()-t;times=[];counts=[]
        for group in (GENERAL,MEDICAL_CASES):
            correct=0
            for i,(word,template,candidates) in enumerate(group):
                candidates=list(candidates);expected=0
                if i%2:candidates.reverse();expected=1
                t=time.perf_counter();scores=model.rank(template.format(word),[template.format(c) for c in candidates]);times.append((time.perf_counter()-t)*1000)
                correct+=int(max(range(len(scores)),key=lambda j:scores[j])==expected)
            counts.append([correct,len(group)])
        search=0
        if name!='sage':
            for query,options,expected in SEARCH:
                scores=model.rank(query,options);search+=int(max(range(len(scores)),key=lambda j:scores[j])==expected)
        warm=[]
        for _ in range(20):
            t=time.perf_counter();model.rank('Контуры ровные.',['Контуры ровные.','Контур ровный.']);warm.append((time.perf_counter()-t)*1000)
        result['comparison'][name]={'load_s':load,'candidate_pair_ms':times,'warm_ms':warm,'general_top1':counts[0],'medical_top1':counts[1],'search_top1':[search,len(SEARCH)] if name!='sage' else None,'sequential_incremental_rss_mib':(proc.memory_info().rss-before)/2**20}
        encoders[name]=model
    import app
    with tempfile.TemporaryDirectory() as tmp,patch.object(app,'app_data_dir',return_value=Path(tmp)):
        lib=app.PhraseLibrary();counts={'LocalAI':0,'LocalAI+RuBERT':0,'LocalAI+SAGE':0,'all_three':0};latencies={k:[] for k in counts};covered=0
        for word,template,gold in GENERAL+MEDICAL_CASES:
            before,after=template.split('{}');t=time.perf_counter();candidates=lib.ai.ranked_corrections(word,before,after);lex_ms=(time.perf_counter()-t)*1000
            if any(c.casefold()==gold[0].casefold() for c in candidates):covered+=1
            correct=lambda values:bool(values and values[0].casefold()==gold[0].casefold())
            counts['LocalAI']+=correct(candidates);latencies['LocalAI'].append(lex_ms)
            if not candidates:continue
            rendered=[template.format(c) for c in candidates]
            t=time.perf_counter();semantic=dict(zip(candidates,encoders['rubert-tiny2'].rank(template.format(word),rendered)));bert_ms=(time.perf_counter()-t)*1000
            t=time.perf_counter();deep=dict(zip(candidates,probabilities(encoders['sage'].rank(template.format(word),rendered))));sage_ms=(time.perf_counter()-t)*1000
            for key,s,d,extra in [('LocalAI+RuBERT',semantic,{},bert_ms),('LocalAI+SAGE',{},deep,sage_ms),('all_three',semantic,deep,bert_ms+sage_ms)]:
                values=lib.ai.ranker.rank(word,candidates,semantic=s,deep=d);counts[key]+=correct(values);latencies[key].append(lex_ms+extra)
        result['end_to_end']={'top1_out_of_24':counts,'correct_candidate_coverage':[covered,24],'wall_ms':latencies,'missing_candidates_are_failures':True}
        ranker=lib.ai.ranker;options=['ровный','ровные'];initial=ranker.rank('ровны',options)
        for _ in range(15):ranker.feedback('ровны','ровные',options);ranker.feedback('ровны','ровный',options,accepted=False)
        result['personalization']={'training_example_before':initial,'training_example_after':ranker.rank('ровны',options),'weights_changed':bool(ranker.weights),'heldout_not_trained':True,'weights':ranker.weights}
        # The held-out set is evaluated again with no training on its word pairs except
        # the explicitly labelled demonstration word, which is excluded here.
        holdout=[case for case in MEDICAL_CASES]
        result['personalization']['medical_holdout_after']=sum(bool((v:=ranker.rank(w,lib.ai.corrections(w,*t.split('{}')))) and v[0].casefold()==g[0].casefold()) for w,t,g in holdout)
        lib.db.close()
    result['protected_changes_rejected']=[sum(not safe_pair(a,b) for a,b in PROTECTED_CASES),len(PROTECTED_CASES)]
    result['limitations']=['24 synthetic paired alternatives are small and often have obvious agreement contrasts; not real-world accuracy.','End-to-end coverage depends on the existing medical lexicon; neural scoring cannot invent a missing candidate.','Memory deltas are sequential and allocator-dependent; GUI benchmark records parent+child peak.','4/8/16 GB are policy simulations, not measurements on three physical hosts.']
    Path('hybrid-benchmark.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':run()
