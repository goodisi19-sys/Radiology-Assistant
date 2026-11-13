"""Local, opt-in-at-insertion continuations learned from saved clinical prose."""
import hashlib
import re
import time

ROOTS = ('грыж','протруз','деформац','дуральн','мешк','сужен','латеральн','карман',
         'межпозвонков','отверст','центральн','парамедиан','задн','диск','мениск','сигнал',
         'суставн','поверхност','контур','структур','паренхим','капсул','мышц','желудоч','ликвор','позвон','печен','почк','матк','артери','сосуд',
         'артроз','кист','синовит','выпот','отек','очаг','стеноз','перелом','хрящ','связк','сухожил')
ANCHORS = {'грыж','протруз','мениск','артроз','кист','синовит','выпот','отек','очаг','стеноз','перелом','хрящ','связк','сухожил'}
META = re.compile(r'фио|фамилия|пациент|дата\s*(?:рожд|исслед)|паспорт|телефон|адрес|лечащ|подпись|врач|заключение|рекоменд',re.I)
RISK = re.compile(r'\[|\]|уточнит|\d|_{2,}|…|\.{3,}|\b(?:прав\w*|лев\w*|справа|слева)\b|\b[CTLSctls](?:[IVX]+)\b|миллиметр\w*|сантиметр\w*|двусторонн\w*|с\s+обеих\s+сторон',re.I)


def tokens(text):
    words=re.findall(r'[а-яё]+',text.casefold().replace('ё','е'))
    return [next((root for root in ROOTS if word.startswith(root)),word) for word in words
            if (len(word)>2 or word=='не') and word not in {'мм','см','мл','размером','размерами','описание'}]


def region(text):
    found=re.findall(r'\b(th|[ctls])\s*\d',text,re.I)
    return (found[0].casefold().replace('th','t') if found else '')


def negative(words):
    return any(word in {'не','без','нет'} or word.startswith(('отсутств','невыявл')) for word in words)


def tail_word(text):
    word = re.findall(r'\S+',text.rstrip())[-1].casefold().strip('.,;:()') if text.strip() else ''
    return '#' if re.search(r'\d',word) else word


def extract(text):
    text=re.split(r'(?im)^[ \t]*заключение\b|\bзаключение\s*:',text,maxsplit=1)[0]
    heading=re.search(r'(?im)^[ \t]*описание[ \t]*[:：]',text)
    if heading: text=text[heading.end():]
    pairs=set()
    for line in text.splitlines():
        if not 30<=len(line)<=1500 or META.search(line) or re.search(r'_{2,}|…|\.{3,}|\[|\]',line):continue
        if re.match(r'\s*(?:На серии|Методика|Исследование выполнено)',line,re.I):continue
        for boundary in re.finditer(r'[,;]\s+|\s+',line,re.I):
            prefix=line[:boundary.start()]; suffix=line[boundary.end():].strip()
            context=tokens(prefix)
            if not (set(context)&ANCHORS or len(context)>=2) or not 8<=len(suffix)<=300 or len(tokens(suffix))<2:continue
            if RISK.search(suffix) or META.search(suffix):continue
            separator='; ' if ';' in boundary.group() else ', ' if ',' in boundary.group() else ' '
            pairs.add((' '.join(context[-14:]),suffix,separator,region(prefix),tail_word(prefix)))
    return pairs


class AdaptiveMemory:
    def __init__(self,db):
        self.db=db
        db.execute('''CREATE TABLE IF NOT EXISTS adaptive_documents(signature TEXT PRIMARY KEY, source TEXT NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS adaptive_continuations(
            context TEXT NOT NULL, suffix TEXT NOT NULL, separator TEXT NOT NULL, region TEXT NOT NULL, tail TEXT NOT NULL,
            source TEXT NOT NULL, uses INTEGER NOT NULL DEFAULT 1, updated REAL NOT NULL,
            PRIMARY KEY(context,suffix,separator,region,tail,source))''')
        db.execute('CREATE INDEX IF NOT EXISTS adaptive_recent ON adaptive_continuations(source,updated)')
        db.commit()

    def learn(self,text,verified=False):
        source='verified' if verified else 'saved'
        signature=hashlib.sha256((source+'\n'+re.sub(r'\s+',' ',text).strip()).encode()).hexdigest()
        if self.db.execute('SELECT 1 FROM adaptive_documents WHERE signature=?',(signature,)).fetchone():return 0
        pairs=extract(text)
        if not pairs:return 0
        with self.db:
            self.db.execute('INSERT INTO adaptive_documents VALUES(?,?)',(signature,source))
            for context,suffix,separator,area,tail in pairs:
                self.db.execute('''INSERT INTO adaptive_continuations(context,suffix,separator,region,tail,source,uses,updated)
                    VALUES(?,?,?,?,?,?,1,?) ON CONFLICT(context,suffix,separator,region,tail,source)
                    DO UPDATE SET uses=uses+1,updated=excluded.updated''',(context,suffix,separator,area,tail,source,time.time()))
        return len(pairs)

    def suggest(self,before,limit=3):
        # Never append a clinical clause to a half-typed word.
        if not before or (not before[-1].isspace() and before[-1] not in ',;:'):return []
        query=tokens(before[-220:]); q=set(query)
        if not (q&ANCHORS or len(q)>=2):return []
        area=region(before); ranked={}
        rows=self.db.execute('''SELECT context,suffix,separator,region,tail,source,uses FROM adaptive_continuations
            ORDER BY (source='verified') DESC,updated DESC LIMIT 3000''').fetchall()
        for context,suffix,separator,stored_area,tail,source,uses in rows:
            stored=set(context.split())
            if not (q&stored&ANCHORS or (len(query)>=2 and query[-2:]==context.split()[-2:])):continue
            if separator==' ' and tail_word(before)!=tail:continue
            if area and stored_area and area!=stored_area:continue
            if negative(q)!=negative(stored):continue
            overlap=len(q&stored)/len(q)
            if len(q)>2 and overlap<0.5:continue
            first=tokens(suffix)[:2]
            if len(first)==2 and set(first)<=q:continue
            score=(source=='verified',overlap,min(uses,10000),len(q&stored))
            candidate={'text':suffix,'separator':separator,'verified':source=='verified'}
            if suffix not in ranked or score>ranked[suffix][0]:ranked[suffix]=(score,candidate)
        return [value[1] for value in sorted(ranked.values(),key=lambda value:value[0],reverse=True)[:limit]]

    def clear_saved(self):
        with self.db:
            self.db.execute("DELETE FROM adaptive_continuations WHERE source='saved'")
            self.db.execute("DELETE FROM adaptive_documents WHERE source='saved'")

    def count(self):return self.db.execute('SELECT count(*) FROM adaptive_continuations').fetchone()[0]
