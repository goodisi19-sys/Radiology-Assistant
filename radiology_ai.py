"""Small offline lexical model. No diagnosis generation, downloads or implicit edits."""
from collections import Counter, defaultdict
from functools import lru_cache
import hashlib
import math
import re
from rapidfuzz import fuzz, process
from rapidfuzz.distance import DamerauLevenshtein

KEYBOARD=str.maketrans('qwertyuiopasdfghjklzxcvbnm','йцукенгшщзфывапролдячсмить')
def wrong_layout(word):
    return word.casefold().translate(KEYBOARD) if re.fullmatch('[A-Za-z]{5,}',word) else ''

WORDS = re.compile(r'[а-яё]+', re.I)
SENSITIVE = re.compile(r'фио|пациент|фамили|паспорт|телефон|адрес|дата\s*(?:рожд|исслед)|врач|подпись|@|https?://', re.I)
CRITICAL = re.compile(r'^(?:не|нет|без|прав\w*|лев\w*|справа|слева|отсутств\w*|невыявл\w*)$', re.I)
AREAS = {
 'ГМ': ('головного мозга','головной мозг','желудочки мозга','срединные структуры','гипофиз','гм'),
 'Позвоночник': ('позвоноч','позвонков','межпозвон','дурального мешка','шоп','гоп','поп'),
 'ОМТ': ('малого таза','малый таз','предстател','простата','матка','яичник','pi-rads'),
 'Суставы': ('сустав','мениск','связк','колено','плечо','тазобедрен'),
 'Брюшная полость': ('печен','почка','почки','поджелудоч','брюшной полости','желчный'),
 'Мягкие ткани': ('мягких ткан','мышц','подкожн'),
 'Сосуды': ('ангиограф','артер','сосуд','венограф'),
}
@lru_cache(maxsize=8192)
def normalized(text):
    text = text.casefold().replace('ё','е')
    # Conservative retrieval stems, never used to rewrite the report.
    value=' '.join(re.sub(r'(?:иями|ами|ого|ему|ому|ыми|ими|иях|ах|ях|ые|ая|ое|ой|ый|ий|ов|ам|ям|ом|ем|ы|и|а|у|е)$','',w) if len(w)>5 else w for w in WORDS.findall(text))
    synonyms={'гм':'мозг','головн':'мозг','голов':'мозг','шоп':'шейн','поп':'поясничн','гоп':'грудн','омт':'таз','почек':'почк'}
    return ' '.join(synonyms.get(w,w) for w in value.split())


def classify(text, fallback='Другие исследования'):
    text=text.casefold().replace('ё','е')
    scores={area:sum(text.count(k) * (2 if ' ' in k else 1) for k in keys) for area,keys in AREAS.items()}
    best=max(scores,key=scores.get)
    return best if scores[best] else fallback


def modality(text):
    t=text.casefold()
    return 'КТ' if re.search(r'\bкт\b|компьютерн',t) else ('МРТ' if re.search(r'\bмрт?\b|магнитно',t) else '')

def safe_lines(text):
    for line in text.splitlines():
        if SENSITIVE.search(line): continue
        # Identity-like short capitalized name lines are not clinical learning data.
        if re.fullmatch(r'\s*(?:[А-ЯЁ][а-яё]+\s+){1,3}[А-ЯЁ][а-яё]+\s*', line): continue
        yield line


