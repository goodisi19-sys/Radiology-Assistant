"""Local module controls and explicit memory management; no remote services."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QCheckBox,QLabel,QComboBox,QPushButton,QListWidget,QListWidgetItem,QMessageBox)

class AISettings(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.setWindowTitle('Локальный ИИ');self.resize(650,540)
        layout=QVBoxLayout(self);layout.addWidget(QLabel('Автономный гибридный модуль; CPU, без внешних API.'))
        for key,label in [('live_spelling','Активная орфография'),('context_corrections','Контекстные исправления'),('grammar_warnings','Грамматические предупреждения'),('smart_completion','Умное автодополнение'),('self_learning','Самообучение по подтверждённым действиям'),('medical_check','Медицинская проверка'),('auto_area','Автоматическое определение анатомической области')]:
            check=QCheckBox(label);check.setChecked(window.library.ai.enabled(key))
            check.toggled.connect(lambda value,k=key:self.change(k,value));layout.addWidget(check)
        neural=QCheckBox('Нейросетевые компоненты (автоматически, в фоне)')
        neural.setChecked(window.library.ai.enabled('neural_enabled'))
        neural.toggled.connect(lambda value:self.change('neural_enabled',value));layout.addWidget(neural)
        phrase_rerank=QCheckBox('Эксперимент: ранжирование продолжений RuBERT (по умолчанию выключено)')
        phrase_rerank.setChecked(window.library.get_setting('bert_phrase_rerank')=='1')
        phrase_rerank.toggled.connect(self.change_phrase_rerank);layout.addWidget(phrase_rerank)
        resource_mode=QComboBox();resource_mode.addItems(['Автоматический','Экономичный','Сбалансированный','Расширенный'])
        resource_mode.setCurrentText(window.library.get_setting('hybrid_mode') or 'Автоматический')
        resource_mode.currentTextChanged.connect(self.change_resource_mode);layout.addWidget(resource_mode)
        self.activity=QLabel();self.activity.setWordWrap(True);layout.addWidget(self.activity)
        self.activity_timer=QTimer(self);self.activity_timer.setInterval(1500);self.activity_timer.timeout.connect(self.refresh_activity);self.activity_timer.start()
        self.refresh_activity()
        self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status);self.items=QListWidget();layout.addWidget(self.items)
        for name,fn in [('Исключить выбранную формулировку',self.exclude),('Резервная копия всей памяти',window.backup_database),('Откатить последнее изменение ранжирования',self.rollback),('Очистить память обучения',self.clear)]:
            button=QPushButton(name);button.clicked.connect(fn);layout.addWidget(button)
        analyze=QPushButton('Оценить текущий абзац сейчас');analyze.clicked.connect(self.analyze_now);layout.addWidget(analyze)
        self.refresh()
    def change_phrase_rerank(self,value):
        self.window.library.set_setting('bert_phrase_rerank','1' if value else '0')
        self.window.hybrid.cache.clear();self.window.hybrid.timer.start()
    def analyze_now(self):
        h=self.window.hybrid;h.cache.clear();h.cooldown=0;h.resources();h.timer.start(0)
        self.refresh_activity()
    def refresh_activity(self):
        hybrid=getattr(self.window,'hybrid',None)
        if not hybrid:return
        state=hybrid.resource_state;resource=state.get('resources',{})
        loaded=getattr(hybrid.backend,'loaded',{})
        self.activity.setText(f"В памяти RuBERT: {'да' if loaded.get('rubert') else 'нет'}, SAGE: {'да' if loaded.get('sage') else 'нет'}. {hybrid.last_status}; выбран: {state.get('requested','—')}; активный профиль: {state.get('mode','—')}; "
            f"RuBERT: {'доступен' if state.get('bert') else 'приостановлен'}; SAGE: {'доступна' if state.get('deep') else 'приостановлена'}; "
            f"{state.get('reason','')} CPU системы: {resource.get('cpu',0):.0f} %; свободно ОЗУ: {resource.get('available_gb',0):.1f} ГиБ. "
            'RuBERT — поиск и формулировки; SAGE — варианты слов в сбалансированном/расширенном профиле. Веса моделей не обучаются автоматически. '+f"Кэш SAGE: попаданий {self.window.library.ai.score_cache_stats['sage_hit']}, без полной оценки {self.window.library.ai.score_cache_stats['sage_miss']}.")
    def change_resource_mode(self,value):
        self.window.library.set_setting('hybrid_mode',value)
        self.change_mode('Расширенный' if value=='Расширенный' else 'Быстрый')
        if hasattr(self.window,'hybrid'):
            self.window.hybrid.reset()
            self.window.library.ai.neural_scores.clear();self.window.library.ai.deep_scores.clear()
            self.window.hybrid.resources()
            self.window.hybrid.timer.start()
        self.refresh_activity()
    def change_mode(self,value):
        self.window.library.set_setting('ai_mode',value);self.window.library.ai.refresh_memory()
    def change(self,key,value):
        self.window.library.set_setting(key,'1' if value else '0')
        if key=='self_learning' and not value and hasattr(self.window,'correction_learning'):self.window.correction_learning.clear()
        if key=='live_spelling':self.window.live_spelling.set_enabled(value)
        if key=='neural_enabled' and hasattr(self.window,'hybrid'):
            self.window.hybrid.reset();self.window.hybrid.resources()
            if value:self.window.hybrid.timer.start()
            if not value:self.window.library.ai.neural_scores.clear();self.window.library.ai.deep_scores.clear()
    def refresh(self):
        ai=self.window.library.ai;self.status.setText('Готов. '+', '.join(f'{k}: {v}' for k,v in ai.stats().items()))
        feedback=ai.db.execute('SELECT coalesce(sum(uses),0),sum(CASE WHEN accepted=0 THEN uses ELSE 0 END) FROM hybrid_feedback').fetchone()
        self.status.setText(self.status.text()+f'; обратная связь: {feedback[0]}, отклонения: {feedback[1] or 0}')
        phrase_count=ai.db.execute('SELECT count(*),coalesce(sum(accepted_count),0),coalesce(sum(rejected_count),0) FROM user_phrase_memory').fetchone()
        self.status.setText(self.status.text()+f'; формулировки: {phrase_count[0]}, приняты: {phrase_count[1]}, отклонены явно: {phrase_count[2]}')
        self.items.clear()
        for original,replacement,area,n in ai.db.execute('SELECT original,replacement,area,uses FROM ai_corrections ORDER BY uses DESC LIMIT 200'):
            item=QListWidgetItem(f'{original} → {replacement} ({n})');item.setData(Qt.ItemDataRole.UserRole,('correction',original,replacement,area));self.items.addItem(item)
        for word,n in ai.db.execute('SELECT word,uses FROM ai_words ORDER BY uses DESC LIMIT 200'):
            item=QListWidgetItem(f'Слово: {word} ({n})');item.setData(Qt.ItemDataRole.UserRole,('word',word));self.items.addItem(item)
        for phrase,n in ai.db.execute('SELECT phrase,sum(uses) FROM ai_ngrams GROUP BY phrase ORDER BY sum(uses) DESC LIMIT 500'):
            self.items.addItem(phrase)
        for phrase, in ai.db.execute("SELECT DISTINCT suffix FROM adaptive_continuations WHERE source='verified' LIMIT 200"):
            if phrase not in ai.excluded:self.items.addItem(phrase)
        for phrase,count in ai.db.execute('SELECT phrase,sum(accepted_count) FROM user_phrase_memory GROUP BY phrase ORDER BY sum(accepted_count) DESC LIMIT 100'):
            item=QListWidgetItem(f'Продолжение ({count}): '+phrase);item.setData(Qt.ItemDataRole.UserRole,('phrase',phrase));self.items.addItem(item)
    def exclude(self):
        item=self.items.currentItem()
        if not item:return
        ai=self.window.library.ai;data=item.data(Qt.ItemDataRole.UserRole)
        if data:
            with ai.db:
                if data[0]=='correction':
                    ai.db.execute('DELETE FROM ai_corrections WHERE original=? AND replacement=? AND area=?',data[1:])
                    ai.db.execute('DELETE FROM hybrid_feedback WHERE original=? AND candidate=?',(data[1],data[2]))
                elif data[0]=='phrase':
                    ai.db.execute('DELETE FROM user_phrase_memory WHERE phrase=?',(data[1],))
                    ai.db.execute('UPDATE phrase_events SET active=0 WHERE phrase=?',(data[1],))
                    ai.exclude(data[1])
                elif data[0]=='word':ai.db.execute('DELETE FROM ai_words WHERE word=?',(data[1],))
            ai.refresh_memory()
        else:ai.exclude(item.text())
        self.refresh()
    def rollback(self):
        row=self.window.library.db.execute('SELECT id FROM rank_versions WHERE active=0 ORDER BY id DESC LIMIT 1').fetchone()
        if row:self.window.phrase_memory.rollback(row[0])
        self.refresh()

    def clear(self):
        if QMessageBox.question(self,'Очистить память','Создать резервную копию и очистить статистику? Стандарты, словарь, избранное и документы сохранятся.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        self.window.library.backup()
        if hasattr(self.window,'correction_learning'):self.window.correction_learning.clear()
        self.window.library.ai.clear();self.window.phrase_memory.clear()
        with self.window.library.db:
            self.window.library.db.execute('DELETE FROM adaptive_continuations')
            self.window.library.db.execute('DELETE FROM adaptive_documents')
        self.window.library.set_setting('restore_verified_memory','0')
        self.refresh()
