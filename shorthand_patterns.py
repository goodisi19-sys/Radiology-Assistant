"""Explicitly approved variable examples; never infer ambiguous identifiers."""
import re
from decimal import Decimal,InvalidOperation
VALUE=re.compile(r'(?<!\w)(?:[CLTSclts]\d{1,2}\s*[-–—]\s*[CLTSclts]\d{1,2}|[-+−]?\d+(?:[.,]\d+)?)(?!\d)')
LEVEL=r'[CLTSclts]\d{1,2}\s*[-–—]\s*[CLTSclts]\d{1,2}'
NUMBER=r'\d+(?:[.,]\d+)?'
def canonical(value):
    if re.search('[CLTSclts]',value):return re.sub(r'\s|[-–—]','',value).upper()
    return Decimal(value.replace(',','.').replace('−','-'))
def make_pattern(source,result):
    left=list(VALUE.finditer(source));right=list(VALUE.finditer(result))
    if not left or len(left)!=len(right):return None
    for text,matches in ((source,left),(result,right)):
        if any(m.start()>0 and text[m.start()-1] in '+-−' and m.group()[0].isdigit() for m in matches):return None
    if [canonical(m.group()) for m in left]!=[canonical(m.group()) for m in right]:return None
    units=lambda text:re.findall(r'(?<![а-яё])(?:мм|см|мл)(?![а-яё])',text,re.I)
    if units(source)!=units(result):return None
    chunks=[];position=0
    for index,match in enumerate(left):
        chunks.append(re.escape(source[position:match.start()]))
        chunks.append('(?P<v'+str(index)+'>'+ (LEVEL if re.search('[CLTSclts]',match.group()) else NUMBER)+')')
        position=match.end()
    chunks.append(re.escape(source[position:]))
    parts=[];position=0
    for index,match in enumerate(right):
        parts.append(result[position:match.start()]);parts.append({'slot':'v'+str(index)})
        position=match.end()
    parts.append(result[position:])
    return {'regex':''.join(chunks),'parts':parts}
def apply_patterns(text,patterns):
    for pattern in reversed(patterns):
        try:
            match=re.fullmatch(pattern['regex'],text.strip(),re.I)
            if match:return ''.join(part if isinstance(part,str) else match.group(part['slot']) for part in pattern['parts'])
        except (re.error,KeyError,TypeError):continue
    return None
