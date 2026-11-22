"""Technical Chromium view. Only www.google.com is allowed; no captcha bypass."""
import json
from PySide6.QtCore import QUrl,QTimer
from PySide6.QtWidgets import QDialog,QVBoxLayout,QPushButton
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
 if (/unusual traffic|not a robot|не робот|подозрительный трафик/i.test(text))
   return {blocked:true,url:location.href,text:''};
 const main=document.querySelector('#search')||document.querySelector('main')||document.body;
 const output=(main ? main.innerText : '').trim();
 return {blocked:false,url:location.href,text:output.slice(0,4000),
   ai:/AI Overview|Обзор от ИИ/i.test(output) || (new URL(location.href).searchParams.get('udm')==='50' && output.length>350 && !document.querySelector('[aria-busy="true"],[role="progressbar"]'))};
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
        button=QPushButton('Скрыть страницу');button.clicked.connect(self.hide);layout.addWidget(button)
        self.timeout=QTimer(self);self.timeout.setSingleShot(True);self.timeout.timeout.connect(self.expired)
        self.poll=QTimer(self);self.poll.setInterval(700);self.poll.timeout.connect(self.extract)
        self.fallback_timer=QTimer(self);self.fallback_timer.setSingleShot(True);self.fallback_timer.timeout.connect(self.fallback_search)
        self.callback=None;self.best='';self.best_url='';self.token=0;self.fallback=False
        self.page.loadFinished.connect(self.loaded)
        self.page.renderProcessTerminated.connect(lambda *_:self.finish('', 'браузерный процесс остановлен'))
    def search(self,url,callback):
        if not allowed_url(url) or not url.startswith('https://www.google.com/search?'):raise ValueError('Invalid Google URL')
        self.cancel();self.callback=callback;self.token+=1;self.best='';self.best_url=url;self.fallback=False
        self.page.setLifecycleState(QWebEnginePage.LifecycleState.Active)
        self.timeout.start(10000);self.fallback_timer.start(6500);self.page.load(QUrl(url))
    def loaded(self,ok):
        if not self.callback:return
        if ok:self.poll.start();self.extract()
        elif not self.fallback:self.fallback_search()
    def fallback_search(self):
        if not self.callback or self.fallback:return
        self.fallback=True;url=QUrl(self.best_url)
        from PySide6.QtCore import QUrlQuery
        query=QUrlQuery(url);query.removeAllQueryItems('udm');url.setQuery(query)
        self.page.load(url)
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
            if not allowed_url(source):return
            if isinstance(text,str) and len(text.strip())>120:
                self.best=text;self.best_url=source
                if result.get('ai') or self.fallback:self.finish(text,'')
        self.page.runJavaScript(EXTRACT,received)
    def expired(self):self.finish(self.best,'' if self.best else 'нет ответа за 10 секунд / доступ ограничен')
    def finish(self,text,error):
        if self.callback is None:return
        callback=self.callback;source=self.best_url;self.callback=None;self.poll.stop();self.timeout.stop();self.fallback_timer.stop();self.view.stop()
        if not self.isVisible():self.page.setLifecycleState(QWebEnginePage.LifecycleState.Frozen)
        if callback:callback(text,source,error)
    def cancel(self):
        self.token+=1;self.callback=None;self.poll.stop();self.timeout.stop();self.fallback_timer.stop();self.view.stop()
    def closeEvent(self,event):
        self.cancel();self.hide();event.ignore() # Closing the inspector never closes the editor.
    def close(self):
        self.cancel();self.page.deleteLater();self.profile.deleteLater();self.deleteLater()
