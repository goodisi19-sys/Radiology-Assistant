"""Conservative candidate generation; no diagnoses or clinical facts are rewritten."""
import re
RULES=[
 (r'\bконтуры\s+(ровный)\b','ровные'),
 (r'\bсрединные\s+(структура)\b','структуры'),
 (r'\bструктура\s+(однородные)\b','однородная'),
 (r'\bсуставная\s+щель\s+(сужен|сужены|сужено)\b','сужена'),
 (r'\bсиновиальная\s+оболочка\s+(утолщен|утолщены)\b','утолщена'),
 (r'\bмежпозвонковые\s+диски\s+(снижен)\b','снижены'),
]
def candidates(text):
    result=[]
    for regex,replacement in RULES:
        for m in re.finditer(regex,text,re.I):
            word=m.group(1);value=replacement.capitalize() if word[:1].isupper() else replacement
            result.append((m.start(1),m.end(1),word,value))
    return result
