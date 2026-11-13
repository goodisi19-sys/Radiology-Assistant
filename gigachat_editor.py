"""Explicit cloud text handoff with asynchronous preview and guarded manual apply."""
import difflib
import html
import json
import os
import queue
import threading
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QPlainTextEdit,QPushButton,QComboBox,QCheckBox,QFileDialog,QTextBrowser,QWidget
from gigachat_client import GigaChatClient,GigaChatError,tls_context,SCOPES
from gigachat_secret import load_key,save_key

class GigaChatEditorDialog(QDialog):
    def __init__(self, window, target=None, source=None, instruction=None):
        super().__init__(window)
        import app
        self.window=window
        self.target=QTextCursor(target if target is not None else window.editor.textCursor())
        whole_scope=target is None and not self.target.hasSelection()
        if whole_scope: self.target.select(QTextCursor.SelectionType.Document)
        from fragment_guard import FragmentGuard
        self.guard=FragmentGuard(window.editor.document(),self.target,whole=whole_scope)
        self.source_text=self.target.selectedText().replace('\u2029','\n')
        self.original=self.source_text
        if source is not None: self.source_text=source
        self.secret_path=app.app_data_dir()/'gigachat-key.dpapi'
        self.inbox=queue.Queue(); self.closed=False; self.busy=False
        self.setWindowTitle('GigaChat — ИИ-редактор'); self.resize(850,760)
        layout=QVBoxLayout(self)
        label=QLabel('Только «Отправить в GigaChat» передаёт текст внешнему сервису. Уберите персональные данные.\n'
            'Проверьте результат: модель может ошибаться. Исходник меняется только после «Применить вариант».')
        label.setWordWrap(True); layout.addWidget(label)
        outer=layout
        toggle=QPushButton('Подключение и настройки GigaChat');outer.addWidget(toggle)
        self.connection_panel=QWidget();outer.addWidget(self.connection_panel)
        layout=QVBoxLayout(self.connection_panel);layout.setContentsMargins(0,0,0,0)
        toggle.clicked.connect(lambda: self.connection_panel.setVisible(not self.connection_panel.isVisible()))
        self.key=QLineEdit(); self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText('Ключ авторизации GigaChat (Authorization Key)'); layout.addWidget(self.key)
        self.key.setText(getattr(window,'gigachat_session_key','') or os.environ.get('GIGACHAT_AUTH_KEY',''))
        self.startup_error=''
        if not self.key.text():
            try: self.key.setText(load_key(self.secret_path))
            except (OSError,UnicodeError): self.startup_error='Сохранённый ключ не прочитан. Введите его заново.'
        self.remember=QCheckBox('Сохранить ключ для моего пользователя Windows (DPAPI)')
        self.remember.setChecked(self.secret_path.exists()); self.remember.setEnabled(os.name=='nt'); layout.addWidget(self.remember)
        row=QHBoxLayout(); layout.addLayout(row)
        self.scope=QComboBox(); self.scope.addItems(SCOPES); self.scope.setCurrentText(window.library.get_setting('giga_scope') or SCOPES[0]); row.addWidget(self.scope)
        self.model=QComboBox(); self.model.setEditable(True); self.model.addItems(['GigaChat-2','GigaChat-2-Pro','GigaChat-2-Max'])
        self.model.setCurrentText(window.library.get_setting('giga_model') or 'GigaChat-2'); row.addWidget(self.model)
        self.models_button=QPushButton('Доступные модели'); self.models_button.clicked.connect(lambda:self.start('models')); row.addWidget(self.models_button)
        self.ca=QLineEdit(window.library.get_setting('giga_ca')); self.ca.setPlaceholderText('Дополнительный PEM-сертификат организации (необязательно)')
        layout.addWidget(self.ca)
        choose=QPushButton('Выбрать дополнительный сертификат'); choose.clicked.connect(self.choose_ca); layout.addWidget(choose)
        self.connection_panel.setVisible(target is None and not self.key.text())
        layout=outer
        self.instruction=QLineEdit('Сделай текст профессиональнее и связнее, сохрани клиническое содержание и структуру протокола.')
        if instruction is not None: self.instruction.setText(instruction)
        self.instruction.setCursorPosition(0)
        self.instruction.setToolTip(self.instruction.text())
        self.instruction.textChanged.connect(self.instruction.setToolTip)
        self.instruction.setPlaceholderText('Ваше задание редактору'); layout.addWidget(self.instruction)
        layout.addWidget(QLabel('Будет отправлен этот текст — можно убрать персональные данные:'))
        self.source=QPlainTextEdit(self.source_text); layout.addWidget(self.source)
        if target is not None:
            local=QPushButton('Развернуть локально');local.clicked.connect(self.expand_local);layout.addWidget(local)
        row=QHBoxLayout(); layout.addLayout(row)
        self.generate=QPushButton('Отправить в GigaChat'); self.generate.clicked.connect(lambda:self.start('rewrite')); row.addWidget(self.generate)
        self.another=QPushButton('Другой вариант'); self.another.setEnabled(False); self.another.clicked.connect(lambda:self.start('another')); row.addWidget(self.another)
        layout.addWidget(QLabel('Предложенный вариант — проверьте перед применением:'))
        self.result=QPlainTextEdit(); layout.addWidget(self.result)
        self.diff=QTextBrowser();self.diff.setMaximumHeight(140);layout.addWidget(self.diff)
        self.variable_example=QCheckBox('Запомнить также как образец с другими числами и уровнями');layout.addWidget(self.variable_example)
        remember_phrase=QPushButton('Запомнить проверенную запись');remember_phrase.clicked.connect(self.remember_phrase);layout.addWidget(remember_phrase)
        row=QHBoxLayout(); layout.addLayout(row)
        self.apply=QPushButton('Применить вариант'); self.apply.setEnabled(False); self.apply.clicked.connect(self.apply_result); row.addWidget(self.apply)
        forget=QPushButton('Удалить сохранённый ключ'); forget.clicked.connect(self.forget); row.addWidget(forget)
        close=QPushButton('Закрыть'); close.clicked.connect(self.close); row.addWidget(close)
        self.status=QLabel(self.startup_error or 'Передаётся только текст из поля выше и ваше задание. Ctrl+Z отменяет применённую замену.')
        self.status.setWordWrap(True); layout.addWidget(self.status)
        self.result.textChanged.connect(self.result_changed)
        self.source.textChanged.connect(self.result_changed)
        self.timer=QTimer(self); self.timer.timeout.connect(self.poll); self.timer.start(100)

    def open_giga(self):
        self.status.setText('Проверьте заметку и нажмите «Отправить в GigaChat». Запрос ещё не отправлен.')

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

    def choose_ca(self):
        name,_=QFileDialog.getOpenFileName(self,'Сертификат CA','','Сертификаты (*.pem *.crt);;Все файлы (*)')
        if name: self.ca.setText(name)

    def forget(self):
        try: self.secret_path.unlink(missing_ok=True)
        except OSError: self.status.setText('Не удалось удалить сохранённый ключ.'); return
        self.key.clear(); self.window.gigachat_session_key=''; self.remember.setChecked(False)
        self.status.setText('Сохранённый ключ удалён. Уже отправленный запрос может ещё выполняться.')

    def start(self,mode):
        if self.busy: return
        if mode!='models' and not self.guard.valid:
            self.status.setText('Исходный фрагмент редактировался. Выберите его заново.'); return
        import app
        try:
            client=GigaChatClient(self.key.text(),tls_context(app.bundled_data_path('gigachat_data'),self.ca.text().strip()),self.scope.currentText())
            if mode!='models' and not self.source.toPlainText().strip(): raise GigaChatError('Нет текста для редактирования.')
            if self.remember.isChecked(): save_key(self.secret_path,client.credentials)
            else: self.secret_path.unlink(missing_ok=True)
        except (GigaChatError,OSError,ValueError):
            self.connection_panel.setVisible(True)
            self.status.setText('Проверьте ключ и PEM-сертификат. Настройки не удалось подготовить.'); return
        self.window.gigachat_session_key=client.credentials
        for name,value in [('giga_model',self.model.currentText()),('giga_scope',self.scope.currentText()),('giga_ca',self.ca.text().strip())]: self.window.library.set_setting(name,value)
        text,instruction,model=self.source.toPlainText(),self.instruction.text(),self.model.currentText()
        previous=self.result.toPlainText() if mode=='another' else ''
        for widget in (self.source,self.instruction,self.key,self.scope,self.model,self.ca): widget.setEnabled(False)
        self.busy=True; self.generate.setEnabled(False); self.another.setEnabled(False); self.models_button.setEnabled(False); self.apply.setEnabled(False)
        self.status.setText('Ожидание GigaChat… Окно можно закрыть; отправленный запрос может завершиться на стороне сервиса.')
        inbox=self.inbox
        def work():
            try: inbox.put((mode,client.models() if mode=='models' else client.rewrite(text,instruction,model,previous),None))
            except GigaChatError as error: inbox.put((mode,None,str(error)))
            except Exception: inbox.put((mode,None,'Не удалось обработать ответ GigaChat. Исходник сохранён.'))
        threading.Thread(target=work,daemon=True).start()

    def poll(self):
        if self.closed: return
        try: mode,value,error=self.inbox.get_nowait()
        except queue.Empty: return
        for widget in (self.source,self.instruction,self.key,self.scope,self.model,self.ca): widget.setEnabled(True)
        self.busy=False; self.generate.setEnabled(True); self.models_button.setEnabled(True)
        if error: self.status.setText(error); self.result_changed(False); return
        if mode=='models':
            current=self.model.currentText(); self.model.clear(); self.model.addItems(value); self.model.setCurrentText(current if current in value else (value[0] if value else 'GigaChat-2'))
            self.status.setText(f'Доступных моделей: {len(value)}. Выберите модель для редактирования.'); self.result_changed(False)
        else:
            self.result.setPlainText(value); self.result_changed()

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
        self.apply.setEnabled(bool(text.strip()) and not same and not self.busy and self.guard.valid)
        self.another.setEnabled(bool(text.strip()) and not self.busy)
        if update_status and not self.busy:
            self.status.setText('Получен исходник без изменений. Нажмите «Другой вариант» или уточните задание.' if same else 'Проверьте факты, числа, стороны и отрицания. Изменения применяются вручную.')

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
        self.closed=True; self.timer.stop(); self.guard.close(); self.key.clear(); event.accept()
