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
            if self.timer.interval()!=4000:self.timer.setInterval(4000)
            if previous_deep and not self.resource_state.get('deep'):self.backend.cancel()
            if self.window.isMinimized() or not self.resource_state['bert'] or not self.window.library.ai.enabled('neural_enabled'):
                self.backend.cancel();self.completion_scores.clear();self.last_status='LocalAI активен — нейроанализ приостановлен'
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
        self.version+=1;self.cache.clear();self.completion_scores.clear();self.cooldown=0;self.failure='';self.backend.cancel();self.timer.stop()
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
        editor=self.window.editor;cursor=editor.textCursor();block=cursor.block().text()
        if len(block.strip())<3:return
        spelling=self.window.live_spelling
        if spelling.enabled and block not in spelling.cache:
            self.timer.start(400);return # Never cache an empty analysis before spelling is ready.
        from context_identity import context_key
        from word_scoring import word_key
        state=self.window.ai_context();area=state['area'];kind=state['modality']
        tasks=[]
        for issue in spelling.cache.get(block,())[:3]:
            before,after=block[:issue.start],block[issue.end:]
            options=self.window.library.ai.correction_candidates(issue.word,before,after,area,kind)
            tasks.append((issue.word,before,after,tuple(options)))
        cursor_before=block.encode('utf-16-le')[:cursor.positionInBlock()*2].decode('utf-16-le')
        completion_after=block[len(cursor_before):]
        prefix=re.search(r'[А-Яа-яЁё]{3,}$',cursor_before)
        if prefix and not cursor.hasSelection():
            word=prefix.group();before=cursor_before[:-len(word)]
            options=self.window.library.ai.editor_candidates(word,before,completion_after,area,kind)
            task=(word,before,completion_after,tuple(options))
            if options and task not in tasks:tasks.append(task)
        pool=self.window.completion_index.suggest(cursor_before,completion_after,area,kind,30) if not cursor.hasSelection() and self.window.library.get_setting('bert_phrase_rerank')=='1' else []
        completion_key=context_key('completion',cursor_before,completion_after,area,kind,[v['source_id']+v['suffix'] for v in pool],model='rubert-tiny2-v1')
        signature=[word_key(w,b,a,area,kind)+repr(opts) for w,b,a,opts in tasks]
        digest=context_key('analysis',block,area=area,kind=kind,candidates=signature+[completion_key,str(spelling.generation)],model='word-v2')
        if digest in self.cache:return
        if not tasks and not pool:
            self.last_status='Лексический анализ: нет задач для моделей';return
        version=self.version;cursor_snapshot=(cursor.position(),cursor.anchor());settings=dict(self.resource_state)
        trusted=frozenset(self.window.library.ai.words)
        self.busy=True;self.last_status='Фоновая проверка вариантов'
        cache_path=self.window.library.path.parent/'hybrid-embeddings.sqlite3'
        def cancelled():return self.closed or version!=self.version
        def work():
            metadata={'cursor_snapshot':cursor_snapshot,'extra_candidates':[],'sage_tasks':0,'bert_used':False}
            ranked=[]
            try:
                if cancelled():raise RuntimeError('cancelled')
                # RuBERT is a phrase/retrieval model, not a spelling likelihood model.
                if pool:
                    metadata['bert_used']=True
                    metadata['completion_key']=completion_key
                    metadata['completion_scores']=self.backend.semantic(cursor_before+' '+completion_after,[c['phrase'] for c in pool],settings['threads'],cache_path,timeout=3)['scores']
                    metadata['completion_ids']=[c['source_id']+c['suffix'] for c in pool]
                score_cache={}
                for word,before,after,options in tasks:
                    if cancelled():raise RuntimeError('cancelled')
                    if not options:
                        from spell_check import suggest
                        from rapidfuzz.distance import DamerauLevenshtein
                        from word_scoring import safe_word_correction,WORD
                        options=tuple(c for c in suggest(word) if WORD.fullmatch(c) and DamerauLevenshtein.distance(word.casefold(),c.casefold())<=2 and safe_word_correction(word,c,trusted))[:6]
                        if options:metadata['extra_candidates'].append((word_key(word,before,after,area,kind),options))
                    deep_scores=None
                    if settings.get('deep') and len(options)>1:
                        from word_scoring import local_window
                        key=word_key(word,before,after,area,kind);known=score_cache.setdefault(key,{})
                        left,_,right=local_window(before,word,after)
                        missing=[c for c in options if c not in known]
                        try:
                            for start in range(0,len(missing),6):
                                if cancelled():raise RuntimeError('cancelled')
                                chunk=missing[start:start+6]
                                values=self.backend.deep(left+word+right,[left+c+right for c in chunk],settings['threads'],cache_path)['scores']
                                known.update(zip(chunk,values))
                            if all(c in known for c in options):deep_scores=[known[c] for c in options];metadata['sage_tasks']+=1
                        except Exception:pass # Lexical suggestions remain available.
                    ranked.append((word,before,after,options,[],deep_scores))
                self.results.put((version,digest,block,area,ranked,metadata,None))
            except Exception as error:self.results.put((version,digest,block,area,[],None,type(error).__name__))
        self.executor.submit(work)

    def drain(self):
        while not self.results.empty():
            version,digest,block,area,ranked,metadata,error=self.results.get();self.busy=False
            if self.closed or version!=self.version:continue
            if error:
                if not self.window.library.ai.enabled('neural_enabled'):continue
                self.failure=error;self.last_status='LocalAI активен — нейромодуль недоступен';self.cooldown=time.monotonic()+60
                continue
            from word_scoring import word_key
            ai=self.window.library.ai;kind=self.window.ai_context()['modality']
            metadata=metadata or {}
            for key,options in metadata.get('extra_candidates',()):ai.extra_candidates[key]=options
            while len(ai.extra_candidates)>256:ai.extra_candidates.pop(next(iter(ai.extra_candidates)))
            for word,before,after,options,_,deep_scores in ranked:
                if deep_scores:
                    key=word_key(word,before,after,area,kind)
                    ai.deep_scores.setdefault(key,{}).update(zip(options,deep_scores))
                    while len(ai.deep_scores)>256:ai.deep_scores.pop(next(iter(ai.deep_scores)))
            if 'completion_key' in metadata:
                self.completion_scores[metadata['completion_key']]=dict(zip(metadata['completion_ids'],metadata['completion_scores']))
                while len(self.completion_scores)>64:self.completion_scores.pop(next(iter(self.completion_scores)))
            self.cache[digest]=True
            while len(self.cache)>256:self.cache.popitem(last=False)
            self.last_status=('SAGE: оценены варианты слов ('+str(metadata['sage_tasks'])+')') if metadata.get('sage_tasks') else ('RuBERT: оценены формулировки' if metadata.get('bert_used') else 'Обновлены словарные варианты; SAGE в этом профиле не использовалась')
            # Cache immutable word scores even after a caret move; refresh only the
            # current popup. Write every score BEFORE rebuilding its visible order.
            cursor=self.window.editor.textCursor();same_cursor=metadata.get('cursor_snapshot') in (None,(cursor.position(),cursor.anchor()))
            popup=self.window.completer.popup()
            if same_cursor and popup.isVisible():
                selected=popup.currentIndex().data();preserve=getattr(self.window,'_completion_user_selected',False) or popup.currentIndex().row()>0
                self.window.update_suggestions()
                labels=self.window.completion_model.stringList()
                if preserve and selected in labels:popup.setCurrentIndex(popup.model().index(labels.index(selected),0))
        if hasattr(self.window,'hybrid_indicator'):self.window.hybrid_indicator.setText(self.last_status)
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
        from neural_retrieval import shortlist
        snapshot=shortlist(self.window.library.ai,query,rows);version=self.version;self.busy=True
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
