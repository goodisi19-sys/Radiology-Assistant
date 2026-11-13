import threading

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QPlainTextEdit, QFileDialog, QCheckBox
from expert_assistant import generate_variant, review_issues, DEFAULT_INSTRUCTION, default_server_path, same_text


class GenerationThread(QThread):
    completed = Signal(str)
    failed = Signal(str)
    def __init__(self, server, model, source, instruction, parent=None):
        super().__init__(parent)
        self.arguments = server, model, source, instruction
        self.cancelled = threading.Event()
    def run(self):
        try: self.completed.emit(generate_variant(*self.arguments, cancelled=self.cancelled))
        except Exception as exc: self.failed.emit(str(exc))


class ExpertDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle('Рентгенолог — экспертный помощник')
        self.resize(940, 860)
        self.issues = []
        self.thread = None
        self.snapshot = window.editor.toPlainText()
        self.target = QTextCursor(window.editor.textCursor())
        if not self.target.hasSelection(): self.target.select(QTextCursor.SelectionType.Document)
        self.source_text = self.target.selectedText().replace('\u2029', '\n')
        layout = QVBoxLayout(self)
        intro = QLabel('Профессиональная редактура по вашему запросу — фрагмента или всего протокола.\n'
            'Используется ваша локальная Qwen 3B. На CPU подготовка варианта может занять несколько минут.')
        intro.setWordWrap(True); layout.addWidget(intro)
        self.server = self.path_row(layout, 'Движок llama-server.exe', 'expert_server', 'Движок (*)')
        self.model = self.path_row(layout, 'Модель GGUF', 'expert_model', 'Модель (*.gguf)')
        layout.addWidget(QLabel('Что сделать с текстом?'))
        self.instruction = QPlainTextEdit(window.library.get_setting('expert_instruction') or DEFAULT_INSTRUCTION)
        self.instruction.setMaximumHeight(90)
        self.instruction.setPlaceholderText('Например: перепиши весь протокол профессионально, структурируй описание и заключение.')
        layout.addWidget(self.instruction)
        self.whole_document = QCheckBox('Обработать весь протокол')
        self.whole_document.setChecked(not window.editor.textCursor().hasSelection())
        self.whole_document.toggled.connect(self.change_scope)
        layout.addWidget(self.whole_document)
        layout.addWidget(QLabel('Исходный текст'))
        self.source = QPlainTextEdit(self.source_text); self.source.setReadOnly(True); layout.addWidget(self.source)
        layout.addWidget(QLabel('Новый вариант — появится после обработки. Затем нажмите «Заменить текст в редакторе».'))
        self.result = QPlainTextEdit(); self.result.setReadOnly(True); layout.addWidget(self.result)
        self.review_confirm = QCheckBox('Я проверил отмеченные различия и хочу применить вариант')
        self.review_confirm.setVisible(False)
        self.review_confirm.toggled.connect(lambda checked: self.apply.setEnabled(bool(self.result.toPlainText().strip()) and (not self.issues or checked)))
        layout.addWidget(self.review_confirm)
        self.status = QLabel('Нажмите «Новый вариант». Исходный документ останется без изменений.')
        self.status.setWordWrap(True); layout.addWidget(self.status)
        row = QHBoxLayout(); layout.addLayout(row)
        self.generate = QPushButton('Новый вариант'); self.generate.clicked.connect(self.start_generation); row.addWidget(self.generate)
        self.stop = QPushButton('Остановить'); self.stop.setEnabled(False); self.stop.clicked.connect(self.stop_generation); row.addWidget(self.stop)
        self.apply = QPushButton('Заменить текст в редакторе'); self.apply.setEnabled(False); self.apply.clicked.connect(self.apply_variant); row.addWidget(self.apply)
        close = QPushButton('Закрыть'); close.clicked.connect(self.close); row.addWidget(close)

    def path_row(self, layout, label, key, file_filter):
        layout.addWidget(QLabel(label))
        row = QHBoxLayout(); layout.addLayout(row)
        value = self.window.library.get_setting(key)
        if not value and key == 'expert_server':
            value = default_server_path()
        field = QLineEdit(value); row.addWidget(field)
        field.editingFinished.connect(lambda: self.window.library.set_setting(key, field.text().strip()))
        choose = QPushButton('Выбрать…'); row.addWidget(choose)
        def select():
            path, _ = QFileDialog.getOpenFileName(self, label, '', file_filter)
            if path:
                field.setText(path)
                self.window.library.set_setting(key, path)
        choose.clicked.connect(select)
        return field

    def change_scope(self, whole):
        self.snapshot = self.window.editor.toPlainText()
        self.target = QTextCursor(self.window.editor.textCursor())
        if whole or not self.target.hasSelection(): self.target.select(QTextCursor.SelectionType.Document)
        self.source_text = self.target.selectedText().replace('\u2029', '\n')
        self.source.setPlainText(self.source_text)
        self.result.clear()
        self.apply.setEnabled(False)
        self.review_confirm.setChecked(False)
        self.review_confirm.hide()

    def is_busy(self): return self.thread is not None and self.thread.isRunning()

    def start_generation(self):
        if self.is_busy(): return
        self.window.library.set_setting('expert_server', self.server.text().strip())
        self.window.library.set_setting('expert_model', self.model.text().strip())
        self.window.library.set_setting('expert_instruction', self.instruction.toPlainText().strip())
        self.review_confirm.setChecked(False); self.review_confirm.hide()
        self.whole_document.setEnabled(False); self.instruction.setEnabled(False)
        self.apply.setEnabled(False); self.generate.setEnabled(False)
        self.result.clear(); self.issues = []
        self.stop.setEnabled(True)
        self.status.setText('Готовлю новый текст. Если модель повторит исходник, повторю запрос один раз. Можно остановить.')
        self.thread = GenerationThread(self.server.text().strip(), self.model.text().strip(), self.source_text, self.instruction.toPlainText(), self)
        self.thread.completed.connect(self.receive_result)
        self.thread.failed.connect(self.receive_error)
        worker = self.thread
        def finished():
            self.generate.setEnabled(True)
            self.stop.setEnabled(False)
            self.whole_document.setEnabled(True); self.instruction.setEnabled(True)
            self.thread = None
            worker.deleteLater()
        self.thread.finished.connect(finished)
        self.thread.start()

    def stop_generation(self):
        if self.thread is not None:
            self.thread.cancelled.set()
            self.stop.setEnabled(False)
            self.status.setText('Останавливаю локальную модель…')

    def receive_result(self, text):
        if self.thread is not None and self.thread.cancelled.is_set():
            self.receive_error('Запрос остановлен.'); return
        if same_text(self.source_text, text):
            self.receive_error('Модель вернула исходный текст без изменений. Новый вариант не создан. Уточните запрос.'); return
        repeated = self.result.toPlainText() == text
        self.result.setPlainText(text)
        issues = self.issues = review_issues(self.source_text, text)
        self.review_confirm.setChecked(False)
        self.review_confirm.setVisible(bool(issues))
        self.status.setText('\n'.join(issues) if issues else 'Новый вариант готов. Проверьте текст и нажмите «Заменить текст в редакторе» — до этого исходник не меняется.')
        if repeated and not issues:
            self.status.setText('Модель повторила предыдущий вариант. Можно запросить ещё один.')
        self.apply.setEnabled(not issues and bool(text.strip()))

    def receive_error(self, text):
        self.result.clear(); self.review_confirm.setChecked(False); self.review_confirm.hide()
        self.status.setText(text); self.apply.setEnabled(False)

    def apply_variant(self):
        if not self.apply.isEnabled() or (self.issues and not self.review_confirm.isChecked()): return
        if self.window.editor.toPlainText() != self.snapshot:
            self.status.setText('Документ изменён после открытия помощника. Закройте окно и выберите текст заново.')
            self.apply.setEnabled(False); return
        start = self.target.selectionStart()
        self.target.beginEditBlock()
        self.target.insertText(self.result.toPlainText())
        self.target.endEditBlock()
        end = self.target.position()
        self.target.setPosition(start)
        self.target.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self.apply.setEnabled(False)
        self.status.setText('Вариант применён. Ctrl+Z отменяет замену.')
        self.snapshot = self.window.editor.toPlainText()

    def reject(self):
        self.close()

    def closeEvent(self, event):
        if self.is_busy():
            self.stop_generation()
            self.status.setText('Останавливаю обработку. Закройте окно после остановки.')
            event.ignore()
        else: event.accept()
