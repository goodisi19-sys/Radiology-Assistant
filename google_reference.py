"""Open an explicitly entered question in ordinary Google Search."""
from PySide6.QtCore import Qt, QUrl, QUrlQuery, QEvent
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPlainTextEdit, QPushButton, QLineEdit, QCheckBox


class GoogleReference(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        intro = QLabel('Справочный поиск через обычный Google в вашем браузере.\n'
            'ИИ-обзор или «Режим ИИ» доступны на стороне Google, если поддерживаются вашим аккаунтом и запросом.')
        intro.setWordWrap(True); layout.addWidget(intro)
        layout.addWidget(QLabel('Ваш вопрос'))
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText('Введите вопрос… Ctrl+Enter — открыть Google')
        self.input.installEventFilter(self); layout.addWidget(self.input, 1)
        self.google = QPushButton('Открыть вопрос в Google')
        self.google.clicked.connect(self.search_google); layout.addWidget(self.google)
        self.status = QLabel('Отправляется только набранный вопрос. Протокол автоматически не передаётся.')
        self.status.setWordWrap(True); layout.addWidget(self.status)
        if parent is None:return
        self.window=parent;self.term=QLineEdit();self.term.setPlaceholderText('Медицинский термин без данных пациента');layout.addWidget(self.term)
        self.term_status=QLabel('Автоуточнение отправляет только редкий термин и область в Google. Ответы требуют проверки врача.');self.term_status.setWordWrap(True);layout.addWidget(self.term_status)
        automatic=QCheckBox('Автоматически уточнять незнакомые термины в Google AI Mode')
        automatic.setChecked(parent.library.get_setting('google_terms_auto')!='0')
        automatic.toggled.connect(self.set_automatic);layout.addWidget(automatic)
        lookup=QPushButton('Уточнить термин в Google AI Mode');lookup.clicked.connect(self.lookup_term);layout.addWidget(lookup)
        self.definition=QPlainTextEdit();self.definition.setPlaceholderText('Справка / определение; непроверенный ответ не обучает локальные модели.');self.definition.setMaximumHeight(150);layout.addWidget(self.definition)
        self.term_source=''
        verify=QPushButton('Подтвердить определение после проверки врачом');verify.clicked.connect(self.verify_term);layout.addWidget(verify)
        inspect=QPushButton('Показать техническую страницу Google');inspect.clicked.connect(self.inspect_browser);layout.addWidget(inspect)

    def set_automatic(self,value):
        self.window.library.set_setting('google_terms_auto','1' if value else '0')
        if not value and hasattr(self.window,'term_lookup'):self.window.term_lookup.cancel()
    def lookup_term(self):
        try:self.window.term_lookup.lookup(self.term.text(),manual=True)
        except (ValueError,OSError,ImportError,RuntimeError) as e:self.term_status.setText(str(e))
    def show_term(self,term,text,source,verified):
        self.term.setText(term);self.definition.setPlainText(text);self.term_source=source
        self.term_status.setText(('Проверенное определение.' if verified else 'Непроверенная справка Google — возможны ошибки. Не применяется автоматически.')+' Источник: '+source)
    def verify_term(self):
        try:
            from google_term_lookup import sanitized_query
            sanitized_query(self.term.text())
            self.window.glossary.save(self.term.text(),self.definition.toPlainText(),self.term_source,verified=True)
            self.window.apply_glossary();self.term_status.setText('Определение подтверждено; термин доступен локально без нового поиска.')
        except (ValueError,OSError) as e:self.term_status.setText(str(e))
    def inspect_browser(self):
        browser=getattr(self.window.term_lookup,'browser',None)
        if browser:
            from PySide6.QtWebEngineCore import QWebEnginePage
            browser.page.setLifecycleState(QWebEnginePage.LifecycleState.Active);browser.show();browser.raise_()
    def activate(self): self.input.setFocus(Qt.FocusReason.OtherFocusReason)

    def search_google(self):
        question = self.input.toPlainText().strip()
        if not question:
            self.status.setText('Введите вопрос.'); self.activate(); return
        url = QUrl('https://www.google.com/search')
        query = QUrlQuery(); query.addQueryItem('q', question); url.setQuery(query)
        self.status.setText('Google открыт в браузере.' if QDesktopServices.openUrl(url)
                            else 'Не удалось открыть браузер по умолчанию.')

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.search_google(); return True
        return super().eventFilter(obj, event)
