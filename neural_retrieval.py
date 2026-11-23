"""Shared bounded lexical shortlist for neural retrieval and its measurements."""
from rapidfuzz import fuzz
from radiology_ai import classify,normalized


def shortlist(ai,query,rows,limit=60):
    lexical=ai.search(query,rows,limit=limit)
    area=classify(query);known=area!='Другие исследования'
    q=normalized(query)
    fallback=sorted(rows,key=lambda r:(known and len(r)>2 and str(r[2])==area,fuzz.WRatio(q,normalized(' '.join(str(v) for v in r[1:])[:1500]))),reverse=True)
    selected={r[0]:r for r in lexical}
    for row in fallback:selected.setdefault(row[0],row)
    return tuple(list(selected.values())[:limit])
