"""Explicit shorthand expansions; uncertain input is never guessed locally."""
import re

NOTE_PROMPT = ('Разверни телеграфную заметку врача в профессиональную формулировку МРТ. '
    'Раскрой сокращения и согласуй слова, сохрани все факты, числа, стороны, отрицания и степень уверенности. '
    'Не дописывай отсутствующие находки и сигнальные характеристики. Неоднозначные уровни и числа '
    '(например, ь5-с1) не исправляй догадкой: оставь [уточнить: исходный фрагмент]. '
    'Сохрани порядок абзацев, начни с заглавной буквы без тире, заверши точкой. Верни только текст.')
IMPROVE_PROMPT = ('Улучши профессиональную формулировку выделенного описания МРТ. '
    'Сохрани структуру, факты, числа, единицы, стороны, уровни и отрицания. '
    'Не добавляй диагнозы, находки, последовательности и сигнальные характеристики. Верни только отредактированный текст.')

def normalized(text): return re.sub(r'\s+', ' ', text).strip().casefold()

def expand_note(text, personal=None):
    key=normalized(text)
    if personal and key in personal: return personal[key], 'Личное сокращение'
    if personal:
        from shorthand_patterns import apply_patterns
        value=apply_patterns(text,personal.get('__patterns__',[]))
        if value:return value,'Ваш проверенный образец с переменными. Проверьте новые значения.'
    # Match the complete statement, never a fragment with an unknown qualifier.
    match=re.fullmatch(r'зад(?:няя)?\s+цент(?:ральная)?\s+(прот(?:рузия)?|грыжа)\s+(?:диска\s+)?'
        r'([ctl][1-9]\d?|th[1-9]\d?)\s*[-–—]\s*([ctls][1-9]\d?|th[1-9]\d?)\s+'
        r'до\s*(\d+(?:[.,]\d+)?)\s*мм(?:\s*[,;]?\s*(?:с\s*)?лок(?:альной)?\s+деформ(?:ацией)?\s+дура(?:льного)?\s+мешка)?[.;]?',key)
    if not match: return None, 'Не удалось однозначно распознать всю заметку. Уточните запись или откройте GigaChat.'
    finding,first,last,size=match.groups()
    # Only conventional adjacent disc levels. Cyrillic lookalikes are deliberately not inferred.
    def level(value):
        m=re.fullmatch(r'(th|[ctls])(\d+)',value);return m.group(1),int(m.group(2))
    a,b=level(first),level(last)
    limits={'c':7,'t':12,'th':12,'l':5,'s':1}
    valid=a[1]<=limits[a[0]] and b[1]<=limits[b[0]] and ((a[0]==b[0] and b[1]==a[1]+1)
        or (a==('l',5) and b==('s',1)) or (a==('c',7) and b in [('t',1),('th',1)]))
    if not valid: return None,'Проверьте уровень диска: автоматическая подстановка не выполнена.'
    noun='протрузия' if finding.startswith('прот') else 'грыжа'
    suffix=', с локальной деформацией дурального мешка' if re.search(r'(?:^|\s)(?:с\s*)?лок',key) else ''
    return f'Задняя центральная {noun} диска {first.upper()}–{last.upper()} до {size} мм{suffix}.','Распознано локально. Проверьте перед применением.'
