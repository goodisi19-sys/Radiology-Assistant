"""Deterministic draft checks. Findings are prompts for review, never corrections."""
from dataclasses import dataclass
import re

@dataclass(frozen=True)
class Finding:
    start: int
    end: int
    message: str
    possible: bool = False
    related: tuple = ()
    category: str = "medical"

SIDE = r'(?:прав(?:ый|ая|ое|ые|ого|ой|ому|ую|ым|ом|ых|ыми)|лев(?:ый|ая|ое|ые|ого|ой|ому|ую|ым|ом|ых|ыми))'
OPTIONS = re.compile(r'\b'+SIDE+r'(?:\s*/\s*|\s*\(\s*|[ \t]+(?:или[ \t]+)?)'+SIDE+r'\b\)?', re.I)
EMPTY = re.compile(r'_{2,}|\.{3,}|…|\[\s*(?:сторона|размеры?|значение|впишите[^\]\n]*)?\s*\]|\b(?:до|размерами|размером)\s+(?=(?:мм|см|мл)\b)|[×хx]\s*(?=(?:мм|см)\b)', re.I)
ENTITIES = {
    'коленный сустав': r'коленн\w*', 'плечевой сустав': r'плечев\w*',
    'тазобедренный сустав': r'тазобедренн\w*', 'голеностопный сустав': r'голеностопн\w*',
    'локтевой сустав': r'локтев\w*', 'лучезапястный сустав': r'лучезапястн\w*',
    'почка': r'почк\w*',
}


def check_protocol(text):
    findings = []
    options = list(OPTIONS.finditer(text))
    for match in options:
        findings.append(Finding(match.start(), match.end(), 'Оставлен вариант шаблона: выберите нужную формулировку'))
    for match in EMPTY.finditer(text):
        findings.append(Finding(match.start(), match.end(), 'Возможно, поле или размер не заполнены'))
    for match in re.finditer(r'(?im)^[ \t]*(?:(?:размеры|сторона|контрастирование)[ \t]*:[ \t]*|[-•–—][ \t]*)$', text):
        findings.append(Finding(match.start(), match.end(), 'Незаполненный пункт шаблона'))
    alternative=r'(?:однородн|неоднородн|сохран|измен|увелич|снижен|повышен)\w*'
    for match in re.finditer(r'\b'+alternative+r'\s*(?:/|или)\s*(?:не\s+)?'+alternative+r'\b',text,re.I):
        findings.append(Finding(match.start(),match.end(),'Возможно, оставлен альтернативный вариант шаблона',True))
    heading = re.search(r'(?im)^[ \t]*заключение[ \t]*(?:[:：]|$)|\bзаключение[ \t]*[:：]', text)
    if heading:
        sections = [(text[:heading.start()], 0), (text[heading.end():], heading.end())]
        by_section = []
        for section, offset in sections:
            entities = {}
            for side in re.finditer(r'\b'+SIDE+r'\b', section, re.I):
                start, end = offset+side.start(), offset+side.end()
                if any(m.start() <= start < m.end() for m in options): continue
                # Only the adjacent noun phrase can establish the organ. Never cross a clause.
                before = section[max(0, side.start()-65):side.start()]
                candidates = []
                for entity, noun in ENTITIES.items():
                    after = re.match(r'\s+(?:(?:и|или)\s+)?(?:'+noun+r')\b', section[side.end():], re.I)
                    previous = re.search(r'\b(?:'+noun+r')(?:\s+сустав\w*)?\s*$', before, re.I)
                    if after or previous: candidates.append(entity)
                if len(candidates) != 1: continue
                entity = candidates[0]
                entities.setdefault(entity, {}).setdefault('right' if side.group().casefold().startswith('прав') else 'left', []).append((start,end))
            by_section.append(entities)
        # Bilateral wording can refer to several organs; abstain rather than invent a conflict.
        if not re.search(r'двусторонн|с\s+обеих\s+сторон|оба\s+сустава|обе\s+почки', text, re.I):
            for entity in by_section[0].keys() & by_section[1].keys():
                description, conclusion = by_section[0][entity], by_section[1][entity]
                if len(description) == len(conclusion) == 1 and set(description) != set(conclusion):
                    related = tuple(next(iter(description.values())) + next(iter(conclusion.values())))
                    start,end = related[-1]
                    findings.append(Finding(start,end, 'Возможное несоответствие стороны: '+entity+' — сверьте описание и заключение', True, related))
    return sorted(findings, key=lambda item: (item.start,item.end))


def qt_offset(text, offset):
    return len(text[:offset].encode('utf-16-le')) // 2


