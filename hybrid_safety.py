"""Independent gates: neural scores never authorize new clinical content."""
import json
import re
from collections import Counter

PROTECTED = re.compile(r'\d+(?:[.,]\d+)?|\b(?:[a-z]+\d*[a-z]*|мм|см|мл|мг|не|нет|без|отсутств\w*|прав\w*|лев\w*|справа|слева|умерен\w*|выражен\w*|незначитель\w*|вероятн\w*|возможн\w*|подозр\w*|гипер\w*|гипо\w*|изоинтенсив\w*|грыж\w*|протрузи\w*|опухол\w*|метастаз\w*|очаг\w*|отек\w*|отёк\w*|стеноз\w*|кист\w*|инфаркт\w*|кровоизлияни\w*|ишеми\w*|демиелинизаци\w*|печен\w*|почк\w*|мозг\w*|позвон\w*|мениск\w*)\b', re.I)

def facts(text):
    return Counter(m.group().casefold().replace('ё','е') for m in PROTECTED.finditer(text))

def safe_pair(original, replacement):
    if re.fullmatch('[A-Za-z]{5,}',original):
        mapped=original.casefold().translate(str.maketrans('qwertyuiopasdfghjklzxcvbnm','йцукенгшщзфывапролдячсмить'))
        if mapped==replacement.casefold():return True
    # A confirmed word-level inflection/typo may preserve the same medical concept.
    # Never use this exception for whole-sentence rewrites or opposite signal/side terms.
    if re.fullmatch('[А-Яа-яЁё]+',original) and re.fullmatch('[А-Яа-яЁё]+',replacement):
        roots=('гиперинтенсив','гипоинтенсив','гипер','гипо','изоинтенсив','протрузи','грыж','демиелинизаци','мениск','позвон','печен','почк')
        from rapidfuzz.distance import DamerauLevenshtein
        if DamerauLevenshtein.distance(original.casefold(),replacement.casefold())<=2:
            for root in roots:
                if original.casefold().startswith(root) and replacement.casefold().startswith(root):return True
    return facts(original) == facts(replacement) and bool(replacement.strip())

def validate_choice(raw, count):
    obj=json.loads(raw)
    if not isinstance(obj,dict) or set(obj)!={'choice'} or type(obj['choice']) is not int:
        raise ValueError('Invalid choice schema')
    if not -1 <= obj['choice'] < count: raise ValueError('Choice outside candidate set')
    return obj['choice']

def language_example(text):
    # RAG is exclusively short, explicitly verified language without facts/identifiers.
    from radiology_ai import SENSITIVE, safe_lines
    return 8 <= len(text) <= 180 and not SENSITIVE.search(text) and not re.search(r'\d|[<>\[\]{}]|[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.',text) and list(safe_lines(text))==[text] and not facts(text)
