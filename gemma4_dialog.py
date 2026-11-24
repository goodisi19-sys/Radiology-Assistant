"""Experimental editor surface. All inference runs outside Qt's GUI thread."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import html
import difflib
import json
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QFormLayout, QLabel,
                               QLineEdit, QPushButton, QSpinBox, QTextBrowser)

from fragment_guard import FragmentGuard
from gemma4 import GemmaSession, discrepancies
from shorthand import expand_note


class GemmaDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle('Локальный ИИ — Gemma 4 (эксперимент)')
        self.resize(700, 500)
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.session = self.job = self.guard = None
        self.request_id = 0
        self.candidate = ''
        self.seen = set()
        layout = QFormLayout(self)
        self.expiry = QTimer(self, interval=180000, singleShot=True)
        self.expiry.timeout.connect(self.unload)
        self.enabled = QCheckBox('Включить на время сеанса')
        self.background = QCheckBox('Предлагать после паузы, пока открыто это окно')
        layout.addRow(self.enabled)
        layout.addRow(self.background)
        self.paths = {}
        for key, title, filter in [('engine', 'llama-server', 'Все файлы (*)'),
                                   ('model', 'Локальный GGUF', 'GGUF (*.gguf)')]:
            field = QLineEdit(window.library.get_setting('gemma4_'+key))
            self.paths[key] = field
            layout.addRow(title, field)
            button = QPushButton('Выбрать файл…')
            button.clicked.connect(lambda checked=False, field=field, filter=filter:
                                   self.pick(field, filter))
            layout.addRow(button)
        self.threads = QSpinBox()
        self.threads.setRange(1, 4)
        self.threads.setValue(2)
        layout.addRow('Потоки CPU', self.threads)
        for label, action in [('Загрузить модель', self.load), ('Выгрузить модель', self.unload),
                              ('Обработать выделенный текст', self.submit)]:
            button = QPushButton(label)
            button.clicked.connect(action)
            layout.addRow(button)
        self.diff = QTextBrowser()
        layout.addRow(self.diff)
        self.status = QLabel('Выберите совместимый llama-server и точный GGUF.')
        self.status.setWordWrap(True)
        layout.addRow(self.status)
        self.apply = QPushButton('Принять предложение')
        self.apply.setEnabled(False)
        self.apply.clicked.connect(self.accept_candidate)
        layout.addRow(self.apply)
        self.poll = QTimer(self, interval=100)
        self.poll.timeout.connect(self.drain)
        self.poll.start()
        self.idle = QTimer(self, interval=900, singleShot=True)
        self.idle.timeout.connect(self.background_request)
        self.enabled.toggled.connect(self.enabled_changed)
        window.editor.textChanged.connect(self.changed)

    def pick(self, field, filter):
        value, _ = QFileDialog.getOpenFileName(self, 'Выберите файл', field.text(), filter)
        if value:
            field.setText(value)

    def enabled_changed(self, enabled):
        if not enabled:
            self.unload()

    def unload(self, message='Модель выгружена.'):
        self.request_id += 1
        self.expiry.stop()
        if self.session:
            self.session.stop()
        self.session = None
        if self.guard:
            self.guard.close()
            self.guard = None
        self.apply.setEnabled(False)
        self.diff.clear()
        self.status.setText(message)

    def ready(self):
        if not self.enabled.isChecked() or self.job is not None or self.window.hybrid.busy:
            return False
        from resource_policy import sample
        resources = sample()
        if resources.available_gb < 6 or resources.cpu >= 60:
            self.status.setText('Для запуска требуется 6 ГиБ свободной памяти и загрузка CPU ниже 60%.')
            return False
        return True

    def start_session(self):
        values = {key: field.text().strip() for key, field in self.paths.items()}
        if not all(values.values()):
            self.status.setText('Укажите оба файла.')
            return None
        for key, value in values.items():
            self.window.library.set_setting('gemma4_'+key, value)
        self.session = GemmaSession(values['engine'], values['model'], self.threads.value())
        return self.session

    def load(self):
        if self.session or not self.ready():
            return
        session = self.start_session()
        if session:
            self.status.setText('Загрузка модели…')
            self.job = (self.request_id, self.pool.submit(session.load), None)

    def changed(self):
        self.apply.setEnabled(False)
        if self.job and self.job[2] is not None:
            self.unload('Документ изменился. Запрос отменён.')
        if self.enabled.isChecked() and self.background.isChecked():
            self.idle.start()

    def background_request(self):
        if (not self.background.isChecked() or not self.enabled.isChecked()
                or self.window.isMinimized() or self.window.completer.popup().isVisible()):
            return
        target = self.window.fragment_target()
        source = target.selectedText().strip()
        if not source.endswith(('.', ';')) or len(source.split()) < 4:
            return
        digest = sha256(source.encode()).digest()
        if digest in self.seen:
            return
        if self.submit(target):
            if len(self.seen) >= 512:
                self.background.setChecked(False)
                self.status.setText('Достигнут лимит фоновых фрагментов за сеанс.')
            self.seen.add(digest)

    def submit(self, target=None):
        if not self.ready():
            return False
        target = target if hasattr(target, 'selectedText') else self.window.editor.textCursor()
        source = target.selectedText().replace('\u2029', '\n').strip()
        block = self.window.protocol_context.update(
            self.window.editor.toPlainText(), self.window.editor.document().revision())
        section = block.at_qt(target.selectionStart())['section']
        end_section = block.at_qt(target.selectionEnd())['section']
        if (not source or len(source) > 1200 or '\n' in source or section == 'method'
                or end_section == 'method' or source.casefold().startswith(('методика', 'на серии'))):
            self.status.setText('Выберите одну строку описания или заключения длиной до 1200 символов.')
            return False
        try:
            personal = json.loads(self.window.library.get_setting('shorthand_personal') or '{}')
        except ValueError:
            personal = {}
        local, _ = expand_note(source, personal)
        if local and not discrepancies(source, local):
            self.show_result(source, local, 0, target, 'Локальное правило')
            return True
        cold = self.session is None
        session = self.session or self.start_session()
        if not session:
            return False
        context = self.window.ai_context()
        description = ' '.join((context['area'], context['modality'], section))
        examples = self.examples(source, context['area'])
        self.set_target(target)
        revision = self.window.editor.document().revision()
        digest = sha256(source.encode()).digest()
        self.request_id += 1

        def work():
            if cold:
                session.load()
            result, metrics = session.generate(source, description, examples)
            return result, metrics, discrepancies(source, result)

        self.expiry.stop()
        self.status.setText('Генерация…')
        self.job = (self.request_id, self.pool.submit(work), (source, revision, digest))
        return True

    def examples(self, source, area):
        from hybrid_safety import language_example
        rows = self.window.library.db.execute(
            "SELECT content FROM verified_standards WHERE category=? LIMIT 30", (area,))
        lines = [line.strip() for (text,) in rows for line in text.splitlines()]
        quick = self.window.library.db.execute(
            'SELECT text FROM quick_line_details WHERE builtin=0 AND category=? LIMIT 30', (area,))
        lines.extend(line.strip() for (text,) in quick for line in text.splitlines())
        words = set(source.casefold().split())
        safe = [line for line in lines if language_example(line)]
        safe.sort(key=lambda line: -len(words.intersection(line.casefold().split())))
        return safe[:3]

    def set_target(self, target):
        if self.guard:
            self.guard.close()
        self.guard = FragmentGuard(self.window.editor.document(), target)
        self.apply.setEnabled(False)
        self.diff.clear()

    def drain(self):
        if not self.job or not self.job[1].done():
            return
        request_id, future, snapshot = self.job
        self.job = None
        if request_id != self.request_id:
            return
        try:
            value = future.result()
        except Exception as error:
            self.unload(str(error))
            return
        self.expiry.start()
        if snapshot is None:
            self.status.setText(f'Модель загружена за {value:.1f} с.')
            return
        source, revision, digest = snapshot
        if (not self.guard or not self.guard.valid or revision != self.guard.document.revision()
                or digest != sha256(self.guard.cursor().selectedText().strip().encode()).digest()):
            return
        result, metrics, errors = value
        self.show_result(source, result, metrics['seconds'], errors=errors)

    def show_result(self, source, result, seconds, target=None, engine='Gemma', errors=None):
        if target is not None:
            self.set_target(target)
        if errors is None:
            errors = discrepancies(source, result)
        self.candidate = result
        diff = difflib.HtmlDiff().make_table([source], [result], 'Исходник', 'Предложение')
        warning = '<br>'.join(html.escape(error) for error in errors)
        self.diff.setHtml(f'<p style="color:#a21c1c">{warning}</p>{diff}')
        self.apply.setEnabled(not errors and source != result and self.guard.valid)
        self.status.setText(f'{engine} · {seconds:.2f} с. Проверьте медицинские факты перед применением.')

    def accept_candidate(self):
        if self.apply.isEnabled() and self.guard and self.guard.valid:
            self.guard.replace(self.candidate)
            self.apply.setEnabled(False)

    def reject(self):
        self.close()

    def closeEvent(self, event):
        self.idle.stop()
        self.poll.stop()
        self.unload()
        self.window.editor.textChanged.disconnect(self.changed)
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.deleteLater()
        event.accept()
