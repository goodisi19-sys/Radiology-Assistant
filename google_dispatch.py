"""Explicit handoff to the OS browser. No HTTP client, renderer, parsing or training."""
from dataclasses import dataclass
from PySide6.QtCore import QUrl,QUrlQuery

MAX_QUERY_URL_BYTES = 7500


def google_url(question='', ai_mode=True):
    url=QUrl('https://www.google.com/search');query=QUrlQuery()
    if question:query.addQueryItem('q',question)
    if ai_mode:query.addQueryItem('udm','50')
    url.setQuery(query);return url


@dataclass(frozen=True)
class DispatchResult:
    opened:bool
    copied:bool
    message:str


def open_review(prompt, open_url=None, copy_text=None):
    """Call only after the editable preview was accepted. Never truncate protocols."""
    if not prompt.strip():return DispatchResult(False,False,'Нет текста для отправки.')
    if open_url is None:
        from PySide6.QtGui import QDesktopServices
        open_url=QDesktopServices.openUrl
    if copy_text is None:
        from PySide6.QtWidgets import QApplication
        copy_text=QApplication.clipboard().setText
    url=google_url(prompt)
    if len(url.toEncoded())>MAX_QUERY_URL_BYTES:
        copy_text(prompt)
        opened=bool(open_url(google_url()))
        return DispatchResult(opened,True,'Полный запрос скопирован. Вставьте его в Google через Ctrl+V.' if opened else 'Запрос скопирован. Откройте Google в браузере и вставьте через Ctrl+V.')
    opened=bool(open_url(url))
    return DispatchResult(opened,False,'Запрос открыт в браузере по умолчанию. Ответ проверяйте в браузере.' if opened else 'Не удалось открыть браузер по умолчанию. Запрос не отправлен.')
