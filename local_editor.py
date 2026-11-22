"""Offline note expansion and guarded manual editing."""
import difflib, html, json
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPlainTextEdit,QPushButton,QCheckBox,QTextBrowser
from fragment_guard import FragmentGuard

class LocalEditorDialog(QDialog):
    def __init__(self, window, target):
        super().__init__(window)
        self.window=window
        self.guard=FragmentGuard(window.editor.document(),target)
        self.original=target.selectedText().replace('\u2029','\n')
        self.setWindowTitle('Локальный редактор заметки')
        self.resize(750,600)
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel('Исходный фрагмент:'))
        self.source=QPlainTextEdit(self.original); layout.addWidget(self.source)
        button=QPushButton('Развернуть локально'); button.clicked.connect(self.expand_local); layout.addWidget(button)
        self.result=QPlainTextEdit(); layout.addWidget(self.result)
        self.diff=QTextBrowser(); self.diff.setMaximumHeight(140); layout.addWidget(self.diff)
        self.variable_example=QCheckBox('Запомнить также как образец с другими числами и уровнями'); layout.addWidget(self.variable_example)
        button=QPushButton('Запомнить проверенную запись'); button.clicked.connect(self.remember_phrase); layout.addWidget(button)
        self.apply=QPushButton('Применить вариант'); self.apply.setEnabled(False); self.apply.clicked.connect(self.apply_result); layout.addWidget(self.apply)
        button=QPushButton('Закрыть'); button.clicked.connect(self.close); layout.addWidget(button)
        self.status=QLabel('Локальная обработка без сети. Проверьте результат.'); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.result.textChanged.connect(self.result_changed)
        self.source.textChanged.connect(self.result_changed)

    def expand_local(self):
        from shorthand import expand_note
        try: personal=json.loads(self.window.library.get_setting('shorthand_personal') or '{}')
        except ValueError:personal={}
        result,message=expand_note(self.source.toPlainText(),personal)
        self.result.setPlainText(result or '');self.status.setText(message)

    def remember_phrase(self):
        from shorthand import normalized
        source,result=self.source.toPlainText().strip(),self.result.toPlainText().strip()
        if not source or not result:return
        try:data=json.loads(self.window.library.get_setting('shorthand_personal') or '{}')
        except ValueError:data={}
        data[normalized(source)]=result
        pattern=None
        if self.variable_example.isChecked():
            from shorthand_patterns import make_pattern
            pattern=make_pattern(source,result)
            if pattern:
                patterns=data.setdefault('__patterns__',[])
                if pattern not in patterns:patterns.append(pattern)
        self.window.library.set_setting('shorthand_personal',json.dumps(data,ensure_ascii=False))
        self.status.setText('Сохранено проверенное соответствие и образец с переменными.' if pattern else 'Сохранено точное соответствие. Обобщение чисел/уровней не выполнялось.')

    def result_changed(self,update_status=True):
        text=self.result.toPlainText()
        baseline=self.guard.cursor().selectedText().replace('\u2029','\n') if self.guard.valid else self.original
        left=baseline.split();right=text.split();parts=[]
        for tag,a,b,c,d in difflib.SequenceMatcher(None,left,right,autojunk=True).get_opcodes():
            if tag=='equal':parts.append(html.escape(' '.join(right[c:d])))
            else:
                if a!=b:parts.append('<span style="color:#9b2424;text-decoration:line-through">'+html.escape(' '.join(left[a:b]))+'</span>')
                if c!=d:parts.append('<strong style="color:#08634d">'+html.escape(' '.join(right[c:d]))+'</strong>')
        self.diff.setHtml('<p>Изменения слов: удалено / добавлено. Это не медицинская проверка.</p><p>'+' '.join(parts)+'</p>')
        same=' '.join(text.split())==' '.join(baseline.split())
        self.apply.setEnabled(bool(text.strip()) and not same and self.guard.valid)
        if update_status:
            self.status.setText('Исходник без изменений.' if same else 'Проверьте факты, числа, стороны и отрицания. Изменения применяются вручную.')

    def apply_result(self):
        if not self.apply.isEnabled(): return
        if not self.guard.valid or self.window.editor.document() is not self.guard.document:
            self.apply.setEnabled(False);self.status.setText('Исходный фрагмент изменился. Выберите его заново.');return
        current=QTextCursor(self.window.editor.textCursor())
        self.guard.replace(self.result.toPlainText())
        self.window.editor.setTextCursor(current)
        self.apply.setEnabled(False)
        self.status.setText('Вариант применён. Ctrl+Z вернёт предыдущий текст.')
        self.window.activateWindow();self.window.editor.setFocus()

    def reject(self): self.close()
    def closeEvent(self,event):
        self.apply.setEnabled(False)
        self.guard.close()
        event.accept()
