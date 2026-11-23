"""User-controlled Google handoff and preserved local, physician-reviewed glossary."""
import re
from PySide6.QtCore import Qt,QUrl,QUrlQuery,QEvent
from PySide6.QtGui import QDesktopServices,QTextCursor
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLabel,QPlainTextEdit,QPushButton,QLineEdit


class GoogleReference(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.window=parent
        layout=QVBoxLayout(self)
        intro=QLabel('Google открывается в установленном браузере по умолчанию.\nПроверка протокола: правая кнопка в редакторе → «Проверить в Google». Результат читается в браузере.')
        intro.setWordWrap(True);layout.addWidget(intro)
        review=QPushButton('Проверить выделение / протокол в Google…');review.setEnabled(parent is not None)
        review.clicked.connect(self.review_protocol);layout.addWidget(review)
        self.input=QPlainTextEdit();self.input.setPlaceholderText('Отдельный вопрос… Ctrl+Enter — открыть Google')
        self.input.installEventFilter(self);layout.addWidget(self.input,1)
        self.google=QPushButton('Открыть вопрос в Google');self.google.clicked.connect(self.search_google);layout.addWidget(self.google)
        self.status=QLabel('Автоматической отправки и чтения ответов нет. Для протокола показывается точный запрос перед отправкой.')
        self.status.setWordWrap(True);layout.addWidget(self.status)
        if parent is None:return
        layout.addWidget(QLabel('Локальный словарь терминов — определения подтверждает врач'))
        self.term=QLineEdit();self.term.setPlaceholderText('Термин');layout.addWidget(self.term)
        load=QPushButton('Загрузить сохранённое определение');load.clicked.connect(self.load_term);layout.addWidget(load)
        self.definition=QPlainTextEdit();self.definition.setMaximumHeight(120);self.definition.setPlaceholderText('Проверенное определение без данных пациента.');layout.addWidget(self.definition)
        self.term_source='Личный словарь'
        self.term_status=QLabel();self.term_status.setWordWrap(True);layout.addWidget(self.term_status)
        verify=QPushButton('Подтвердить определение после проверки врачом');verify.clicked.connect(self.verify_term);layout.addWidget(verify)

    def review_protocol(self,cursor=None):
        if self.window is None:return
        from privacy_review import redact,make_prompt,approve_preview
        from google_dispatch import open_review
        target=QTextCursor(cursor) if isinstance(cursor,QTextCursor) else self.window.editor.textCursor()
        text=target.selectedText().replace('\u2029','\n') if target.hasSelection() else self.window.editor.toPlainText()
        clean=redact(text)
        if not clean.text.strip():self.status.setText('Нет текста для проверки.');return
        approved=approve_preview(self,make_prompt(clean.text))
        if approved is None:return
        self.status.setText(open_review(approved).message)
        self.window.statusBar().showMessage(self.status.text(),10000)

    def load_term(self):
        term=self.term.text().strip().casefold();record=self.window.glossary.records.get(term)
        if record:self.show_term(term,record['definition'],record.get('source','Личный словарь'),record['verified'])
        else:self.term_status.setText('Сохранённого определения нет.')

    def show_term(self,term,text,source,verified):
        self.term.setText(term);self.definition.setPlainText(text);self.term_source=source
        self.term_status.setText('Подтверждённое определение.' if verified else 'Непроверенная справка. Не используется для обучения без подтверждения врача.')

    def verify_term(self):
        try:
            term=self.term.text().strip()
            if not re.fullmatch(r'[А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z -]{1,79}',term):raise ValueError('Укажите отдельный термин без идентификаторов, чисел и переносов строк.')
            self.window.glossary.save(term,self.definition.toPlainText(),self.term_source,verified=True)
            self.window.apply_glossary();self.term_status.setText('Определение подтверждено и доступно локально.')
        except (ValueError,OSError) as error:self.term_status.setText(str(error))

    def activate(self):self.input.setFocus(Qt.FocusReason.OtherFocusReason)

    def search_google(self):
        question=self.input.toPlainText().strip()
        if not question:self.status.setText('Введите вопрос.');self.activate();return
        url=QUrl('https://www.google.com/search');query=QUrlQuery();query.addQueryItem('q',question);url.setQuery(query)
        self.status.setText('Google открыт в браузере.' if QDesktopServices.openUrl(url) else 'Не удалось открыть браузер по умолчанию.')

    def eventFilter(self,obj,event):
        if obj is self.input and event.type()==QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.search_google();return True
        return super().eventFilter(obj,event)
