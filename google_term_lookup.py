"""Autonomous term-only lookup policy. No protocol text reaches the browser adapter."""
import re
from urllib.parse import urlencode,urlsplit
from PySide6.QtCore import QObject,QTimer
from radiology_ai import SENSITIVE,WORDS,classify,CRITICAL

AREAS={'ГМ','Позвоночник','ОМТ','Суставы','Брюшная полость','Мягкие ткани','Сосуды','Другие исследования'}
PRIVATE=re.compile(r'фио|пациент|паспорт|телефон|адрес|дата|рожден|рождён|карта|истори\w*\s+болез|снилс|@|https?://|\d{4,}|\d[./-]\d|[\n\r<>\[\]{}]',re.I)
MEDICAL=re.compile(r'^(?:интра|экстра|суб|супра|пара|пери|ретро|транс|юкс|гипер|гипо|миел|энцефал|хондр|спондил|нейро|ангио)[а-яё-]{5,}$',re.I)

def allowed_url(url):
    try:
        parts=urlsplit(url)
        return (parts.scheme=='https' and parts.hostname=='www.google.com' and parts.port in (None,443) and not parts.username and not parts.password) or url=='about:blank' or parts.scheme in ('data','qrc') or url.startswith('blob:https://www.google.com/')
    except ValueError:return False

def sanitized_query(term,area=''):
    term=term.strip()
    if not 2<=len(term)<=80 or PRIVATE.search(term):raise ValueError('В поиске допустим только медицинский термин без персональных данных.')
    if not re.fullmatch(r'[А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z -]{1,79}',term):raise ValueError('Выделите отдельный термин, без чисел и данных исследования.')
    words=term.split()
    if len(words)>4 or sum(w[:1].isupper() for w in words)>=3:raise ValueError('Запрос похож на персональные данные или фрагмент протокола.')
    return term+' медицинский термин МРТ'+(' '+area if area in AREAS and area!='Другие исследования' else '')

def search_url(term,area='',ai=True):
    query=sanitized_query(term,area)
    return 'https://www.google.com/search?'+urlencode({'q':query,**({'udm':'50'} if ai else {})})

def uncertain_terms(text,known=()):
    if PRIVATE.search(text) or SENSITIVE.search(text):return []
    known={w.casefold() for w in known};out=[]
    for match in WORDS.finditer(text):
        word=match.group();prefix=text[max(0,match.start()-50):match.start()].casefold()
        eponym=bool(re.search(r'(?:классификац\w*|шкал\w*|синдром\w*|симптом\w*)\s+(?:по\s+)?$',prefix))
        if word.casefold() in known or CRITICAL.fullmatch(word):continue
        if MEDICAL.fullmatch(word) or eponym:
            try:sanitized_query(word)
            except ValueError:continue
            out.append(word)
    return list(dict.fromkeys(out))[:3]

class TermLookup(QObject):
    def __init__(self,window,allow_network=False,browser_factory=None):
        super().__init__(window);self.window=window;self.allow_network=allow_network;self.factory=browser_factory;self.browser=None;self.version=0;self.attempted=set();self.count=0;self.closed=False;self.busy=False
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(2200);self.timer.timeout.connect(self.analyze)
        window.editor.textChanged.connect(self.changed)
    def changed(self):
        self.version+=1;self.timer.start()
    def cancel(self):
        self.busy=False
        if self.browser:self.browser.cancel()
    def reset(self):self.version+=1;self.attempted.clear();self.count=0;self.cancel();self.timer.stop()
    def close(self):
        if self.closed:return
        self.closed=True;self.timer.stop();self.cancel()
        if self.browser:self.browser.close()
    def analyze(self):
        w=self.window
        if self.closed or not self.allow_network or w.isMinimized() or self.busy or self.count>=3 or w.library.get_setting('google_terms_auto')=='0':return
        resources=getattr(w,'hybrid',None)
        if resources and resources.busy:
            self.timer.start(1800);return
        if resources and resources.resource_state.get('resources',{}).get('available_gb',0)<2:return
        text=w.editor.textCursor().block().text();area=classify(w.editor.document().firstBlock().text()+' '+text)
        known=set(w.library.ai.words)|set(w.live_spelling.personal)
        for term in uncertain_terms(text,known):
            if term.casefold() in self.attempted or term.casefold() in w.glossary.records:continue
            # Ordinary near-certain typos stay local. Search only genuinely uncertain terminology.
            candidates=w.library.ai.corrections(term)
            if candidates:
                from rapidfuzz.distance import DamerauLevenshtein
                if DamerauLevenshtein.distance(term.casefold(),candidates[0].casefold())<=1:continue
            try:self.lookup(term,area)
            except (ValueError,OSError,ImportError,RuntimeError):
                self.window.reference.term_status.setText('Автосправка недоступна; локальный анализ продолжается.')
            break
    def lookup(self,term,area='',manual=False):
        url=search_url(term,area)
        if self.closed:return False
        cached=self.window.glossary.records.get(term.casefold())
        if cached:
            self.window.reference.show_term(term,cached['definition'],cached.get('source',''),cached['verified']);return True
        if self.count>=3:return False
        if not self.allow_network and not manual:return False
        if self.busy:return False
        self.attempted.add(term.casefold());self.count+=1;version=self.version
        if self.browser is None:
            if self.factory:self.browser=self.factory()
            else:
                from google_browser import GoogleBrowser
                self.browser=GoogleBrowser(self.window,self.window.glossary.path.parent/'google_profile')
        self.busy=True
        self.window.reference.term_status.setText('Уточнение термина в Google: '+term+'. Передаётся только термин и область.')
        def complete(text,source,error):
            self.busy=False
            if self.closed:return
            if error:
                self.window.reference.term_status.setText('Справка недоступна: '+error+'. Локальный анализ продолжается.');return
            try:self.window.glossary.save(term,text,source,verified=False)
            except (OSError,ValueError):
                self.window.reference.term_status.setText('Справка получена, но словарь не удалось сохранить.')
            if version==self.version:self.window.reference.show_term(term,text,source,False)
            else:self.window.reference.term_status.setText('Непроверенная справка сохранена в кэш: '+term)
        try:self.browser.search(url,complete)
        except Exception:self.busy=False;raise
        return True
