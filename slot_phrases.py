"""Doctor-selected smart continuation slots. Never copy numerical patient findings."""
import re

SLOT_RE = re.compile(r'\[(?:уровень|размер|сторона|значение|находка)\]')
BAD_SOURCE = re.compile(r'_{2,}|…|\.{3,}')
LEVEL = re.compile(r'\b(?:Th|C|T|L|S)\s*\d{1,2}(?:\s*[-–]\s*(?:Th|C|T|L|S)\s*\d{1,2})?\b', re.I)
DIMENSIONS = re.compile(r'(?<!\w)\d+(?:[.,]\d+)?(?:\s*[xх×]\s*\d+(?:[.,]\d+)?){1,2}(?:\s*(?:мм|см|мл))?\b', re.I)
MEASUREMENT = re.compile(r'(?<!\w)\d+(?:[.,]\d+)?\s*(?:мм|см|мл)\b', re.I)
SIDE = re.compile(r'\b(?:справа|слева|двусторонн\w*|прав(?:ый|ая|ое|ые|ого|ой|ому|ую|ым|ом|ых|ыми)|лев(?:ый|ая|ое|ые|ого|ой|ому|ую|ым|ом|ых|ыми))\b', re.I)
NUMBER = re.compile(r'(?<!\w)\d+(?:[.,]\d+)?(?!\w)')
FINDING_ROOTS = ('грыж','протрузи','кист','очаг','метастаз','опухол','инфаркт',
                 'ишеми','демиелинизац','кровоизлияни','перелом','выпот','стеноз',
                 'синовит','артроз','новообразовани')
FINDING = re.compile(r'\b(?:'+'|'.join(s+r'\w*' for s in FINDING_ROOTS)+r')\b',re.I)
UNFILLED = re.compile(r'\b(?:до|размером|размерами)\s+(?:мм|см|мл)\b',re.I)

def slots_from_source(value, preceding=''):
    """Safely retain source prose with variable sides, levels, sizes and new findings."""
    if not value or BAD_SOURCE.search(value):return None
    leftover=SLOT_RE.sub('',value)
    if '[' in leftover or ']' in leftover:return None
    value=DIMENSIONS.sub('[размер]',value)
    value=LEVEL.sub('[уровень]',value)
    value=MEASUREMENT.sub('[размер]',value)
    value=SIDE.sub('[сторона]',value)
    value=NUMBER.sub('[значение]',value)
    context=preceding.casefold().replace('ё','е')
    def finding_slot(match):
        word=match.group().casefold().replace('ё','е')
        root=next((s for s in FINDING_ROOTS if word.startswith(s)),None)
        return match.group() if root and root in context else '[находка]'
    return FINDING.sub(finding_slot,value)

def safe_slot_suffix(value):
    if not value or not value.strip() or len(value)>320 or BAD_SOURCE.search(value):return False
    leftover=SLOT_RE.sub('',value)
    return not (re.search(r'[\[\]]',leftover) or NUMBER.search(leftover)
                or LEVEL.search(leftover) or SIDE.search(leftover)
                or UNFILLED.search(leftover))
