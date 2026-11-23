"""Real packaged Chromium rendering; synthetic offline positive and negative fixtures."""
import json,tempfile,time
from pathlib import Path
from PySide6.QtCore import Qt,QUrl
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtTest import QTest

def run(target):
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    application=QApplication.instance() or QApplication([])
    from google_browser import GoogleBrowser,EXTRACT
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        owner=QWidget();browser=GoogleBrowser(owner,Path(tmp))
        def probe(html):
            result=[];loaded=[]
            slot=lambda ok:loaded.append(ok)
            browser.page.loadFinished.connect(slot)
            browser.page.setHtml(html,QUrl('about:blank'))
            deadline=time.perf_counter()+10
            while not loaded and time.perf_counter()<deadline:QTest.qWait(50)
            browser.page.loadFinished.disconnect(slot)
            assert loaded and loaded[-1],loaded
            browser.page.runJavaScript(EXTRACT,lambda data:result.append(json.loads(data)))
            while not result and time.perf_counter()<deadline:QTest.qWait(50)
            assert result,result
            return result[0]
        start=time.perf_counter()
        ordinary=probe('<main id="search">'+('Обзор от ИИ. Статья о медицинском термине. '*30)+'</main>')
        assert not ordinary['ai'] and not ordinary['text'],ordinary
        genuine=probe('<main><section data-ai-response data-complete="true"><div>RAD_AI_ANSWER</div><div>Синтетическая справка по медицинскому термину.</div><div>RAD_AI_END</div></section></main>')
        assert genuine['ai'] and 'Синтетическая справка' in genuine['text'],genuine
        echo=probe('<main>RAD_AI_ANSWER\nСкопированный вопрос не является ответом ИИ.\nRAD_AI_END</main>')
        assert not echo['ai'] and not echo['text'],echo
        streaming=probe('<main><section data-ai-response aria-busy="true">RAD_AI_ANSWER\nНезавершенный ответ по термину.\nRAD_AI_END</section></main>')
        assert not streaming['ai'],streaming
        captcha=probe('<main><form class="g-recaptcha">Confirm you are not a robot</form><section data-ai-response data-complete="true">RAD_AI_ANSWER<br>Fake answer during challenge.<br>RAD_AI_END</section></main>')
        assert captcha['blocked'] and not captcha['text'],captcha
        consent=probe('<main><form action="/consent">Before you continue to Google</form></main>')
        assert consent['blocked'] and not consent['text'],consent
        skeleton=probe('<main><section data-ai-response data-complete="true"><div data-skeleton></div>RAD_AI_ANSWER<br>Still loading this response.<br>RAD_AI_END</section></main>')
        assert not skeleton['ai'],skeleton
        elapsed=time.perf_counter()-start;browser.close();QTest.qWait(300)
        Path(target).write_text(json.dumps({'chromium_renderer':'ok','offline_fixture':'ok','extraction':'ok','ordinary_results_rejected':True,'captcha_consent_skeleton_rejected':True,'elapsed_s':elapsed,'real_google_ai_mode':'not tested against corporate firewall'},ensure_ascii=False),encoding='utf8')
