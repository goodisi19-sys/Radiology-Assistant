"""Explicit handoff to the OS browser. No HTTP client, renderer, parsing or training."""
from dataclasses import dataclass
from urllib.parse import urlencode,quote
from PySide6.QtCore import QUrl

MAX_QUERY_URL_BYTES = 7500


def google_url(question='', ai_mode=True):
    # QUrlQuery leaves literal '+' unescaped; search servers decode it as a
    # space. Preserve contrast/sequence notation such as T1+C on the wire.
    query={}
    if question:query['q']=question
    if ai_mode:query['udm']='50'
    # RFC 3986 permits '/' and '?' inside a query. Retain their readable form
    # for existing QUrlQuery callers while escaping '+', '&', '=' and '#'.
    return QUrl('https://www.google.com/search?'+urlencode(query,quote_via=quote,safe='/?'))


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
