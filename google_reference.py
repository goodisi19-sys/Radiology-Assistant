"""Open an explicitly entered question in ordinary Google Search."""
from PySide6.QtCore import Qt, QUrl, QUrlQuery, QEvent
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPlainTextEdit, QPushButton


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
