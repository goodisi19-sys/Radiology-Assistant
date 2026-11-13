"""Persistent local reference chat, independent of report editing."""
import threading
from PySide6.QtCore import QThread, Signal, Qt, QUrl, QUrlQuery
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit,
    QLineEdit, QPushButton, QComboBox, QFileDialog, QGroupBox)
from expert_assistant import generate_chat, chat_context, default_server_path


class ChatThread(QThread):
    completed = Signal(str)
    failed = Signal(str)
    def __init__(self, server, model, history, parent=None):
        super().__init__(parent)
        self.arguments = server, model, history
        self.cancelled = threading.Event()
    def run(self):
        try: self.completed.emit(generate_chat(*self.arguments, cancelled=self.cancelled))
        except Exception as exc: self.failed.emit(str(exc))


class LocalChat(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.library = window.library
        self.thread = None
        self.pending = None
        self.session_id = None
        layout = QVBoxLayout(self)
        intro = QLabel('Локальный чат с вашей Qwen 3B. Задавайте вопросы и уточняйте ответы.\n'
            'Без поиска в интернете; справочные сведения проверяйте по источникам.')
        intro.setWordWrap(True); layout.addWidget(intro)
        row = QHBoxLayout(); layout.addLayout(row)
        self.sessions = QComboBox(); self.sessions.setMinimumWidth(80); row.addWidget(self.sessions, 1)
        self.new_button = QPushButton('Новый разговор'); row.addWidget(self.new_button)
        self.sessions.currentIndexChanged.connect(self.select_session)
        self.new_button.clicked.connect(self.new_session)
        self.settings = QGroupBox('Настройка локальной модели')
        self.settings.setCheckable(True); layout.addWidget(self.settings)
        settings_layout = QVBoxLayout(self.settings)
        self.settings_body = QWidget(); settings_layout.addWidget(self.settings_body)
        fields = QVBoxLayout(self.settings_body); fields.setContentsMargins(0, 0, 0, 0)
        self.server = self.path_row(fields, 'Движок llama-server.exe', 'expert_server', 'Движок (*)')
        self.model = self.path_row(fields, 'Модель GGUF — та же, что для редактуры', 'expert_model', 'Модель (*.gguf)')
        self.refresh_settings()
        self.settings.toggled.connect(self.settings_body.setVisible)
        self.settings.setChecked(not bool(self.model.text()))
        layout.addWidget(QLabel('Переписка — ответы появятся здесь'))
        self.transcript = QPlainTextEdit(); self.transcript.setReadOnly(True)
        self.transcript.setPlaceholderText('Введите вопрос в поле «Ваш вопрос» ниже и нажмите «Спросить».')
        layout.addWidget(self.transcript, 1)
        lookup = QHBoxLayout(); layout.addLayout(lookup)
        self.google = QPushButton('Открыть вопрос в Google'); self.google.clicked.connect(self.search_google); lookup.addWidget(self.google)
        self.google.setToolTip('Открыть обычный Google-поиск в браузере. Используйте ИИ-обзор или режим ИИ, если они доступны у Google. Вопрос отправляется в браузер; текст протокола не читается.')
        layout.addWidget(QLabel('Ваш вопрос — напишите здесь'))
        self.input = QPlainTextEdit(); self.input.setMinimumHeight(90); self.input.setMaximumHeight(130)
        self.input.setPlaceholderText('Ваш вопрос… Ctrl+Enter — отправить')
        self.input.installEventFilter(self); layout.addWidget(self.input)
        row = QHBoxLayout(); layout.addLayout(row)
        self.send = QPushButton('Спросить'); self.send.clicked.connect(self.send_message); row.addWidget(self.send)
        self.stop = QPushButton('Остановить'); self.stop.setEnabled(False); self.stop.clicked.connect(self.stop_generation); row.addWidget(self.stop)
        self.copy = QPushButton('Копировать ответ'); self.copy.clicked.connect(self.copy_answer); row.addWidget(self.copy)
        self.status = QLabel('История разговоров хранится локально в вашей базе.')
        self.status.setWordWrap(True); layout.addWidget(self.status)
        rows = self.library.chat_sessions()
        if not rows: self.session_id = self.library.new_chat()
        else:
            last = self.library.get_setting('chat_session')
            self.session_id = next((key for key, _ in rows if str(key) == last), rows[0][0])
        self.refresh_sessions()
        self.render()

    def path_row(self, layout, label, key, file_filter):
        layout.addWidget(QLabel(label))
        row = QHBoxLayout(); layout.addLayout(row)
        field = QLineEdit(); row.addWidget(field, 1)
        choose = QPushButton('Выбрать…'); row.addWidget(choose)
        field.editingFinished.connect(lambda: self.library.set_setting(key, field.text().strip()))
        def select():
            path, _ = QFileDialog.getOpenFileName(self, label, '', file_filter)
            if path:
                field.setText(path)
                self.library.set_setting(key, path)
        choose.clicked.connect(select)
        return field

    def refresh_settings(self):
        if self.is_busy(): return
        self.server.setText(self.library.get_setting('expert_server') or default_server_path())
        self.model.setText(self.library.get_setting('expert_model'))

    def activate(self):
        self.refresh_settings()
        self.input.setReadOnly(False)
        self.input.setFocus(Qt.FocusReason.OtherFocusReason)

    def is_busy(self): return self.thread is not None

    def refresh_sessions(self):
        self.sessions.blockSignals(True)
        self.sessions.clear()
        for key, title in self.library.chat_sessions(): self.sessions.addItem(title, key)
        self.sessions.setCurrentIndex(self.sessions.findData(self.session_id))
        self.sessions.blockSignals(False)

    def select_session(self, index):
        if self.is_busy() or index < 0: return
        self.session_id = self.sessions.itemData(index)
        self.library.set_setting('chat_session', str(self.session_id))
        self.input.clear()
        self.render()

    def new_session(self):
        if self.is_busy(): return
        self.session_id = self.library.new_chat()
        self.library.set_setting('chat_session', str(self.session_id))
        self.refresh_sessions()
        self.input.clear()
        self.render()
        self.status.setText('Новый разговор. Предыдущие доступны в списке выше.')

    def render(self):
        history = self.library.chat_history(self.session_id)
        if self.pending is not None: history.append({'role': 'user', 'content': self.pending})
        self.transcript.setPlainText('\n\n'.join(('Вы' if item['role'] == 'user' else 'ИИ — ответ не проверен по источникам') + ':\n' + item['content'] for item in history))
        self.transcript.verticalScrollBar().setValue(self.transcript.verticalScrollBar().maximum())
        self.copy.setEnabled(any(item['role'] == 'assistant' for item in history))

    def set_busy(self, busy):
        self.send.setEnabled(not busy); self.stop.setEnabled(busy)
        self.sessions.setEnabled(not busy); self.new_button.setEnabled(not busy)
        self.settings.setEnabled(not busy)
        # The question field must stay writable, including while the model works.
        self.input.setReadOnly(False)

    def send_message(self):
        if self.is_busy(): return
        expert = getattr(self.window, 'expert_dialog', None)
        if expert is not None and expert.is_busy():
            self.status.setText('Дождитесь завершения редактуры протокола, затем задайте вопрос.')
            return
        question = self.input.toPlainText().strip()
        history = self.library.chat_history(self.session_id) + [{'role': 'user', 'content': question}]
        try: context = chat_context(history)
        except ValueError as exc:
            self.status.setText(str(exc)); return
        self.library.set_setting('expert_server', self.server.text().strip())
        self.library.set_setting('expert_model', self.model.text().strip())
        self.pending = question
        self.render()
        self.set_busy(True)
        self.status.setText(f'Готовлю ответ на CPU… В контексте {len(context)-1} сообщений. Можно остановить запрос.')
        self.thread = ChatThread(self.server.text().strip(), self.model.text().strip(), history, self)
        self.thread.completed.connect(self.receive_answer)
        self.thread.failed.connect(self.receive_error)
        worker = self.thread
        def finished():
            self.thread = None
            self.set_busy(False)
            worker.deleteLater()
        self.thread.finished.connect(finished)
        self.thread.start()

    def receive_answer(self, text):
        if self.pending is None: return
        if self.thread is not None and self.thread.cancelled.is_set():
            self.receive_error('Запрос остановлен.'); return
        try: self.library.save_chat_turn(self.session_id, self.pending, text)
        except Exception as exc:
            self.receive_error('Не удалось сохранить ответ: ' + str(exc)); return
        question = self.pending
        self.pending = None
        if self.input.toPlainText().strip() == question: self.input.clear()
        self.refresh_sessions()
        self.render()
        self.status.setText('Ответ готов. Можно задать уточняющий вопрос.')

    def receive_error(self, text):
        self.pending = None
        self.render()
        self.status.setText(text)  # Keep the original question in the input for retry.

    def stop_generation(self):
        if self.thread is not None:
            self.thread.cancelled.set()
            self.stop.setEnabled(False)
            self.status.setText('Останавливаю локальную модель…')

    def search_google(self):
        from PySide6.QtGui import QDesktopServices
        question = self.input.toPlainText().strip()
        if not question:
            self.status.setText('Введите вопрос в поле «Ваш вопрос», затем нажмите «Открыть вопрос в Google».')
            self.input.setFocus(); return
        query = QUrlQuery()
        query.addQueryItem('q', question)
        url = QUrl('https://www.google.com/search'); url.setQuery(query)
        if QDesktopServices.openUrl(url):
            self.status.setText('Вопрос открыт в браузере. ИИ-обзор и режим ИИ доступны по условиям Google; ответ не переносится сюда автоматически.')
        else:
            self.status.setText('Не удалось открыть браузер. Проверьте браузер по умолчанию.')

    def copy_answer(self):
        from PySide6.QtWidgets import QApplication
        for item in reversed(self.library.chat_history(self.session_id)):
            if item['role'] == 'assistant':
                QApplication.clipboard().setText(item['content'])
                self.status.setText('Ответ скопирован.'); return

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self.input and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.send_message(); return True
        return super().eventFilter(obj, event)
