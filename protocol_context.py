"""Revision-scoped clinical evidence in RAM. Ambiguous associations deliberately abstain."""
from dataclasses import dataclass,replace
from collections import defaultdict
import re
from radiology_ai import classify,modality

STRUCTURES={'почка':r'почк\w*','печень':r'печен\w*','головной мозг':r'головн\w*\s+мозг\w*','желудочки':r'желудоч\w*','коленный сустав':r'коленн\w*','плечевой сустав':r'плечев\w*','мениск':r'мениск\w*','диск':r'диск\w*','простата':r'предстател\w*|простат\w*','матка':r'матк\w*'}
LESIONS={'киста':r'кист\w*','очаг':r'очаг\w*','грыжа':r'грыж\w*','протрузия':r'протрузи\w*','отек':r'от[её]к\w*','перелом':r'перелом\w*','образование':r'образовани\w*','стеноз':r'стеноз\w*'}
LEVEL=re.compile(r'\b(?:Th|[CTLS])\d{1,2}(?:\s*[-–]\s*(?:Th|[CTLS])\d{1,2})?\b',re.I)
MEASURE=re.compile(r'(?<!\w)(\d+(?:[.,]\d+)?(?:\s*[xх×]\s*\d+(?:[.,]\d+)?){0,2})\s*(мм|см)\b',re.I)
@dataclass(frozen=True)
class Fact:
    structure:str;finding:str;side:str;levels:tuple;sizes:tuple;polarity:str;location:str;section:str;start:int;end:int;ambiguous:bool=False

def extract_block(text,section):
    out=[]
    for m in re.finditer(r'[^;\n]+?(?:;|(?<!\d)\.(?!\d)|$)',text):
        clause=m.group();structures=[k for k,p in STRUCTURES.items() if re.search(p,clause,re.I)]
        lesions=[k for k,p in LESIONS.items() if re.search(p,clause,re.I)]
        if not lesions:continue
        sides=set('right' if x.group().lower().startswith(('прав','справа')) else 'left' for x in re.finditer(r'\b(?:прав\w*|лев\w*|справа|слева)\b',clause,re.I))
        bilateral=bool(re.search(r'двусторонн|обе\s+почк|оба\s+сустав|обеих',clause,re.I))
        side='bilateral' if bilateral else next(iter(sides)) if len(sides)==1 else ''
        uncertain=bool(re.search(r'не\s+исключ|исключить|вероятн|возможн|подозр|\?',clause,re.I))
        alternatives=bool(re.search(r'/|\bили\b|_{2,}|\[',clause))
        absent=bool(re.search(r'без\s+(?:признаков\s+)?|не\s+(?:выявл|определя|обнаруж)|отсутств',clause,re.I))
        polarity='alternative' if alternatives else 'uncertain' if uncertain else 'absent' if absent else 'present'
        sizes=[]
        for size in MEASURE.finditer(clause):
            factor=10 if size[2].lower()=='см' else 1
            sizes.append(tuple(sorted(round(float(v.replace(',','.'))*factor,4) for v in re.split(r'\s*[xх×]\s*',size[1]))))
        location='upper' if re.search(r'верхн\w*\s+полюс',clause,re.I) else 'lower' if re.search(r'нижн\w*\s+полюс',clause,re.I) else ''
        levels=tuple(sorted(v.group().upper().replace(' ','').replace('–','-') for v in LEVEL.finditer(clause)))
        ambiguous=len(lesions)>1 or len(sizes)>1 or len(sides)>1 or len(structures)>1
        # A disc and its named level are sufficient; a generic lesion without an organ is unknown.
        structure=structures[0] if len(structures)==1 else 'диск' if levels and not structures else ''
        for lesion in lesions:out.append(Fact(structure,lesion,side,levels,tuple(sizes),polarity,location,section,m.start(),m.end(),ambiguous))
    return tuple(out)

class ProtocolContextState:
    def __init__(self):self.text='';self.revision=0;self.cache={};self.facts=();self.area='';self.modality='';self.section='description';self.changed_blocks=0
    def update(self,text,revision=None):
        if text==self.text and (revision is None or revision==self.revision):
            self.changed_blocks=0;return self
        self.revision=self.revision+1 if revision is None else revision;self.text=text
        section='description';offset=0;facts=[];active={};changed=0
        for block in text.splitlines(keepends=True):
            if section=='method':section='description'
            if re.search(r'(?i)^\s*заключение\s*[:：]',block):section='conclusion'
            elif re.search(r'(?i)^\s*описание\s*[:：]',block):section='description'
            elif re.search(r'(?i)^\s*методика\s*[:：]',block):section='method'
            key=(block,section)
            if key not in self.cache:changed+=1
            local=self.cache.get(key)
            if local is None:local=extract_block(block,section)
            active[key]=local;facts.extend(replace(f,start=f.start+offset,end=f.end+offset) for f in local);offset+=len(block)
        self.cache=dict(list(active.items())[-2048:]);self.facts=tuple(facts);self.changed_blocks=changed
        self.area=classify(text);self.modality=modality(text);self.section=section
        return self
    def at(self,position):
        before=self.text[:position];head=re.findall(r'(?im)^\s*(описание|заключение|методика)\s*[:：]',before)
        section={'описание':'description','заключение':'conclusion','методика':'method'}.get(head[-1].lower(),'description') if head else 'description'
        current=before.rsplit('\n',1)[-1]
        if section=='method' and not re.match(r'(?i)^\s*методика\s*[:：]',current):section='description'
        if re.match(r'(?i)^\s*(?:на серии|исследование выполнено)',current):section='method'
        return {'area':self.area,'modality':self.modality,'section':section,'revision':self.revision}
    def clear(self):self.__init__()

def conflicts(state):
    groups=defaultdict(lambda:defaultdict(list))
    for f in state.facts:
        if f.structure and not f.ambiguous and f.polarity not in ('uncertain','alternative') and f.section in ('description','conclusion'):
            groups[(f.structure,f.finding)][f.section].append(f)
    result=[]
    for (organ,finding),sections in groups.items():
        desc,conc=sections['description'],sections['conclusion']
        for right in conc:
            candidates=[left for left in desc if left.side==right.side and left.location==right.location and (left.levels==right.levels or not left.levels or not right.levels)]
            if not candidates and len(desc)==len(conc)==1:candidates=desc
            if len(candidates)!=1:continue
            left=candidates[0];issues=[]
            if left.polarity!=right.polarity:issues.append('отрицания')
            if left.side and right.side and left.side!=right.side and 'bilateral' not in (left.side,right.side):issues.append('стороны')
            if left.levels and right.levels and left.levels!=right.levels:issues.append('уровня')
            if left.sizes and right.sizes and left.sizes!=right.sizes:issues.append('размеров')
            if issues:result.append((right.start,right.end,'Возможное несоответствие '+', '.join(issues)+': '+organ+', '+finding,((left.start,left.end),(right.start,right.end))))
    return result