class LocalAI:
    def __init__(self, db, corpus=()):
        self.db=db
        db.executescript('''CREATE TABLE IF NOT EXISTS local_ai_metadata(version INTEGER);
        CREATE TABLE IF NOT EXISTS ai_corrections(original TEXT, replacement TEXT, area TEXT, uses INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(original,replacement,area));
        CREATE TABLE IF NOT EXISTS ai_words(word TEXT PRIMARY KEY, uses INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS ai_ngrams(context TEXT, phrase TEXT, uses INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(context,phrase));
        CREATE TABLE IF NOT EXISTS ai_sources(digest TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS ai_exclusions(phrase TEXT PRIMARY KEY);
        INSERT INTO local_ai_metadata SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM local_ai_metadata);''')
        self.words=Counter(); self.bigrams=Counter(); self.area_words=defaultdict(Counter)
        for text,area in corpus: normalized(text); self.index(text,area)
        # Reuse the pre-existing medical lexicon for candidates, not just acceptance.
        from spell_check import MEDICAL_WORDS
        self.words.update(MEDICAL_WORDS)
        self.base_words=self.words.copy(); self.base_bigrams=self.bigrams.copy()
        self.base_areas={k:v.copy() for k,v in self.area_words.items()}
        for word,count in db.execute('SELECT word,uses FROM ai_words ORDER BY uses DESC LIMIT 20000'): self.words[word]+=count
        for (word,) in db.execute('SELECT word FROM spelling_words'): self.words[word.casefold()]+=1
        self.refresh_memory()
        from personal_ranker import PersonalRanker
        self.ranker=PersonalRanker(db)
        self.neural_scores={};self.deep_scores={}

    def ranked_corrections(self,word,before='',after='',area=''):
        values=self.corrections(word,before,after,area)
        if not hasattr(self,'ranker'):return values
        key=(word,before.rsplit('\n',1)[-1],after.split('\n',1)[0],area)
        scores=self.neural_scores.get(key,{})
        return tuple(self.ranker.rank(word,values,area,modality(before+after),scores,self.deep_scores.get(key,{})))

    def ranked_completion(self,prefix,before='',area=''):
        values=self.complete(prefix,before,area)
        if not hasattr(self,'ranker'):return values
        return tuple(self.ranker.rank(prefix,values,area,modality(before),self.neural_scores.get((prefix,before,'',area),{}),self.deep_scores.get((prefix,before,'',area),{})))

    def enabled(self, key):
        row=self.db.execute('SELECT value FROM app_settings WHERE key=?',(key,)).fetchone()
        return not row or row[0]!='0'

    def index(self,text,area=''):
        area=area or classify(text)
        for line in safe_lines(text):
            words=[w.casefold().replace('ё','е') for w in WORDS.findall(line)]
            self.words.update(w for w in words if len(w)>2)
            self.bigrams.update(zip(words,words[1:])); self.area_words[area].update(words)

    def refresh_memory(self):
        self.words=self.base_words.copy();self.bigrams=self.base_bigrams.copy()
        self.area_words=defaultdict(Counter,{k:v.copy() for k,v in self.base_areas.items()})
        self.words.update(dict(self.db.execute('SELECT word,uses FROM ai_words ORDER BY uses DESC LIMIT 20000')))
        self.words.update(w for w, in self.db.execute('SELECT word FROM spelling_words'))
        self.words.update(getattr(self,'glossary_words',set()))
        for ctx,phrase,n in self.db.execute('SELECT context,phrase,uses FROM ai_ngrams'):
            if ctx.split() and phrase.split():self.bigrams[ctx.split()[-1],phrase.split()[0]]+=n
        self.confirmed={(a,b,c):n for a,b,c,n in self.db.execute('SELECT original,replacement,area,uses FROM ai_corrections ORDER BY uses DESC LIMIT 10000')}
        for (_,replacement,_),count in self.confirmed.items():self.words[replacement]+=count
        self.excluded={x[0] for x in self.db.execute('SELECT phrase FROM ai_exclusions')}
        self.corrections.cache_clear()
        self.complete.cache_clear()

    def learn_text(self,text,confirmed=False):
        if not confirmed or not self.enabled('self_learning'): return 0
        clean='\n'.join(safe_lines(text)); digest=hashlib.sha256(clean.encode()).hexdigest()
        if not clean or self.db.execute('SELECT 1 FROM ai_sources WHERE digest=?',(digest,)).fetchone():return 0
        counts=Counter(); grams=Counter()
        for line in clean.splitlines():
            # Do not retain numbers, dates, identifiers or raw documents.
            if re.search(r'\d|_{2,}|\[|\]',line): continue
            words=[w.casefold().replace('ё','е') for w in WORDS.findall(line)]
            counts.update(w for w in words if len(w)>2)
            for n in (1,2,3):
                for i in range(1,len(words)-n+1):
                    phrase=' '.join(words[i:i+n])
                    if not SENSITIVE.search(phrase): grams[(' '.join(words[max(0,i-2):i]),phrase)]+=1
        with self.db:
            self.db.execute('INSERT INTO ai_sources VALUES(?)',(digest,))
            for w,n in counts.items(): self.db.execute('INSERT INTO ai_words VALUES(?,?) ON CONFLICT(word) DO UPDATE SET uses=uses+excluded.uses',(w,n))
            for (ctx,p),n in grams.items(): self.db.execute('INSERT INTO ai_ngrams VALUES(?,?,?) ON CONFLICT(context,phrase) DO UPDATE SET uses=uses+excluded.uses',(ctx,p,n))
        self.index(clean); self.refresh_memory()
        if hasattr(self,'ranker'):
            for line in clean.splitlines():self.ranker.add_example(line,classify(line),modality(line))
        return sum(counts.values())

    def confirm_correction(self, original, replacement, area=''):
        if not self.enabled('self_learning') or not re.fullmatch('[А-Яа-яЁёA-Za-z]+',original) or not WORDS.fullmatch(replacement):return
        if CRITICAL.fullmatch(original) or CRITICAL.fullmatch(replacement):return
        if hasattr(self,'ranker'):
            self.ranker.feedback(original,replacement,self.corrections(original,area=area),area)
        with self.db:
            self.db.execute('INSERT INTO ai_corrections VALUES(?,?,?,1) ON CONFLICT(original,replacement,area) DO UPDATE SET uses=uses+1',(original.casefold(),replacement.casefold(),area))
        self.words[replacement.casefold()]+=1; self.refresh_memory()

    @lru_cache(maxsize=2048)
    def corrections(self, word, before='', after='', area=''):
        mapped=wrong_layout(word)
        if mapped and mapped in self.words and not CRITICAL.fullmatch(mapped):return (mapped.capitalize() if word[:1].isupper() else mapped,)
        if not WORDS.fullmatch(word) or CRITICAL.fullmatch(word) or len(word)<3 or (word.isupper() and len(word)<=5):return ()
        q=word.casefold().replace('ё','е'); prev=WORDS.findall(before.casefold())[-1:] or ['']; nxt=WORDS.findall(after.casefold())[:1] or ['']
        pool=[w for w in self.words if abs(len(w)-len(q))<=2 and not CRITICAL.fullmatch(w)]
        candidates=process.extract(q,pool,scorer=DamerauLevenshtein.distance,score_cutoff=(3 if self.db.execute("SELECT value FROM app_settings WHERE key='ai_mode'").fetchone()==('Расширенный',) else 2),limit=40)
        ranked=[]
        for candidate,distance,_ in candidates:
            if candidate==q or candidate in self.excluded:continue
            context=self.bigrams[prev[0],candidate]+self.bigrams[candidate,nxt[0]]
            learned=self.confirmed.get((q,candidate,area),0)+self.confirmed.get((q,candidate,''),0)
            score=distance*8 - min(learned,10)*3 - math.log1p(context)*2 - math.log1p(self.area_words[area][candidate]) - math.log1p(self.words[candidate])*.3
            value=candidate.capitalize() if word[0].isupper() else candidate
            if word.isupper():value=candidate.upper()
            ranked.append((score,value))
        return tuple(v for _,v in sorted(ranked)[:6])

    @lru_cache(maxsize=2048)
    def complete(self,prefix,before='',area=''):
        if not WORDS.fullmatch(prefix) or len(prefix)<2 or CRITICAL.fullmatch(prefix):return ()
        q=prefix.casefold();previous=(WORDS.findall(before.casefold()) or [''])[-1];ranked=[]
        for word,count in self.words.items():
            if len(word)<=len(q) or CRITICAL.fullmatch(word) or word in self.excluded:continue
            distance=DamerauLevenshtein.distance(q,word[:len(q)])
            if distance>(1 if len(q)>=4 else 0):continue
            score=distance*10-math.log1p(self.bigrams[previous,word])*2-math.log1p(count)*.3-math.log1p(self.area_words[area][word])*.5
            ranked.append((score,word.capitalize() if prefix[0].isupper() else word))
        return tuple(v for _,v in sorted(ranked)[:5])

    def continuations(self,before,limit=3):
        words=WORDS.findall(before.casefold()); context=' '.join(words[-2:]); last=words[-1] if words else ''
        if not context:return []
        rows=self.db.execute('SELECT phrase,sum(uses) FROM ai_ngrams WHERE context=? OR context=? GROUP BY phrase ORDER BY sum(uses) DESC LIMIT 30',(context,last))
        return [p for p,_ in rows if p not in self.excluded][:limit]

    def exclude(self, phrase):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO ai_exclusions VALUES(?)',(phrase,))
            self.db.execute('DELETE FROM ai_ngrams WHERE phrase=?',(phrase,))
            if hasattr(self,'ranker'):
                self.db.execute('DELETE FROM hybrid_examples WHERE text=?',(phrase,))
                self.db.execute('DELETE FROM hybrid_feedback WHERE candidate=?',(phrase,))
        self.refresh_memory()

    def clear(self):
        with self.db:
            for table in ('ai_corrections','ai_words','ai_ngrams'): self.db.execute('DELETE FROM '+table)
        if hasattr(self,'ranker'):self.ranker.clear();self.neural_scores.clear();self.deep_scores.clear()
        # Keep processed source digests to prevent silent re-learning on restart.
        self.refresh_memory()

    def stats(self):
        return {name:self.db.execute('SELECT count(*) FROM '+table).fetchone()[0] for name,table in [('Слова','ai_words'),('Исправления','ai_corrections'),('Формулировки','ai_ngrams')]}

    def search(self, query, rows, limit=100):
        if not query:return list(rows)[:limit]
        q=normalized(query);ranked=[]
        required=re.findall(r'(?i)\b(?:L|C|Th|T|S)\d+(?:[-–](?:L|C|Th|T|S)\d+)?\b|\d+(?:[.,]\d+)?',query)
        for row in rows:
            raw=' '.join(str(x) for x in row[1:])
            canonical=raw.casefold().replace('–','-')
            if any(v.casefold().replace('–','-') not in canonical for v in required):continue
            text=' '.join(normalized(str(x)) for x in row[1:])
            if not q:
                if query.casefold() in canonical:ranked.append((100,row))
                continue
            score=100 if q in text else fuzz.partial_ratio(q,text)
            if score>=78:ranked.append((score,row))
        return [r for _,r in sorted(ranked,key=lambda x:x[0],reverse=True)[:limit]]
