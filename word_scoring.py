"""Shared word-level contracts. These do not weaken whole-fragment fact validation."""
import hashlib,json,re
from rapidfuzz.distance import DamerauLevenshtein
from hybrid_safety import safe_pair,facts

WORD=re.compile(r'[А-Яа-яЁё]+')
HARD=re.compile(r'^(?:не|нет|без|прав\w*|лев\w*|справа|слева|отсутств\w*|вероятн\w*|возможн\w*|подозр\w*|умерен\w*|выражен\w*|незначитель\w*)$',re.I)
ANATOMY=('мозг','мениск','печен','позвон','почк')


def folded(text):return text.casefold().replace('ё','е')


def safe_completion(prefix,candidate,trusted):
    if not WORD.fullmatch(prefix) or not WORD.fullmatch(candidate):return False
    p,c=folded(prefix),folded(candidate)
    if len(p)<2 or len(c)<=len(p) or c not in trusted or not c.startswith(p):return False
    if HARD.fullmatch(p) or HARD.fullmatch(c):return False
    for signal in ('гипо','гипер','изоинтенсив'):
        if c.startswith(signal) and not p.startswith(signal):return False
    return True


def safe_word_correction(original,candidate,trusted):
    if safe_pair(original,candidate):return True
    if not WORD.fullmatch(original) or not WORD.fullmatch(candidate):return False
    q,c=folded(original),folded(candidate)
    # Only a missing/mistyped anatomical stem, not a different protected concept.
    if len(q)<5 or c not in trusted or q in trusted or q[0]!=c[0]:return False
    if HARD.fullmatch(q) or HARD.fullmatch(c) or facts(original):return False
    if not c.startswith(ANATOMY):return False
    return DamerauLevenshtein.distance(q,c)<=2


def word_key(word,before='',after='',area='',modality=''):
    # Preserve punctuation and case used by the scorer. Never store the source text.
    payload=['sage-word-v2',word,before.rsplit('\n',1)[-1][-180:],after.split('\n',1)[0][:180],area,modality]
    return hashlib.sha256(json.dumps(payload,ensure_ascii=True).encode()).hexdigest()


def local_window(before,word,after,neighbours=6):
    left=before.rsplit('\n',1)[-1][-180:];right=after.split('\n',1)[0][:180]
    boundary=r';|(?<!\d)\.(?!\d)'
    left=re.split(boundary,left)[-1]
    end=re.search(boundary,right)
    if end:right=right[:end.end()]
    words=list(re.finditer(r'\S+',left))
    if len(words)>neighbours:left=left[words[-neighbours].start():]
    words=list(re.finditer(r'\S+',right))
    if len(words)>neighbours:right=right[:words[neighbours-1].end()]
    return left,word,right