def create_dialog(window):
    from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QPushButton, QTextEdit
    from PySide6.QtGui import QTextCursor, QColor
    class CheckDialog(QDialog):
        def __init__(self):
            super().__init__(window)
            self.setWindowTitle('Проверка протокола'); self.resize(760,430)
            layout = QVBoxLayout(self)
            intro = QLabel('Синий — язык и согласование; жёлтый — пустые поля; оранжевый — возможное медицинское несоответствие.\n'
                'Проверка по правилам может пропустить ошибку или выделить допустимую запись. Текст не меняется.')
            intro.setWordWrap(True); layout.addWidget(intro)
            self.issues = QListWidget(); layout.addWidget(self.issues)
            self.status = QLabel(); layout.addWidget(self.status)
            row = QHBoxLayout(); layout.addLayout(row)
            refresh = QPushButton('Проверить заново'); refresh.clicked.connect(self.scan); row.addWidget(refresh)
            close = QPushButton('Закрыть'); close.clicked.connect(self.close); row.addWidget(close)
            self.issues.currentRowChanged.connect(self.select)
            window.editor.textChanged.connect(self.invalidate)
            self.snapshot = ''; self.matches = []
        def invalidate(self):
            window.editor.setExtraSelections([])
            self.issues.setEnabled(False)
            self.status.setText('Текст изменился. Нажмите «Проверить заново».')
        def scan(self):
            self.snapshot = window.editor.toPlainText()
            self.matches = check_protocol(self.snapshot) if window.library.ai.enabled('medical_check') else []
            if window.library.ai.enabled('medical_check'):self.matches+=consistency_findings(self.snapshot)
            if window.library.ai.enabled('grammar_warnings'):self.matches+=language_findings(self.snapshot)
            self.issues.clear(); self.issues.setEnabled(True)
            selections = []
            for issue in self.matches:
                line = self.snapshot.count('\n',0,issue.start)+1
                self.issues.addItem(f'[{issue.category}] Строка {line}: {issue.message}')
                for left,right in issue.related or ((issue.start,issue.end),):
                    item = QTextEdit.ExtraSelection()
                    item.cursor = QTextCursor(window.editor.document())
                    item.cursor.setPosition(qt_offset(self.snapshot,left))
                    item.cursor.setPosition(qt_offset(self.snapshot,right), QTextCursor.MoveMode.KeepAnchor)
                    item.format.setBackground(QColor('#d6e7ff' if issue.category=='grammar' else '#ffd19a' if issue.possible else '#fff29a'))
                    item.format.setForeground(QColor('#18202b')); selections.append(item)
            window.editor.setExtraSelections(selections)
            self.status.setText(f'Замечаний: {len(self.matches)}.' if self.matches else 'Правила не нашли замечаний. Это не подтверждает полноту или медицинскую корректность протокола.')
            if self.matches: self.issues.setCurrentRow(0)
        def select(self,index):
            if not 0 <= index < len(self.matches) or self.snapshot != window.editor.toPlainText(): return
            issue = self.matches[index]; cursor = window.editor.textCursor()
            cursor.setPosition(qt_offset(self.snapshot,issue.start))
            cursor.setPosition(qt_offset(self.snapshot,issue.end), QTextCursor.MoveMode.KeepAnchor)
            window.editor.setTextCursor(cursor); window.editor.ensureCursorVisible()
        def done(self,result):
            window.editor.setExtraSelections([]); super().done(result)
        def closeEvent(self,event):
            window.editor.setExtraSelections([]); super().closeEvent(event)
    return CheckDialog()

# Separate, conservative language/review rules. Never rewrite clinical facts.
def language_findings(text):
    result=[]
    for m in re.finditer(r'\b([А-Яа-яЁё]{2,})[ \t]+\1\b',text,re.I):
        result.append(Finding(m.start(),m.end(),'Повтор слова: '+m.group(1)))
    previous=None
    for m in re.finditer(r'[^.!?\n]+[.!?]?',text):
        value=m.group().strip().casefold()
        if len(value)>12 and value==previous:result.append(Finding(m.start(),m.end(),'Возможный повтор предложения'))
        previous=value
    for m in re.finditer(r'\b(?:срединные структура|контуры ровный|размеры сохранен|структура однородные)\b',text,re.I):
        result.append(Finding(m.start(),m.end(),'Возможная ошибка согласования — проверьте окончания',True))
    from medical_grammar import candidates
    for start,end,_,_ in candidates(text):
        if not any(x.start<=start and x.end>=end for x in result):
            result.append(Finding(start,end,'Возможная ошибка согласования — проверьте окончание',True))
    for m in re.finditer(r'(?m)\S[^\n]{15,}(?<![.;:!?])$',text):
        if not re.match(r'\s*(?:Методика|На серии|Исследование выполнено)',m.group(),re.I):
            result.append(Finding(m.end()-1,m.end(),'Возможно, пропущен знак в конце строки',True))
    return [Finding(x.start,x.end,x.message,x.possible,x.related,'grammar') for x in result]


def consistency_findings(text):
    heading=re.search(r'(?im)^\s*заключение\s*[:：]',text)
    if not heading:return []
    desc,conclusion=text[:heading.start()],text[heading.end():];out=[]
    from protocol_context import ProtocolContextState,conflicts
    out.extend(Finding(a,b,message,True,related) for a,b,message,related in conflicts(ProtocolContextState().update(text)))
    level=r'\b(?:C|Th|T|L|S)\d{1,2}\s*[-–]\s*(?:C|Th|T|L|S)\d{1,2}\b'
    a=set(re.findall(level,desc,re.I));b=set(re.findall(level,conclusion,re.I))
    uncertain=re.search(r'не\s+исключ|вероятн|возможн|подозр|\?',text,re.I)
    if not uncertain and not any('уровня' in item.message for item in out) and len(a)==len(b)==1 and {v.upper().replace('TH','T').replace(' ','') for v in a}!={v.upper().replace('TH','T').replace(' ','') for v in b}:
        out.append(Finding(heading.end(),len(text),'Возможное несоответствие анатомического уровня — сверьте описание и заключение',True))
    for subject in ('выпот','отек','перелом','грыжа'):
        states=[]
        for section in (desc,conclusion):
            states.append(set(bool(m[1]) for m in re.finditer(r'\b'+subject+r'\s+(не\s+)?(?:определяется|выявлен\w*)',section,re.I)))
        if not uncertain and all(len(x)==1 for x in states) and states[0]!=states[1]:
            out.append(Finding(heading.end(),len(text),'Возможное противоречие отрицания: '+subject+' — требуется проверка врача',True))
    return out
