"""Versioned, source-backed FTS5 contexts and RAM prefetch. Drafts are never indexed."""
import hashlib,re,sqlite3,time
from collections import deque
from rapidfuzz.distance import DamerauLevenshtein
from adaptive_completion import RISK,META,ANCHORS,tokens
from radiology_ai import safe_lines,classify,modality

WORDS=re.compile(r'[А-Яа-яЁёA-Za-z]+(?:-\w+)*|\d+(?:[.,]\d+)?')
def norm(text):return ' '.join(m.group().casefold().replace('ё','е') for m in WORDS.finditer(text))
from context_identity import context_key
def safe_suffix(suffix,before):
    return bool(suffix.strip()) and len(suffix)<=180 and not RISK.search(suffix) and not re.search(r'\b(?:мм|см|мл|влево|вправо|mm|cm)\b',suffix,re.I) and not META.search(suffix) and not re.search(r'\b[IVX]+(?:-го|-й)?\b',suffix) and not ((set(tokens(suffix))&ANCHORS)-set(tokens(before))) and not any(re.search(r'\b'+root+r'\w*',suffix,re.I) and not re.search(r'\b'+root+r'\w*',before,re.I) for root in ('метастаз','опухол','инфаркт','ишеми','демиелинизац','кровоизлияни'))

