"""Technical Chromium view. Only www.google.com is allowed; no captcha bypass."""
import json,time
from PySide6.QtCore import QUrl,QTimer,Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QPushButton,QLabel
from PySide6.QtWebEngineCore import QWebEngineProfile,QWebEnginePage,QWebEngineUrlRequestInterceptor,QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView


from google_term_lookup import allowed_url

class GoogleOnly(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self,info):
        if not allowed_url(info.requestUrl().toString()):info.block(True)

class GooglePage(QWebEnginePage):
    def acceptNavigationRequest(self,url,kind,main):return allowed_url(url.toString())
    def createWindow(self,kind):return None

EXTRACT=r'''(() => {
 const text=(document.body && document.body.innerText)||'';
 if (/unusual traffic|not a robot|не робот|подозрительный трафик|before you continue to google|прежде чем перейти к google/i.test(text))
   return {blocked:true,url:location.href,text:''};
 // Fail closed when Google changes its DOM. Never interpret #search/main as an AI answer.
 if (location.hostname==='consent.google.com' || document.querySelector('form[action*="consent"],iframe[src*="recaptcha"],.g-recaptcha'))
   return {blocked:true,url:location.href,text:''};
 const boxes=[...document.querySelectorAll('[data-ai-response], [data-container-id="aim-response"], [data-testid="ai-response"], [data-attrid="AIOverview"], [aria-label="AI response"], [aria-label="Ответ ИИ"]')];
 for (const box of boxes) {
   if (box.closest('article') || box.querySelector('textarea,input,[contenteditable="true"]')) continue;
   const output=(box.innerText||'').trim();
   const match=output.match(/(?:^|\n)[ \t]*RAD_AI_ANSWER[ \t]*\r?\n([\s\S]{10,4000}?)\r?\n[ \t]*RAD_AI_END[ \t]*(?:\n|$)/);
   const busy=box.matches('[aria-busy="true"]')||box.querySelector('[aria-busy="true"],[role="progressbar"],[data-loading="true"],[data-skeleton],.skeleton');
   const complete=box.matches('[data-complete="true"],[aria-busy="false"]')||box.querySelector('button[aria-label*="Copy"],button[aria-label*="Копировать"]');
   if (match && !busy && complete) return {blocked:false,url:location.href,text:match[1].trim(),ai:true,complete:true};
 }
 return {blocked:false,url:location.href,text:'',ai:false,complete:false};
})()'''

EXTRACT='JSON.stringify('+EXTRACT+')'

class GoogleBrowser(QDialog):
    def __init__(self,parent,storage):
        super().__init__(parent);self.setWindowTitle('Google — справка по термину');self.resize(1000,720)
        storage.mkdir(parents=True,exist_ok=True)
        self.profile=QWebEngineProfile('MedicalTerms',self)
        self.profile.setPersistentStoragePath(str(storage/'storage'));self.profile.setCachePath(str(storage/'cache'))
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)
        self.interceptor=GoogleOnly(self);self.profile.setUrlRequestInterceptor(self.interceptor)
        self.profile.downloadRequested.connect(lambda item:item.cancel())
        self.page=GooglePage(self.profile,self);self.view=QWebEngineView(self);self.view.setPage(self.page)
        settings=self.page.settings();settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,False);settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard,False)
        layout=QVBoxLayout(self);layout.addWidget(self.view)
        self.diagnostic=QLabel();self.diagnostic.setTextFormat(Qt.TextFormat.PlainText);self.diagnostic.setWordWrap(True);layout.addWidget(self.diagnostic)
        self.last_certificate_error=''
        self.page.certificateError.connect(self.certificate_failed)
        button=QPushButton('Скрыть страницу');button.clicked.connect(self.hide);layout.addWidget(button)
        self.timeout_ms=max(1000,min(60000,int(parent.library.get_setting('google_timeout_ms') or 30000))) if hasattr(parent,'library') else 30000
        self.timeout=QTimer(self);self.timeout.setSingleShot(True);self.timeout.timeout.connect(self.expired)
        self.poll=QTimer(self);self.poll.setInterval(400);self.poll.timeout.connect(self.extract)
        self.callback=None;self.best_url='';self.token=0;self.stable_text='';self.stable_since=0
        self.page.loadFinished.connect(self.loaded)
        self.page.renderProcessTerminated.connect(lambda *_:self.finish('', 'браузерный процесс остановлен'))
    def search(self,url,callback):
        if not allowed_url(url) or not url.startswith('https://www.google.com/search?'):raise ValueError('Invalid Google URL')
        from urllib.parse import urlsplit,parse_qs
        if parse_qs(urlsplit(url).query).get('udm')!=['50']:raise ValueError('Требуется Google AI Mode')
        self.cancel();self.callback=callback;self.token+=1;self.best_url=url;self.stable_text='';self.stable_since=0;self.last_certificate_error='';self.diagnostic.clear()
        self.page.setLifecycleState(QWebEnginePage.LifecycleState.Active)
        self.timeout.start(self.timeout_ms);self.page.load(QUrl(url))
    def certificate_failed(self,error):
        from tls_diagnostics import reject_and_describe
        self.last_certificate_error=reject_and_describe(error)
        self.diagnostic.setText(self.last_certificate_error)
    def loaded(self,ok):
        if not self.callback:return
        if ok:self.poll.start();self.extract()
        else:self.finish('',self.last_certificate_error or 'страница Google AI Mode не загрузилась')
    def extract(self):
        if not self.callback:return
        token=self.token
        def received(result):
            if token!=self.token or not self.callback:return
            if isinstance(result,str):
                try:result=json.loads(result)
                except ValueError:return
            if not isinstance(result,dict):return
            if result.get('blocked'):
                self.finish('','Google требует проверку пользователя; откройте техническую страницу');return
            text=result.get('text','');source=result.get('url','')
            from urllib.parse import urlsplit,parse_qs
            if not allowed_url(source) or parse_qs(urlsplit(source).query).get('udm')!=['50']:return
            if parse_qs(urlsplit(source).query).get('q')!=parse_qs(urlsplit(self.best_url).query).get('q'):return
            if result.get('ai') and result.get('complete') and isinstance(text,str) and len(text.strip())>=10:
                if text!=self.stable_text:
                    self.stable_text=text;self.stable_since=time.monotonic();return
                if time.monotonic()-self.stable_since>=.8:
                    self.best_url=source;self.finish(text,'')
            else:self.stable_text='';self.stable_since=0
        self.page.runJavaScript(EXTRACT,received)
    def expired(self):self.finish('','Google AI Mode не вернул распознаваемый ответ за отведённое время; обычная выдача не используется')
    def finish(self,text,error):
        if self.callback is None:return
        callback=self.callback;source=self.best_url;self.callback=None;self.poll.stop();self.timeout.stop();self.view.stop()
        if not self.isVisible():self.page.setLifecycleState(QWebEnginePage.LifecycleState.Frozen)
        if callback:callback(text,source,error)
    def cancel(self):
        self.token+=1;self.callback=None;self.poll.stop();self.timeout.stop();self.view.stop()
    def closeEvent(self,event):
        self.cancel();self.hide();event.ignore() # Closing the inspector never closes the editor.
    def close(self):
        self.cancel();self.page.deleteLater();self.profile.deleteLater();self.deleteLater()
