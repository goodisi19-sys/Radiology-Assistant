"""Per-block, non-destructive spelling decoration and explicit replacements."""
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from queue import SimpleQueue
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
        self.ignored=set(); self.generation=0; self.cache=OrderedDict(); self.pending=set()
        self.results=SimpleQueue(); self.worker=ThreadPoolExecutor(max_workers=1,thread_name_prefix='spelling')
        self.poll=QTimer(self); self.poll.setInterval(50); self.poll.timeout.connect(self.drain); self.poll.start()
        self.grammar_mark=QTextCharFormat();self.grammar_mark.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SpellCheckUnderline);self.grammar_mark.setUnderlineColor(QColor('#2876b7'))
        self.mark = QTextCharFormat()
        self.mark.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SpellCheckUnderline)
        self.mark.setUnderlineColor(QColor('#df3030'))
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.reload_words)
        self.timer.start(450)

    @lru_cache(maxsize=2048)
    def issues(self, text):
        result=tuple(find_typos(text, self.personal | frozenset(self.ignored)))
        self.cache[text]=result
        return result

    def reload_words(self):
        if self.window._closing: return
        db = self.window.library.db
        words = {row[0].casefold() for row in db.execute('SELECT word FROM spelling_words')}
        for (content,) in db.execute('SELECT content FROM verified_standards'):
            words.update(m.group().casefold() for m in WORD.finditer(content))
        words.update(getattr(self.window.library.ai,'glossary_words',set()))
        self.personal = frozenset(words)
        self.window.library.ai.refresh_memory()
        self.issues.cache_clear()
        self.generation+=1; self.cache.clear(); self.pending.clear()
        self.ready = True
        self.rehighlight()

    def stop(self):
        self.timer.stop()
        self.poll.stop(); self.generation+=1
        self.worker.shutdown(wait=False,cancel_futures=True)
        self.ready = False
        self.issues.cache_clear()

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.window.library.set_setting('live_spelling', '1' if enabled else '0')
        if enabled and not self.ready: self.reload_words()
        else: self.rehighlight()

    def highlightBlock(self, text):
        if not getattr(self, 'ready', False) or not self.enabled: return
        if text not in self.cache:
            key=(self.generation,text)
            if key not in self.pending and len(self.pending)<256:
                self.pending.add(key)
                personal=self.personal | frozenset(self.ignored)
                future=self.worker.submit(find_typos,text,personal)
                def complete(f, key=key):
                    try:self.results.put((key,tuple(f.result()),None))
                    except Exception as exc:self.results.put((key,(),str(exc)))
                future.add_done_callback(complete)
            return
        if self.window.library.ai.enabled('grammar_warnings'):
            from medical_grammar import candidates
            for start,end,_,_ in candidates(text):self.setFormat(qt_offset(text,start),qt_offset(text,end)-qt_offset(text,start),self.grammar_mark)
        for issue in self.cache[text]:
            start = qt_offset(text, issue.start)
            self.setFormat(start, qt_offset(text, issue.end) - start, self.mark)

    def drain(self):
        changed=set()
        while not self.results.empty():
            (generation,text),issues,error=self.results.get(); self.pending.discard((generation,text))
            if generation!=self.generation or self.window._closing:continue
            if error:
                self.failure=error;self.cache[text]=()
                self.window.statusBar().showMessage('Орфография недоступна: '+error,5000);continue
            self.cache[text]=issues; self.cache.move_to_end(text); changed.add(text)
            if len(self.cache)>2048:self.cache.popitem(last=False)
        if changed:
            block=self.document().begin()
            while block.isValid():
                if block.text() in changed or (block.text() not in self.cache and len(self.pending)<128):self.rehighlightBlock(block)
                block=block.next()

    def ignore(self, word):
        self.ignored.add(word.casefold()); self.reload_words()

    def add_menu(self, menu, cursor):
        if not self.enabled: return
        if not self.ready: self.reload_words()
        block = cursor.block()
        text = block.text()
        offset = cursor.position() - block.position()
        if text not in self.cache:
            menu.addAction('Словарь проверяет абзац…').setEnabled(False)
            self.rehighlightBlock(block);return
        for issue in self.cache[text]:
            start, end = qt_offset(text, issue.start), qt_offset(text, issue.end)
            if not start <= offset <= end: continue
            target = QTextCursor(cursor)
            target.setPosition(block.position() + start)
            target.setPosition(block.position() + end, QTextCursor.MoveMode.KeepAnchor)
            submenu = menu.addMenu('Исправить: ' + issue.word)
            from radiology_ai import classify
            options = self.window.library.ai.ranked_corrections(issue.word,text[:issue.start],text[issue.end:],self.window.ai_context()['area'],self.window.ai_context()['modality']) if self.window.library.ai.enabled('context_corrections') else ()
            options = options or suggest(issue.word)
            for candidate in options:
                submenu.addAction(candidate, lambda c=candidate: self.replace(target, issue.word, c))
            if not options:
                submenu.addAction('Нет вариантов').setEnabled(False)
            rejected=submenu.addMenu('Отклонить вариант')
            for candidate in options:
                rejected.addAction(candidate,lambda c=candidate:self.reject(issue.word,c,options))
            submenu.addSeparator()
            submenu.addAction('Добавить в личный словарь', lambda: self.accept(issue.word))
            submenu.addAction('Пропустить в этом сеансе', lambda: self.ignore(issue.word))
            break

        if self.window.library.ai.enabled('grammar_warnings'):
            from medical_grammar import candidates
            from hybrid_safety import safe_pair
            for start,end,word,value in candidates(text):
                if not qt_offset(text,start)<=offset<=qt_offset(text,end) or not safe_pair(word,value):continue
                target=QTextCursor(cursor);target.setPosition(block.position()+qt_offset(text,start));target.setPosition(block.position()+qt_offset(text,end),QTextCursor.MoveMode.KeepAnchor)
                menu.addAction('Возможное согласование: '+value,lambda:self.replace(target,word,value));break

    def reject(self,original,candidate,options):
        if self.window.library.ai.enabled('self_learning'):
            self.window.library.ai.ranker.feedback(original,candidate,options,accepted=False)
    def replace(self, cursor, expected, replacement):
        if cursor.document() is not self.window.editor.document() or cursor.selectedText() != expected: return False
        cursor.beginEditBlock()
        cursor.insertText(replacement)
        cursor.endEditBlock()
        self.window.library.ai.confirm_correction(expected,replacement)
        return True

    def accept(self, word):
        db = self.window.library.db
        db.execute('INSERT OR IGNORE INTO spelling_words(word) VALUES(?)', (word.casefold(),))
        db.commit()
        self.reload_words()
