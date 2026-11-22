"""Portable term cache. Retrieved text is evidence, never automatically verified knowledge."""
import datetime,json,os,re,tempfile
from pathlib import Path

class MedicalGlossary:
    def __init__(self,path):
        self.path=Path(path);self.records={};self.error=''
        if self.path.exists():
            try:
                data=json.loads(self.path.read_text(encoding='utf8'))
                if not isinstance(data,dict):raise ValueError('Invalid glossary')
                self.records={k:v for k,v in data.items() if isinstance(k,str) and isinstance(v,dict) and isinstance(v.get('definition'),str) and type(v.get('verified')) is bool}
            except (OSError,ValueError):self.error='Словарь повреждён: исходный файл сохранён, запись отключена.'
    def save(self,term,definition,source,verified=False,evidence='manual'):
        if self.error:raise ValueError(self.error)
        term=term.strip().casefold()
        if not term or len(term)>90 or not definition.strip():raise ValueError('Нужен термин и определение')
        existing=self.records.get(term)
        if existing and existing['verified'] and not verified:return # Never replace reviewed knowledge with search output.
        updated=dict(self.records);updated[term]={'definition':definition.strip()[:4000],'verified':bool(verified),'updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source':source[:1000],'evidence':'physician-reviewed' if verified else evidence}
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix='.med-glossary-',dir=self.path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf8') as f:json.dump(updated,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
            os.replace(name,self.path);self.records=updated
        finally:Path(name).unlink(missing_ok=True)
    def verified_context(self,text,limit=2):
        result=[]
        for term,record in self.records.items():
            if record['verified'] and re.search(r'(?<!\w)'+re.escape(term)+r'(?!\w)',text,re.I):result.append((term,record['definition'][:240]))
            if len(result)>=limit:break
        return result
    def verified_words(self):
        return {w.casefold() for term,r in self.records.items() if r['verified'] for w in re.findall('[А-Яа-яЁё]{3,}',term)}
