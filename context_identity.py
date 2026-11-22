import hashlib,json,re

def norm(text):
    return " ".join(re.findall(r"[а-яёa-z0-9]+",text.casefold().replace("ё","е")))

def context_key(task,left,right='',area='',kind='',candidates=(),model='v1'):
    value=[task,norm(left[-500:]),norm(right[:300]),area,kind,model,sorted(set(candidates))]
    return hashlib.sha256(json.dumps(value,ensure_ascii=True).encode()).hexdigest()
