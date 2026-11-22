"""Offline Russian spellchecking. Suggestions never modify reports automatically."""
from dataclasses import dataclass
from functools import lru_cache
from itertools import islice
from pathlib import Path
import re
import sys
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
                              QListWidgetItem, QComboBox, QPushButton)

WORD = re.compile(r'(?<![\w])[А-Яа-яЁё]+(?:[-–][А-Яа-яЁё]+)*(?![\w])')
MEDICAL_WORDS = set('''МРТ КТ МР МРА МРХПГ МРХГ МРТХПГ ОМТ ШОП ГОП ПОП
ликвор мениск мениска мениски менисков менисками мениске
протрузия протрузии протрузий протрузиями протрузию
экструзия экструзии экструзий экструзию
спондилоартроз спондилоартроза спондилез спондилеза
антеролистез антеролистеза ретролистез ретролистеза
остеофит остеофиты остеофитов глиоз глиоза лейкоареоз
ахиллобурсит ахиллобурсита теносиновит теносиновита
лигаментоз лигаментоза гонартроз гонартроза
'''.casefold().split())
STEMS = ('гиперинтенсивн', 'гипоинтенсивн', 'изоинтенсивн', 'паравертебральн',
         'перивентрикулярн', 'субкортикальн', 'интрамедуллярн', 'субхондральн',
         'интраменисков', 'супрапателлярн', 'парамедианн', 'фораминальн')
ENDINGS = ('ый', 'ая', 'ое', 'ые', 'ого', 'ой', 'ых', 'ым', 'ыми', 'ом', 'ую')
MEDICAL_WORDS.update(stem + ending for stem in STEMS for ending in ENDINGS)


@lru_cache(maxsize=1)
def dictionary():
    from spylls.hunspell import Dictionary
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
    return Dictionary.from_files(str(root / 'spelling_data' / 'ru_RU'))


@lru_cache(maxsize=20000)
def known_word(word): return dictionary().lookup(word)


@dataclass(frozen=True)
class Typo:
    word: str
    start: int
    end: int
    line: int


def find_typos(text, personal=()):
    accepted = MEDICAL_WORDS | {word.casefold() for word in personal}
    issues = []
    for match in WORD.finditer(text):
        word = match.group()
        if len(word) < 3 or (word.isupper() and len(word) <= 5) or word.casefold() in accepted: continue
        if known_word(word) or known_word(word.casefold()): continue
        parts = re.split('[-–]', word)
        if len(parts) > 1 and all(len(part) < 3 or part.isupper() or part.casefold() in accepted
                                 or known_word(part.casefold()) for part in parts): continue
        issues.append(Typo(word, match.start(), match.end(), text.count('\n', 0, match.start()) + 1))
    return issues


@lru_cache(maxsize=4096)
def suggest(word):
    values = list(islice(dictionary().suggest(word.casefold()), 6))
    if word.isupper(): values = [value.upper() for value in values]
    elif word[:1].isupper(): values = [value[:1].upper() + value[1:] for value in values]
    return tuple(values)


def qt_offset(text, offset): return len(text[:offset].encode('utf-16-le')) // 2


class SpellingDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle('Проверка опечаток')
        self.resize(700, 520)
        layout = QVBoxLayout(self)
        intro = QLabel('Возможные опечатки по русскому словарю. Медицинский термин может быть верным.\n'
                       'Автоматических замен нет: проверьте слово и выберите исправление.')
        intro.setWordWrap(True); layout.addWidget(intro)
        self.issues = QListWidget(); layout.addWidget(self.issues, 1)
        self.issues.currentRowChanged.connect(self.select_issue)
        row = QHBoxLayout(); layout.addLayout(row)
        self.suggestions = QComboBox(); self.suggestions.setEditable(True); row.addWidget(self.suggestions, 1)
        self.replace = QPushButton('Заменить это слово'); self.replace.clicked.connect(self.replace_word); row.addWidget(self.replace)
        row = QHBoxLayout(); layout.addLayout(row)
        self.add = QPushButton('Добавить в личный словарь'); self.add.clicked.connect(self.add_word); row.addWidget(self.add)
        scan = QPushButton('Проверить заново'); scan.clicked.connect(self.scan); row.addWidget(scan)
        close = QPushButton('Закрыть'); close.clicked.connect(self.close); row.addWidget(close)
        self.status = QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.snapshot = ''
        self.matches = []

    def scan(self):
        self.snapshot = self.window.editor.toPlainText()
        db = self.window.library.db
        personal = {row[0] for row in db.execute('SELECT word FROM spelling_words')}
        # User-verified standards are an explicit personal vocabulary source.
        for (content,) in db.execute('SELECT content FROM verified_standards'):
            personal.update(match.group() for match in WORD.finditer(content))
        self.matches = find_typos(self.snapshot, personal)
        self.issues.clear()
        for issue in self.matches:
            self.issues.addItem(QListWidgetItem(f'{issue.word} — строка {issue.line}'))
        self.replace.setEnabled(bool(self.matches)); self.add.setEnabled(bool(self.matches))
        self.status.setText(f'Возможных опечаток: {len(self.matches)}. Изменения вносятся только вручную.'
                            if self.matches else 'Словарь не нашёл возможных опечаток. Это не проверка медицинского смысла.')
        if self.matches: self.issues.setCurrentRow(0)
        else: self.suggestions.clear()

    def select_issue(self, index):
        self.suggestions.clear()
        if index < 0 or index >= len(self.matches): return
        issue = self.matches[index]
        self.suggestions.addItems(suggest(issue.word))
        if self.window.editor.toPlainText() != self.snapshot: return
        cursor = self.window.editor.textCursor()
        cursor.setPosition(qt_offset(self.snapshot, issue.start))
        cursor.setPosition(qt_offset(self.snapshot, issue.end), QTextCursor.MoveMode.KeepAnchor)
        self.window.editor.setTextCursor(cursor)
        self.window.editor.ensureCursorVisible()

    def replace_word(self):
        index = self.issues.currentRow()
        if index < 0 or index >= len(self.matches): return
        if self.window.editor.toPlainText() != self.snapshot:
            self.scan(); self.status.setText('Документ изменился. Список обновлён; выберите слово заново.'); return
        replacement = self.suggestions.currentText().strip()
        if not replacement: return
        issue = self.matches[index]
        cursor = QTextCursor(self.window.editor.document())
        cursor.setPosition(qt_offset(self.snapshot, issue.start))
        cursor.setPosition(qt_offset(self.snapshot, issue.end), QTextCursor.MoveMode.KeepAnchor)
        cursor.beginEditBlock(); cursor.insertText(replacement); cursor.endEditBlock()
        self.scan()

    def add_word(self):
        index = self.issues.currentRow()
        if index < 0 or index >= len(self.matches): return
        self.window.library.db.execute('INSERT OR IGNORE INTO spelling_words(word) VALUES(?)', (self.matches[index].word.casefold(),))
        self.window.library.db.commit()
        self.window.live_spelling.reload_words()
        self.scan()
