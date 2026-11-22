"""Automatic idle analysis. One running job, one replacement; Qt/SQLite stay on GUI."""
import hashlib, re, time
from concurrent.futures import ThreadPoolExecutor
from queue import SimpleQueue
from collections import OrderedDict
from PySide6.QtCore import QTimer
from hybrid_backend import NeuralBackend
from resource_policy import ResourcePolicy, sample
from radiology_ai import classify

class HybridCoordinator:
    def __init__(self,window):
        self.window=window;self.version=0;self.closed=False;self.backend=NeuralBackend();self.policy=ResourcePolicy()
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='hybrid-dispatch')
        self.results=SimpleQueue();self.busy=False;self.cache=OrderedDict();self.last_status='LocalAI активен';self.failure='';self.completion_scores={}
        self.resource_state={};self.cooldown=0;self.text_snapshot='';self.pending_search=None
        self.timer=QTimer(window);self.timer.setSingleShot(True);self.timer.setInterval(650);self.timer.timeout.connect(self.analyze)
        self.poll=QTimer(window);self.poll.setInterval(80);self.poll.timeout.connect(self.drain);self.poll.start()
        self.monitor=QTimer(window);self.monitor.setInterval(5000);self.monitor.timeout.connect(self.resources);self.monitor.start()
        window.editor.textChanged.connect(self.changed)
        self.resources()
    def resources(self):
        if self.closed:return
        try:
            if not self.busy and self.backend.last_used and time.monotonic()-self.backend.last_used>120:self.backend.cancel()
            previous_deep=self.resource_state.get('deep',False)
            self.resource_state=self.policy.choose(sample(),self.window.library.get_setting('hybrid_mode') or 'Автоматический')
            self.timer.setInterval(4000)
            if previous_deep and not self.resource_state.get('deep'):self.backend.cancel()
            if self.window.isMinimized() or not self.resource_state['bert'] or not self.window.library.ai.enabled('neural_enabled'):
                self.backend.cancel();self.last_status='LocalAI активен — нейроанализ приостановлен'
            elif not self.busy:
                self.last_status='LocalAI активен — '+self.resource_state['mode'].lower()+' профиль'
        except Exception:self.resource_state={'bert':False,'deep':False,'mode':'Экономичный','threads':1};self.last_status='LocalAI активен — ресурсы недоступны'
        if hasattr(self.window,'hybrid_indicator'):self.window.hybrid_indicator.setText(self.last_status)
    def changed(self):
        if self.closed:return
        self.version+=1
        # Keep a warm worker; stale results are discarded by revision.
        self.timer.start()
    def reset(self):
        self.version+=1;self.cache.clear();self.backend.cancel();self.timer.stop()
    def close(self):
        self.closed=True;self.timer.stop();self.poll.stop();self.monitor.stop();
        if hasattr(self,'search_poll'):self.search_poll.stop()
        self.backend.close();self.executor.shutdown(wait=False,cancel_futures=True)
    def allowed(self):
        return not self.closed and not self.window.isMinimized() and self.window.library.ai.enabled('neural_enabled') and self.resource_state.get('bert',False) and self.resource_state.get('resources',{}).get('cpu',100)<40 and time.monotonic()>self.cooldown
    def analyze(self):
        if self.closed:return
        if self.busy:self.timer.start(400);return
        if not self.allowed():return
        editor=self.window.editor;block=editor.textCursor().block().text()
        if len(block.strip())<8:return
        from context_identity import context_key
        state=self.window.protocol_context.update(editor.toPlainText(),editor.document().revision())
        digest=context_key('analysis',block,area=state.area,kind=state.modality,model='rubert-tiny2+sage-v1')
        if digest in self.cache:return
        area=state.area if self.window.library.ai.enabled('auto_area') else ''
        issues=self.window.live_spelling.cache.get(block,())
        tasks=[]
        for issue in issues[:3]:
            before,after=block[:issue.start],block[issue.end:]
            candidates=self.window.library.ai.ranked_corrections(issue.word,before,after,area)
            if candidates:tasks.append((issue.word,before,after,tuple(candidates)))
        cursor=editor.textCursor()
        cursor_before=block.encode('utf-16-le')[:cursor.positionInBlock()*2].decode('utf-16-le')
        prefix=re.search(r'[А-Яа-яЁё]{3,}$',cursor_before)
        if prefix:
            word=prefix.group();before=cursor_before[:-len(word)];after=block[len(cursor_before):]
            if not any(t[0]==word and t[1]==before for t in tasks):
                options=self.window.library.ai.complete(word,before,area)
                if options:tasks.append((word,before,after,tuple(options)))
        if self.window.library.ai.enabled('grammar_warnings'):
            from medical_grammar import candidates as grammar_candidates
            for start,end,word,value in grammar_candidates(block)[:2]:
                tasks.append((word,block[:start],block[end:],(word,value)))
        # Context classification from the same encoder; no diagnostic head is claimed.
        prototypes=[('ГМ','МРТ головного мозга. Срединные структуры.'),('Позвоночник','МРТ позвоночника. Межпозвонковые диски.'),('ОМТ','МРТ органов малого таза.'),('Суставы','МРТ сустава. Связки и мениски.'),('Брюшная полость','КТ органов брюшной полости. Печень и почки.'),('Мягкие ткани','МРТ мягких тканей.'),('Сосуды','МР ангиография артерий и вен.')]
        version=self.version
        cursor_snapshot=(cursor.position(),cursor.anchor())
        completion_after=block[len(cursor_before):]
        completion_pool=self.window.completion_index.suggest(cursor_before,completion_after,area,state.modality,30)
        completion_key=context_key('completion',cursor_before,completion_after,area,state.modality,[v['source_id']+v['suffix'] for v in completion_pool],model='rubert-tiny2-v1')
        definitions=self.window.glossary.verified_context(block) if hasattr(self.window,'glossary') else []
        glossary_context=' '.join(term+': '+definition for term,definition in definitions)[:350]
        settings=dict(self.resource_state)
        self.busy=True;self.last_status=('Глубокий анализ' if settings.get('deep') and tasks else 'Контекстный анализ');cache_path=self.window.library.path.parent/'hybrid-embeddings.sqlite3'
        def work():
            try:
                if self.closed or version!=self.version:raise RuntimeError('cancelled')
                classification=self.backend.semantic(block,[p[1] for p in prototypes],settings['threads'],cache_path)
                if completion_pool:
                    classification['completion_key']=completion_key
                    classification['completion_scores']=self.backend.semantic(cursor_before+' '+completion_after,[c['phrase'] for c in completion_pool],settings['threads'],cache_path,timeout=3)['scores']
                    classification['completion_ids']=[c['source_id']+c['suffix'] for c in completion_pool]
                classification['cursor_snapshot']=cursor_snapshot
                ranked=[]
                for word,before,after,options in tasks:
                    if self.closed or version!=self.version:return self.results.put((version,digest,block,area,[],None,'cancelled'))
                    context=before[-180:]+word+after[:180]
                    rendered=[before[-180:]+c+after[:180] for c in options]
                    scores=self.backend.semantic(context+(' Справочник: '+glossary_context if glossary_context else ''),rendered,settings['threads'],cache_path)['scores']
                    deep_scores=None
                    if settings.get('deep') and len(options)>1:
                        try:
                            deep_scores=self.backend.deep(context,rendered,settings['threads'],cache_path)['scores']
                        except Exception:pass # Retain already computed lexical/encoder results on deadline.
                    ranked.append((word,before,after,options,scores,deep_scores))
                self.results.put((version,digest,block,area,ranked,classification,None))
            except Exception as e:self.results.put((version,digest,block,area,[],None,type(e).__name__))
        self.executor.submit(work)
    def drain(self):
        while not self.results.empty():
            version,digest,block,area,ranked,classification,error=self.results.get();self.busy=False
            if self.closed or version!=self.version:continue
            if error:
                self.failure=error;self.last_status='LocalAI активен — нейромодуль недоступен';self.cooldown=time.monotonic()+60
                # No raw text or exception detail is logged or shown.
                continue
            from context_identity import context_key
            if classification and classification.get('cursor_snapshot') is not None:
                cursor=self.window.editor.textCursor()
                if classification['cursor_snapshot']!=(cursor.position(),cursor.anchor()):continue
            if classification and 'completion_key' in classification:
                self.completion_scores[classification['completion_key']]=dict(zip(classification['completion_ids'],classification['completion_scores']))
                while len(self.completion_scores)>64:self.completion_scores.pop(next(iter(self.completion_scores)))
                popup=self.window.completer.popup()
                if popup.isVisible():
                    selected=popup.currentIndex().data()
                    self.window.update_suggestions()
                    labels=self.window.completion_model.stringList()
                    if selected in labels:popup.setCurrentIndex(popup.model().index(labels.index(selected),0))
            ai=self.window.library.ai
            for word,before,after,options,scores,deep_scores in ranked:
                values=dict(zip(options,scores))
                if deep_scores:
                    import math
                    top=max(deep_scores)
                    weights=[math.exp(s-top) for s in deep_scores]
                    ai.deep_scores[context_key('word',before+word,after,area,candidates=options,model='hybrid-v1')]=dict(zip(options,weights))
                    while len(ai.deep_scores)>256:ai.deep_scores.pop(next(iter(ai.deep_scores)))
                ai.neural_scores[context_key('word',before+word,after,area,candidates=options,model='hybrid-v1')]=values
                while len(ai.neural_scores)>256:ai.neural_scores.pop(next(iter(ai.neural_scores)))
            self.cache[digest]=True
            while len(self.cache)>256:self.cache.popitem(last=False)
            self.last_status='LocalAI активен · контекст проверен'
            if classification and ai.enabled('auto_area'):
                labels=['ГМ','Позвоночник','ОМТ','Суставы','Брюшная полость','Мягкие ткани','Сосуды']
                scores=classification['scores'];order=sorted(range(len(scores)),key=lambda i:scores[i],reverse=True)
                self.inferred_area=labels[order[0]] if scores[order[0]]-scores[order[1]]>.1 else area
        if hasattr(self.window,'hybrid_indicator'):
            self.window.hybrid_indicator.setText(self.last_status)
        self.start_pending_search()
    def start_pending_search(self):
        if self.pending_search and not self.busy and self.allowed():
            task=self.pending_search;self.pending_search=None
            self.semantic_search(*task)
    def semantic_search(self,query,rows,callback):
        """Cached template/content/favorite/quick-line retrieval on the same bounded worker."""
        if not rows or not self.allowed():return
        if self.busy:
            self.pending_search=(query,rows,callback)
            return
        # A lexical shortlist bounds neural work; do not encode the entire library on every search.
        lexical=self.window.library.ai.search(query,rows,limit=60)
        snapshot=tuple(lexical[:60] or rows[:60]);version=self.version;self.busy=True
        cache=self.window.library.path.parent/'hybrid-embeddings.sqlite3'
        def work():
            try:
                scores=self.backend.semantic(query,[' '.join(str(x) for x in r[1:])[:1000] for r in snapshot],self.resource_state.get('threads',1),cache,timeout=8)['scores']
                result=sorted(zip(scores,snapshot),key=lambda x:-x[0])[:30]
                self.search_results.put((query,version,callback,[r for s,r in result if s>.45]))
            except Exception:self.search_results.put((query,version,callback,[]))
        if not hasattr(self,'search_results'):
            self.search_results=SimpleQueue();self.search_poll=QTimer(self.window);self.search_poll.setInterval(100);self.search_poll.timeout.connect(self.drain_search);self.search_poll.start()
        self.executor.submit(work)
    def drain_search(self):
        while not self.search_results.empty():
            query,version,callback,rows=self.search_results.get();self.busy=False
            if not self.closed and version==self.version:callback(query,rows)
        self.start_pending_search()
