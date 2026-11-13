import json
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPlainTextEdit,QPushButton
from shorthand import expand_note,normalized,NOTE_PROMPT

class ShorthandDialog(QDialog):
    def __init__(self,window,target):
        super().__init__(window)
        self.window=window;self.target=QTextCursor(target);self.snapshot=window.editor.toPlainText()
        self.original=self.target.selectedText().replace('\u2029','\n')
        self.setWindowTitle('Развернуть заметку');self.resize(760,490)
        layout=QVBoxLayout(self)
        label=QLabel('Локально распознаются только известные записи. Исходник меняется после применения.\n'
            'Для свободной заметки можно открыть GigaChat; отправка выполняется отдельно в его окне.')
        label.setWordWrap(True);layout.addWidget(label)
        self.source=QPlainTextEdit(self.original);layout.addWidget(self.source)
        row=QHBoxLayout();layout.addLayout(row)
        local=QPushButton('Развернуть локально');local.clicked.connect(self.expand);row.addWidget(local)
        giga=QPushButton('Развернуть через GigaChat');giga.clicked.connect(self.open_giga);row.addWidget(giga)
        self.result=QPlainTextEdit();self.result.setPlaceholderText('Предпросмотр — можно отредактировать вручную');layout.addWidget(self.result)
        row=QHBoxLayout();layout.addLayout(row)
        self.apply=QPushButton('Применить');self.apply.clicked.connect(self.apply_result);row.addWidget(self.apply)
        remember=QPushButton('Запомнить мою запись');remember.clicked.connect(self.remember);row.addWidget(remember)
        close=QPushButton('Отмена');close.clicked.connect(self.close);row.addWidget(close)
        self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status)
        self.result.textChanged.connect(self.changed);self.source.textChanged.connect(self.invalidate)
        self.expand()
    def personal(self):
        try:
            data=json.loads(self.window.library.get_setting('shorthand_personal') or '{}')
            return data if isinstance(data,dict) else {}
        except ValueError:return {}
    def invalidate(self):
        self.result.clear();self.status.setText('Заметка изменена. Нажмите «Развернуть локально» или откройте GigaChat.')
    def changed(self):
        self.apply.setEnabled(bool(self.result.toPlainText().strip()) and self.result.toPlainText()!=self.original)
    def expand(self):
        result,message=expand_note(self.source.toPlainText(),self.personal())
        self.result.setPlainText(result or '');self.status.setText(message);self.changed()
    def current(self):
        if self.window.editor.toPlainText()!=self.snapshot:
            self.apply.setEnabled(False);self.status.setText('Документ изменился. Закройте окно и выберите фрагмент заново.');return False
        return True
    def apply_result(self):
        if not self.apply.isEnabled() or not self.current():return
        self.target.beginEditBlock();self.target.insertText(self.result.toPlainText());self.target.endEditBlock()
        self.close()
    def remember(self):
        source,result=self.source.toPlainText().strip(),self.result.toPlainText().strip()
        if not source or not result:self.status.setText('Введите запись и проверенную полную формулировку.');return
        data=self.personal();data[normalized(source)]=result
        self.window.library.set_setting('shorthand_personal',json.dumps(data,ensure_ascii=False))
        self.status.setText('Сохранено ваше соответствие. Оно имеет приоритет при точном совпадении записи.')
    def open_giga(self):
        if not self.current():return
        self.window.open_fragment_gigachat(self.target,self.source.toPlainText(),NOTE_PROMPT)
        self.close()
