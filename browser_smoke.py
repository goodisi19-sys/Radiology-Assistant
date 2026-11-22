"""Real packaged Chromium rendering using a synthetic offline fixture; no Google request."""
import json,tempfile,time
from pathlib import Path
from PySide6.QtCore import Qt,QUrl
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtTest import QTest

def run(target):
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    application=QApplication.instance() or QApplication([])
    from google_browser import GoogleBrowser
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        owner=QWidget();browser=GoogleBrowser(owner,Path(tmp));result=[]
        browser.callback=lambda text,source,error:result.append((text,error))
        browser.timeout.start(10000)
        text='Обзор от ИИ. '+('Синтетическая справка по медицинскому термину. '*12)
        browser.page.setHtml('<main id="search">'+text+'</main>',QUrl('about:blank'))
        start=time.perf_counter()
        while not result and time.perf_counter()-start<12:QTest.qWait(50)
        assert result and not result[0][1] and 'Синтетическая справка' in result[0][0],result
        elapsed=time.perf_counter()-start;browser.close();QTest.qWait(300)
        Path(target).write_text(json.dumps({'chromium_renderer':'ok','offline_fixture':'ok','extraction':'ok','elapsed_s':elapsed,'real_google_ai_mode':'not tested against corporate firewall'},ensure_ascii=False),encoding='utf8')
