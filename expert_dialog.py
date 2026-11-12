from pathlib import Path
import sys

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QPlainTextEdit, QFileDialog, QCheckBox
from expert_assistant import generate_variant, review_issues, DEFAULT_INSTRUCTION


class GenerationThread(QThread):
    completed = Signal(str)
    failed = Signal(str)
    def __init__(self, server, model, source, instruction, parent=None):
        super().__init__(parent)
        self.arguments = server, model, source, instruction
    def run(self):
        try: self.completed.emit(generate_variant(*self.arguments))
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
            'CPU, 16 ГБ ОЗУ: Qwen2.5-3B-Instruct Q4_K_M (~2 ГБ). Первый ответ может занять несколько минут.')
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
        layout.addWidget(QLabel('Предлагаемый вариант — проверьте медицинский смысл перед применением'))
        self.result = QPlainTextEdit(); self.result.setReadOnly(True); layout.addWidget(self.result)
        self.review_confirm = QCheckBox('Я проверил отмеченные различия и хочу применить вариант')
        self.review_confirm.setVisible(False)
        self.review_confirm.toggled.connect(lambda checked: self.apply.setEnabled(bool(self.result.toPlainText().strip()) and (not self.issues or checked)))
        layout.addWidget(self.review_confirm)
        self.status = QLabel('Нажмите «Новый вариант». Исходный документ останется без изменений.')
        self.status.setWordWrap(True); layout.addWidget(self.status)
        row = QHBoxLayout(); layout.addLayout(row)
        self.generate = QPushButton('Новый вариант'); self.generate.clicked.connect(self.start_generation); row.addWidget(self.generate)
        self.apply = QPushButton('Применить вариант'); self.apply.setEnabled(False); self.apply.clicked.connect(self.apply_variant); row.addWidget(self.apply)
        close = QPushButton('Закрыть'); close.clicked.connect(self.close); row.addWidget(close)

    def path_row(self, layout, label, key, file_filter):
        layout.addWidget(QLabel(label))
        row = QHBoxLayout(); layout.addLayout(row)
        value = self.window.library.get_setting(key)
        if not value and key == 'expert_server':
            root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
            value = next((str(path) for path in (root / 'local-ai').rglob('llama-server.exe')), '')
        field = QLineEdit(value); row.addWidget(field)
        choose = QPushButton('Выбрать…'); row.addWidget(choose)
        def select():
            path, _ = QFileDialog.getOpenFileName(self, label, '', file_filter)
            if path: field.setText(path)
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
        self.status.setText('Загрузка локальной модели и подготовка варианта…')
        self.thread = GenerationThread(self.server.text().strip(), self.model.text().strip(), self.source_text, self.instruction.toPlainText(), self)
        self.thread.completed.connect(self.receive_result)
        self.thread.failed.connect(self.receive_error)
        worker = self.thread
        def finished():
            self.generate.setEnabled(True)
            self.whole_document.setEnabled(True); self.instruction.setEnabled(True)
            self.thread = None
            worker.deleteLater()
        self.thread.finished.connect(finished)
        self.thread.start()

    def receive_result(self, text):
        repeated = self.result.toPlainText() == text
        self.result.setPlainText(text)
        issues = self.issues = review_issues(self.source_text, text)
        self.review_confirm.setChecked(False)
        self.review_confirm.setVisible(bool(issues))
        self.status.setText('\n'.join(issues) if issues else 'Проверьте находки, отрицания, сторону и сигнальные характеристики. Затем примените вариант.')
        if repeated and not issues:
            self.status.setText('Модель повторила предыдущий вариант. Можно запросить ещё один.')
        self.apply.setEnabled(not issues and bool(text.strip()))

    def receive_error(self, text):
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
            self.status.setText('Дождитесь завершения локальной обработки, затем закройте окно.')
            event.ignore()
        else: event.accept()
