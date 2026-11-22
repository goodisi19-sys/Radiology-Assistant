"""Frozen synthetic shadow checks for bounded ranking updates, not clinical validation."""
import math,json,time
from rapidfuzz.distance import DamerauLevenshtein
from medical_evaluation import MEDICAL_CASES,PROTECTED_CASES
from hybrid_safety import safe_pair

def score(weights):
    reciprocal=[]
    for index,(original,_,choices) in enumerate(MEDICAL_CASES):
        gold=choices[0];options=list(choices)
        if index%2:options.reverse()
        def value(pair):
            i,c=pair
            features={'distance':-min(3,DamerauLevenshtein.distance(original.casefold(),c.casefold()))/3,'base':1/(i+1),'positive':0,'negative':0,'semantic':0}
            learned=sum(weights.get(k,0)*v for k,v in features.items())
            return 1/(i+1)+.2*max(-1,min(1,learned))
        ranked=[c for i,c in sorted(enumerate(options),key=lambda p:-value(p))]
        reciprocal.append(1/(ranked.index(gold)+1))
    return {'count':len(reciprocal),'mrr':sum(reciprocal)/len(reciprocal),'safety_failures':sum(safe_pair(a,b) for a,b in PROTECTED_CASES)}

def validate(previous,proposed):
    baseline=score(previous);candidate=score(proposed)
    candidate['baseline_mrr']=baseline['mrr'];candidate['synthetic_only']=True
    candidate['drift_l2']=math.sqrt(sum((proposed.get(k,0)-previous.get(k,0))**2 for k in set(previous)|set(proposed)))
    valid=all(math.isfinite(v) and abs(v)<=1 for v in proposed.values()) and candidate['drift_l2']<=.3 and not candidate['safety_failures'] and candidate['mrr']>=baseline['mrr']-.02
    return valid,candidate

def snapshot(db,weights,metrics,previous=None):
    # PhraseMemory created this table with a pre-migration backup. Five snapshots,
    # atomically committed with weights; verified sources are never removed.
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='rank_versions'").fetchone():return
    if not db.execute('SELECT 1 FROM rank_versions').fetchone():
        db.execute('INSERT INTO rank_versions(weights,metrics,active,created) VALUES(?,?,0,?)',(json.dumps(previous or {}),json.dumps(metrics),time.time()))
    db.execute('UPDATE rank_versions SET active=0')
    db.execute('INSERT INTO rank_versions(weights,metrics,active,created) VALUES(?,?,1,?)',(json.dumps(weights),json.dumps(metrics),time.time()))
    db.execute('DELETE FROM rank_versions WHERE id NOT IN (SELECT id FROM rank_versions ORDER BY id DESC LIMIT 5)')