class ContextIndex:
    VERSION=2
    def __init__(self,library,fts=True):
        self.library=library;self.path=library.path.with_name('completion-index.sqlite3');self.db=sqlite3.connect(self.path)
        self.db.execute('PRAGMA busy_timeout=1500');self.db.executescript('''CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,digest TEXT);
        CREATE TABLE IF NOT EXISTS windows(id INTEGER PRIMARY KEY,source_id TEXT,context TEXT,suffix TEXT,phrase TEXT,area TEXT,modality TEXT,verified INTEGER,frequency INTEGER,source TEXT);
        CREATE INDEX IF NOT EXISTS context_prefix ON windows(context);CREATE INDEX IF NOT EXISTS window_source ON windows(source_id);''')
        self._closed=False;self.fts=False
        if fts:
            try:
                existed=self.db.execute("SELECT 1 FROM sqlite_master WHERE name='window_fts'").fetchone()
                self.db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS window_fts USING fts5(context,content=windows,content_rowid=id)');self.fts=True
                if not existed:self.db.execute("INSERT INTO window_fts(window_fts) VALUES('rebuild')")
            except sqlite3.OperationalError:pass
        self.generation=0;self.shortlist=None;self.query_count=0;self.lookup_times=deque(maxlen=128);self.sync()
    def records(self):
        db=self.library.db
        rows=db.execute("SELECT t.id,t.title,COALESCE(l.content,t.content),t.category FROM templates t LEFT JOIN template_layouts l ON l.template_id=t.id AND l.original_digest=raw_digest(t.content) WHERE COALESCE(l.kind,'')!='base-evidence'").fetchall()
        for key,title,body,area in rows:yield 'template:'+str(key),body,area,modality(title+' '+body[:300]),False,'Библиотека'
        for key,body,area in db.execute("SELECT rowid,text,category FROM phrases WHERE source='Личный стандарт'"):yield 'phrase:'+str(key),body,area,modality(body),True,'Личный стандарт'
        for key,body,area in db.execute('SELECT id,content,category FROM verified_standards'):yield 'verified:'+str(key),body,area,modality(body[:300]),True,'Личный стандарт'
    def sync(self):
        started=time.perf_counter();seen=set();changed=False;phrases=0;word_count=0
        with self.db:
            for key,body,area,kind,verified,source in self.records():
                seen.add(key);digest=hashlib.sha256((str(self.VERSION)+body+area+kind+str(verified)).encode()).hexdigest()
                if self.db.execute('SELECT digest FROM sources WHERE id=?',(key,)).fetchone()==(digest,):continue
                changed=True;self._delete(key)
                self.db.execute('INSERT INTO sources VALUES(?,?)',(key,digest))
                for line in safe_lines(body):
                    if META.search(line) or re.match(r'\s*(?:На серии|Методика|Исследование выполнено)',line,re.I):continue
                    for phrase in re.split(r';\s*|(?<=[.!?])\s+',line):
                        phrase=phrase.strip(' •—-\t');spans=list(WORDS.finditer(phrase))
                        if not 3<=len(spans)<=70 or len(phrase)>700:continue
                        phrases+=1;word_count+=len(spans)
                        for end in range(2,len(spans)):
                            suffix=phrase[spans[end-1].end():]
                            if not safe_suffix(suffix,phrase[:spans[end-1].end()]):continue
                            for size in (2,3,4,5):
                                start=max(0,end-size)
                                if size>end:continue
                                context=norm(phrase[spans[start].start():spans[end-1].end()])
                                cur=self.db.execute('INSERT INTO windows(source_id,context,suffix,phrase,area,modality,verified,frequency,source) VALUES(?,?,?,?,?,?,?,?,?)',(key,context,suffix,phrase,area,kind,int(verified),1,source))
                                if self.fts:self.db.execute('INSERT INTO window_fts(rowid,context) VALUES(?,?)',(cur.lastrowid,context))
            for key, in self.db.execute('SELECT id FROM sources').fetchall():
                if key not in seen:self._delete(key);changed=True
        if changed:self.generation+=1;self.shortlist=None
        self.source_versions=dict(self.db.execute('SELECT id,digest FROM sources'))
        self.library_changes=self.library.db.total_changes
        self.sync_ms=(time.perf_counter()-started)*1000
    def _delete(self,key):
        if self.fts:
            for rowid,context in self.db.execute('SELECT id,context FROM windows WHERE source_id=?',(key,)).fetchall():self.db.execute("INSERT INTO window_fts(window_fts,rowid,context) VALUES('delete',?,?)",(rowid,context))
        self.db.execute('DELETE FROM windows WHERE source_id=?',(key,));self.db.execute('DELETE FROM sources WHERE id=?',(key,))
    def retrieve(self,context,area='',kind='',limit=40):
        terms=norm(context).split()[-5:]
        if len(terms)<2:return []
        self.query_count+=1;lookup_started=time.perf_counter()
        if self.fts:
            match=' AND '.join('"'+word.replace('"','""')+'"*' for word in terms[-4:])
            rows=self.db.execute('SELECT w.*,bm25(window_fts) FROM window_fts JOIN windows w ON w.id=window_fts.rowid WHERE window_fts MATCH ? ORDER BY bm25(window_fts) LIMIT 150',(match,)).fetchall()
            if not rows:
                match=' AND '.join('"'+word+'"*' for word in terms[-2:])
                rows=self.db.execute('SELECT w.*,bm25(window_fts) FROM window_fts JOIN windows w ON w.id=window_fts.rowid WHERE window_fts MATCH ? ORDER BY bm25(window_fts) LIMIT 150',(match,)).fetchall()
            if not rows:
                match='"'+terms[-2]+'"'
                rows=self.db.execute('SELECT w.*,bm25(window_fts) FROM window_fts JOIN windows w ON w.id=window_fts.rowid WHERE window_fts MATCH ? ORDER BY bm25(window_fts) LIMIT 150',(match,)).fetchall()
        else:
            rows=self.db.execute('SELECT *,0 FROM windows WHERE context LIKE ? LIMIT 150',('%'+terms[-2]+'%',)).fetchall()
        ranked=[]
        for row in rows:
            key,source,stored,suffix,phrase,region,mode,verified,freq,label,bm=row
            st=stored.split()
            matched=False
            for length in range(min(len(terms),len(st)),1,-1):
                a,b=terms[-length:],st[-length:]
                if a[:-1]==b[:-1] and (b[-1].startswith(a[-1]) or (len(a[-1])>=4 and DamerauLevenshtein.distance(a[-1],b[-1])<=1)):
                    matched=True;break
            if not matched or not safe_suffix(suffix,context):continue
            if region and area and area!='Другие исследования' and region!=area:continue
            if mode and kind and mode!=kind:continue
            score=length*4+verified*8+(region==area)*3+(mode==kind)*2-float(bm)*.01
            ranked.append((score,{'suffix':suffix,'phrase':phrase,'source_id':source,'personal':bool(verified),'source':label,'context':stored,'id':key,'last':st[-1],'area':region,'modality':mode,'frequency':freq,'source_version':self.source_versions.get(source,'')}))
        unique={}
        for score,value in sorted(ranked,key=lambda x:-x[0]):unique.setdefault((value['context'],value['suffix']),value)
        self.lookup_times.append((time.perf_counter()-lookup_started)*1000)
        return list(unique.values())[:limit]
    def suggest(self,before,after='',area='',kind='',limit=8):
        if self.library.db.total_changes!=self.library_changes:self.sync()
        clause=re.split(r';\s*|(?<=[.!?])\s+',before)[-1]
        matches=list(WORDS.finditer(clause))
        if len(matches)<2:return []
        boundary=bool(clause[-1:].isspace() or clause[-1:] in ',;:')
        tail='' if boundary else matches[-1].group()
        anchor=clause if boundary else clause[:matches[-1].start()]
        # Cache a broad shortlist on the previous complete context. Individual letters filter RAM.
        cachekey=(norm(anchor),area,kind,self.generation,norm(after))
        if self.shortlist is None or self.shortlist[0]!=cachekey:
            query=anchor if len(WORDS.findall(anchor))>=2 else clause
            self.shortlist=(cachekey,self.retrieve(query,area,kind,60),len(WORDS.findall(anchor))<2)
        pool=self.shortlist[1];out=[]
        for item in pool:
            suffix=item['suffix']
            if tail and self.shortlist[2]:
                target=item['last'];q=norm(tail)
                if not target.startswith(q):continue
                suffix=target[len(q):]+suffix
            elif tail:
                first=WORDS.search(suffix)
                if not first:continue
                word=first.group();q=tail.casefold().replace('ё','е');w=word.casefold().replace('ё','е')
                if not w.startswith(q):continue # Never rewrite an earlier typo or a protected token.
                suffix=suffix[first.start()+len(tail):]
            elif not clause.endswith((' ', '\t')) and not suffix.startswith((' ', ',', ';', '.', ':')):suffix=' '+suffix
            if boundary and clause.endswith((' ', '\t')):suffix=suffix.lstrip()
            if item['phrase'].casefold() in getattr(self.library.ai,'excluded',()):continue
            from completion_overlap import trim_right_overlap
            suffix=trim_right_overlap(suffix,after)
            if suffix is None or not suffix.strip():continue
            if any(norm(v['suffix'])==norm(suffix) for v in out):continue
            value=dict(item);value['suffix']=suffix;out.append(value)
            if len(out)>=limit:break
        return out
    def stats(self):
        return {'fts5':self.fts,'sources':self.db.execute('SELECT count(*) FROM sources').fetchone()[0],'windows':self.db.execute('SELECT count(*) FROM windows').fetchone()[0],'unique_phrases':self.db.execute('SELECT count(DISTINCT phrase) FROM windows').fetchone()[0],'sync_ms':self.sync_ms,'index_bytes':self.path.stat().st_size}
    def close(self):
        if not self._closed:self.db.close();self._closed=True
