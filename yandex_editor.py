"""Browser handoff to Yandex's own editor. No AI API, model, or automatic upload."""
import html
import json
import os
from pathlib import Path
import queue
import secrets
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                              QPlainTextEdit, QFileDialog, QLineEdit)


def browser_path():
    candidates = []
    for key in ('LOCALAPPDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)'):
        if os.environ.get(key): candidates.append(Path(os.environ[key]) / 'Yandex/YandexBrowser/Application/browser.exe')
    if os.name == 'nt':
        import winreg
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(root, r'Software\Microsoft\Windows\CurrentVersion\App Paths\browser.exe') as key:
                    value, _ = winreg.QueryValueEx(key, None)
                    if 'yandex' in value.casefold(): candidates.append(Path(value))
            except OSError: pass
    return next((str(path) for path in candidates if path.is_file()), '')


def page(source, result_path):
    return '''<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="referrer" content="no-referrer"><title>Radiology Assistant — Яндекс Редактор</title>
<style>body{font:17px system-ui;margin:24px auto;max-width:1100px;padding:0 20px;background:#f4f6f8;color:#202b38}
textarea{box-sizing:border-box;width:100%;height:58vh;font:18px/1.5 Georgia;background:white;color:#202b38;border:1px solid #aebdca;padding:18px}
button{font:inherit;padding:12px 18px;background:white;color:#202b38;border:1px solid #aebdca;border-radius:6px;margin-top:14px}
#status{white-space:pre-wrap}p{line-height:1.5}</style>
<h1>Яндекс Редактор</h1>
<p>1. Выделите текст в поле ниже → в меню Яндекс Браузера нажмите «Редактировать».
Выберите «Другими словами», «Улучшить стиль» или свой запрос. При необходимости откройте Редактор через новую вкладку браузера.</p>
<p>2. Нажмите «Заменить выделенный текст» / «Вставить на страницу» в Редакторе.
Если вы работали в отдельной вкладке Редактора, вставьте его результат обратно в поле ниже.</p>
<p>3. Нажмите «Вернуть в программу». В Radiology Assistant просмотрите новый текст и подтвердите замену.</p>
<label for="text">Текст для редактирования</label>
<textarea id="text" spellcheck="false" autocomplete="off">'''+html.escape(source)+'''</textarea>
<button id="send">Вернуть в программу</button><p id="status" role="status"></p>
<p>Это локальная служебная страница. Программа не отправляет текст в Яндекс автоматически.
Обработка в Яндексе начинается по вашему действию в его Редакторе. После закрытия окна обмена в программе связь прекращается.</p>
<script>
const button=document.getElementById('send'), status=document.getElementById('status');
button.addEventListener('click',async()=>{
 button.disabled=true;status.textContent='Возвращаю текст…';
 try{
  const response=await fetch('''+json.dumps(result_path)+''',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:document.getElementById('text').value})});
  if(!response.ok)throw new Error('Не удалось вернуть текст. Проверьте, что окно обмена в программе открыто.');
  status.textContent='Текст возвращён в программу на просмотр. Переключитесь в Radiology Assistant и нажмите «Заменить текст в редакторе».';
 }catch(error){status.textContent=error.message+' Можно скопировать текст и вставить его в программу вручную.';}
 finally{button.disabled=false;}
});
</script></html>'''


class BrowserBridge:
    def __init__(self, source):
        self.inbox = queue.Queue()
        self.token = secrets.token_urlsafe(24)
        self.root = '/' + self.token + '/'
        self.result_path = self.root + 'result'
        self.document = page(source, self.result_path).encode('utf-8')
        bridge = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass  # Never log medical text or the token.
            def reply(self, code, data=b''):
                self.send_response(code)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers(); self.wfile.write(data)
            def valid_host(self): return self.headers.get('Host') == urlsplit(bridge.origin).netloc
            def do_GET(self):
                if not self.valid_host() or self.path != bridge.root: self.reply(404); return
                self.reply(200, bridge.document)
            def do_POST(self):
                if not self.valid_host() or self.path != bridge.result_path or self.headers.get('Origin') != bridge.origin:
                    self.reply(403); return
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= 2_000_000: self.reply(413); return
                    if self.headers.get_content_type() != 'application/json': self.reply(415); return
                    payload = json.loads(self.rfile.read(size).decode('utf-8'))
                    text = payload['text']
                    if not isinstance(text, str) or not text.strip(): raise ValueError('Empty text')
                except (ValueError, KeyError, TypeError): self.reply(400); return
                bridge.inbox.put(text)
                self.reply(200, b'OK')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.origin = f'http://127.0.0.1:{self.server.server_port}'
        self.url = self.origin + self.root
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .1}, daemon=True)
        self.thread.start()
        self.closed = False

    def close(self):
        if self.closed: return
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
        self.closed = True


class YandexEditorDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.bridge = None
        self.snapshot = window.editor.toPlainText()
        self.target = QTextCursor(window.editor.textCursor())
        if not self.target.hasSelection(): self.target.select(QTextCursor.SelectionType.Document)
        self.source_text = self.target.selectedText().replace('\u2029', '\n')
        self.setWindowTitle('Яндекс Редактор — через установленный браузер')
        self.resize(850, 680)
        layout = QVBoxLayout(self)
        intro = QLabel('Откройте текст в Яндекс Браузере → вызовите его «Редактор» → верните результат кнопкой на странице.\n'
            'Локальная модель и API-ключ не нужны. Обработку выполняет встроенный Редактор Яндекс Браузера.')
        intro.setWordWrap(True); layout.addWidget(intro)
        row = QHBoxLayout(); layout.addLayout(row)
        self.browser = QLineEdit(window.library.get_setting('yandex_browser') or browser_path()); row.addWidget(self.browser, 1)
        self.browser.setPlaceholderText('Путь к установленному Яндекс Браузеру: browser.exe')
        choose = QPushButton('Выбрать браузер…'); choose.clicked.connect(self.choose_browser); row.addWidget(choose)
        self.open = QPushButton('Открыть текст в Яндекс Браузере'); self.open.clicked.connect(self.open_browser); layout.addWidget(self.open)
        layout.addWidget(QLabel('Исходный текст'))
        self.source = QPlainTextEdit(self.source_text); self.source.setReadOnly(True); layout.addWidget(self.source)
        layout.addWidget(QLabel('Текст, возвращённый из браузера — проверьте перед заменой'))
        self.result = QPlainTextEdit(); layout.addWidget(self.result)
        row = QHBoxLayout(); layout.addLayout(row)
        self.apply = QPushButton('Заменить текст в редакторе'); self.apply.setEnabled(False); self.apply.clicked.connect(self.apply_result); row.addWidget(self.apply)
        close = QPushButton('Закрыть'); close.clicked.connect(self.close); row.addWidget(close)
        self.status = QLabel('До подтверждения исходник в программе не меняется. Ctrl+Z отменяет замену.')
        self.status.setWordWrap(True); layout.addWidget(self.status)
        self.result.textChanged.connect(self.result_changed)
        self.timer = QTimer(self); self.timer.timeout.connect(self.poll_result); self.timer.start(200)

    def choose_browser(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Выберите browser.exe Яндекс Браузера', '', 'Программы (*.exe);;Все файлы (*)')
        if path: self.browser.setText(path)

    def open_browser(self):
        path = Path(self.browser.text().strip())
        if not path.is_file(): self.status.setText('Укажите установленный browser.exe Яндекс Браузера.'); return
        if not self.source_text.strip(): self.status.setText('В редакторе нет текста для передачи.'); return
        try:
            if self.bridge is None or self.bridge.closed: self.bridge = BrowserBridge(self.source_text)
            self.window.library.set_setting('yandex_browser', str(path))
            subprocess.Popen([str(path.resolve()), self.bridge.url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.status.setText('Текст открыт на локальной странице в Яндекс Браузере. Используйте его Редактор и нажмите «Вернуть в программу».')
        except Exception as exc:
            if self.bridge is not None: self.bridge.close(); self.bridge = None
            self.status.setText('Не удалось открыть браузер: ' + str(exc))

    def poll_result(self):
        if self.bridge is None: return
        latest = None
        while True:
            try: latest = self.bridge.inbox.get_nowait()
            except queue.Empty: break
        if latest is not None:
            self.result.setPlainText(latest)
            self.raise_(); self.activateWindow()

    def result_changed(self):
        text = self.result.toPlainText()
        same = ' '.join(text.split()) == ' '.join(self.source_text.split())
        self.apply.setEnabled(bool(text.strip()) and not same)
        self.status.setText('Возвращён исходник без изменений. Отредактируйте его в Яндекс Редакторе.' if same
            else 'Результат получен. Проверьте медицинские формулировки и подтвердите замену.')

    def apply_result(self):
        if not self.apply.isEnabled(): return
        if self.window.editor.toPlainText() != self.snapshot:
            self.apply.setEnabled(False); self.status.setText('Документ изменился. Закройте это окно и выберите текст заново.'); return
        start = self.target.selectionStart()
        self.target.beginEditBlock(); self.target.insertText(self.result.toPlainText()); self.target.endEditBlock()
        end = self.target.position()
        self.target.setPosition(start); self.target.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self.snapshot = self.window.editor.toPlainText()
        self.apply.setEnabled(False); self.status.setText('Текст заменён. Ctrl+Z отменяет замену.')

    def reject(self):
        self.close()

    def closeEvent(self, event):
        self.timer.stop()
        if self.bridge is not None: self.bridge.close()
        event.accept()
