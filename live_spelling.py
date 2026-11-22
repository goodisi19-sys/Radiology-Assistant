"""Per-block, non-destructive spelling decoration and explicit replacements."""
from functools import lru_cache
from PySide6.QtCore import QTimer
from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QTextCursor
from spell_check import WORD, find_typos, suggest, qt_offset

class LiveSpelling(QSyntaxHighlighter):
    def __init__(self, window):
        super().__init__(window.editor.document())
        self.window = window
        self.enabled = window.library.get_setting('live_spelling') != '0'
        self.ready = False
        self.personal = frozenset()
        self.mark = QTextCharFormat()
        self.mark.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SpellCheckUnderline)
        self.mark.setUnderlineColor(QColor('#df3030'))
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.reload_words)
        self.timer.start(450)

    @lru_cache(maxsize=2048)
    def issues(self, text):
        return tuple(find_typos(text, self.personal))

    def reload_words(self):
        if self.window._closing: return
        db = self.window.library.db
        words = {row[0].casefold() for row in db.execute('SELECT word FROM spelling_words')}
        for (content,) in db.execute('SELECT content FROM verified_standards'):
            words.update(m.group().casefold() for m in WORD.finditer(content))
        self.personal = frozenset(words)
        self.issues.cache_clear()
        self.ready = True
        self.rehighlight()

    def stop(self):
        self.timer.stop()
        self.ready = False
        self.issues.cache_clear()

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.window.library.set_setting('live_spelling', '1' if enabled else '0')
        if enabled and not self.ready: self.reload_words()
        else: self.rehighlight()

    def highlightBlock(self, text):
        if not getattr(self, 'ready', False) or not self.enabled: return
        for issue in self.issues(text):
            start = qt_offset(text, issue.start)
            self.setFormat(start, qt_offset(text, issue.end) - start, self.mark)

    def add_menu(self, menu, cursor):
        if not self.enabled: return
        if not self.ready: self.reload_words()
        block = cursor.block()
        text = block.text()
        offset = cursor.position() - block.position()
        for issue in self.issues(text):
            start, end = qt_offset(text, issue.start), qt_offset(text, issue.end)
            if not start <= offset <= end: continue
            target = QTextCursor(cursor)
            target.setPosition(block.position() + start)
            target.setPosition(block.position() + end, QTextCursor.MoveMode.KeepAnchor)
            submenu = menu.addMenu('Исправить: ' + issue.word)
            options = suggest(issue.word)
            for candidate in options:
                submenu.addAction(candidate, lambda c=candidate: self.replace(target, issue.word, c))
            if not options:
                submenu.addAction('Нет вариантов').setEnabled(False)
            submenu.addSeparator()
            submenu.addAction('Добавить в личный словарь', lambda: self.accept(issue.word))
            break

    def replace(self, cursor, expected, replacement):
        if cursor.document() is not self.window.editor.document() or cursor.selectedText() != expected: return False
        cursor.beginEditBlock()
        cursor.insertText(replacement)
        cursor.endEditBlock()
        return True

    def accept(self, word):
        db = self.window.library.db
        db.execute('INSERT OR IGNORE INTO spelling_words(word) VALUES(?)', (word.casefold(),))
        db.commit()
        self.reload_words()
