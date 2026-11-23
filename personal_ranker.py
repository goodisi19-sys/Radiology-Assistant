"""Bounded online pairwise linear ranker. SQLite lives exclusively on the UI thread."""
import json, math, re
from rapidfuzz.distance import DamerauLevenshtein
from hybrid_safety import safe_pair, language_example

class PersonalRanker:
    def __init__(self, db):
        self.db=db
        db.executescript('''CREATE TABLE IF NOT EXISTS hybrid_memory_version(version INTEGER);
        INSERT INTO hybrid_memory_version SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM hybrid_memory_version);
        CREATE TABLE IF NOT EXISTS hybrid_weights(feature TEXT PRIMARY KEY, weight REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS hybrid_feedback(original TEXT, candidate TEXT, area TEXT, modality TEXT, accepted INTEGER, uses INTEGER DEFAULT 1, PRIMARY KEY(original,candidate,area,modality,accepted));
        CREATE TABLE IF NOT EXISTS hybrid_examples(digest TEXT PRIMARY KEY, text TEXT NOT NULL, area TEXT, modality TEXT, uses INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS hybrid_vectors(digest TEXT, model TEXT, vector BLOB, PRIMARY KEY(digest,model));''')
        self.reload()
    def reload(self):
        self.weights=dict(self.db.execute('SELECT feature,weight FROM hybrid_weights'))
    def features(self,original,candidate,index,area='',modality='',semantic=0):
        good=bad=0
        for accepted,n in self.db.execute('SELECT accepted,sum(uses) FROM hybrid_feedback WHERE original=? AND candidate=? AND (area=? OR area=\'\') AND (modality=? OR modality=\'\') GROUP BY accepted',(original.casefold(),candidate.casefold(),area,modality)):
            if accepted:good=n
            else:bad=n
        return {'distance':-min(3,DamerauLevenshtein.distance(original.casefold(),candidate.casefold()))/3,
                'base':1/(index+1),'positive':min(1,math.log1p(good)/3),'negative':-min(1,math.log1p(bad)/3),'semantic':max(-1,min(1,semantic))}
    def rank(self,original,candidates,area='',modality='',semantic=None,deep=None,mode='correction',trusted=()):
        semantic=semantic or {};deep=deep or {};ranked=[]
        for i,c in enumerate(candidates):
            from word_scoring import safe_completion,safe_word_correction
            allowed=(safe_completion(original,c,trusted) if mode=='completion' else (safe_completion(original,c,trusted) or safe_word_correction(original,c,trusted)) if mode=='editor' else safe_word_correction(original,c,trusted))
            if not allowed:continue
            f=self.features(original,c,i,area,modality,semantic.get(c,0))
            learned=sum(self.weights.get(k,0)*v for k,v in f.items())
            # Neural influence and individual examples are deliberately bounded.
            score=1/(i+1)+.2*max(-1,min(1,learned))+.12*semantic.get(c,0)+.3*(f['positive']+f['negative'])+.7*max(0,min(1,deep.get(c,0)))
            ranked.append((score,i,c))
        return [c for _,_,c in sorted(ranked,key=lambda x:(-x[0],x[1]))]
    def feedback(self,original,candidate,alternatives,area='',modality='',accepted=True):
        if not safe_pair(original,candidate):return
        # Store only word pairs; no raw patient context. Area/modality are categorical.
        if not re.fullmatch('[А-Яа-яЁёA-Za-z -]{2,100}',original+candidate):return
        chosen=self.features(original,candidate,0,area,modality)
        other=next((c for c in alternatives if c!=candidate),original)
        contrast=self.features(original,other,1,area,modality)
        sign=1 if accepted else -1
        with self.db:
            proposed={key:max(-1,min(1,self.weights.get(key,0)*.998+.08*sign*(chosen[key]-contrast[key]))) for key in chosen}
            from rank_guard import validate,snapshot
            valid,metrics=validate(self.weights,proposed)
            if valid:
                snapshot(self.db,proposed,metrics,self.weights)
                for key,w in proposed.items():
                    self.db.execute('INSERT INTO hybrid_weights VALUES(?,?) ON CONFLICT(feature) DO UPDATE SET weight=excluded.weight',(key,w))
            self.db.execute('INSERT INTO hybrid_feedback VALUES(?,?,?,?,?,1) ON CONFLICT(original,candidate,area,modality,accepted) DO UPDATE SET uses=min(uses+1,100)',(original.casefold(),candidate.casefold(),area,modality,int(accepted)))
        self.reload()
    def add_example(self,text,area='',modality=''):
        import hashlib
        if not language_example(text):return
        digest=hashlib.sha256(text.encode()).hexdigest()
        with self.db:self.db.execute('INSERT INTO hybrid_examples VALUES(?,?,?,?,1) ON CONFLICT(digest) DO UPDATE SET uses=min(uses+1,100)',(digest,text,area,modality))
    def examples(self,area='',limit=3):
        return [r[0] for r in self.db.execute('SELECT text FROM hybrid_examples WHERE area=? OR area=\'\' ORDER BY uses DESC LIMIT ?',(area,limit))]
    def clear(self):
        with self.db:
            for table in ('hybrid_feedback','hybrid_weights','hybrid_examples','hybrid_vectors'):self.db.execute('DELETE FROM '+table)
        self.reload()
