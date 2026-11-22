"""Local module controls and explicit memory management; no remote services."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QCheckBox,QLabel,QComboBox,QPushButton,QListWidget,QListWidgetItem,QMessageBox)

class AISettings(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.setWindowTitle('Локальный ИИ');self.resize(650,540)
        layout=QVBoxLayout(self);layout.addWidget(QLabel('Автономный словарный модуль; CPU, без сети и генеративной модели.'))
        for key,label in [('live_spelling','Активная орфография'),('context_corrections','Контекстные исправления'),('grammar_warnings','Грамматические предупреждения'),('smart_completion','Умное автодополнение'),('self_learning','Самообучение по подтверждённым действиям'),('medical_check','Медицинская проверка'),('auto_area','Автоматическое определение анатомической области')]:
            check=QCheckBox(label);check.setChecked(window.library.ai.enabled(key))
            check.toggled.connect(lambda value,k=key:self.change(k,value));layout.addWidget(check)
        mode=QComboBox();mode.addItems(['Быстрый','Расширенный']);mode.setCurrentText(window.library.get_setting('ai_mode') or 'Быстрый')
        mode.currentTextChanged.connect(self.change_mode);layout.addWidget(mode)
        self.status=QLabel();layout.addWidget(self.status);self.items=QListWidget();layout.addWidget(self.items)
        for name,fn in [('Исключить выбранную формулировку',self.exclude),('Резервная копия всей памяти',window.backup_database),('Очистить память обучения',self.clear)]:
            button=QPushButton(name);button.clicked.connect(fn);layout.addWidget(button)
        self.refresh()
    def change_mode(self,value):
        self.window.library.set_setting('ai_mode',value);self.window.library.ai.refresh_memory()
    def change(self,key,value):
        self.window.library.set_setting(key,'1' if value else '0')
        if key=='live_spelling':self.window.live_spelling.set_enabled(value)
    def refresh(self):
        ai=self.window.library.ai;self.status.setText('Готов. '+', '.join(f'{k}: {v}' for k,v in ai.stats().items()))
        self.items.clear()
        for original,replacement,area,n in ai.db.execute('SELECT original,replacement,area,uses FROM ai_corrections ORDER BY uses DESC LIMIT 200'):
            item=QListWidgetItem(f'{original} → {replacement} ({n})');item.setData(Qt.ItemDataRole.UserRole,('correction',original,replacement,area));self.items.addItem(item)
        for word,n in ai.db.execute('SELECT word,uses FROM ai_words ORDER BY uses DESC LIMIT 200'):
            item=QListWidgetItem(f'Слово: {word} ({n})');item.setData(Qt.ItemDataRole.UserRole,('word',word));self.items.addItem(item)
        for phrase,n in ai.db.execute('SELECT phrase,sum(uses) FROM ai_ngrams GROUP BY phrase ORDER BY sum(uses) DESC LIMIT 500'):
            self.items.addItem(phrase)
        for phrase, in ai.db.execute("SELECT DISTINCT suffix FROM adaptive_continuations WHERE source='verified' LIMIT 200"):
            if phrase not in ai.excluded:self.items.addItem(phrase)
    def exclude(self):
        item=self.items.currentItem()
        if not item:return
        ai=self.window.library.ai;data=item.data(Qt.ItemDataRole.UserRole)
        if data:
            with ai.db:
                if data[0]=='correction':ai.db.execute('DELETE FROM ai_corrections WHERE original=? AND replacement=? AND area=?',data[1:])
                elif data[0]=='word':ai.db.execute('DELETE FROM ai_words WHERE word=?',(data[1],))
            ai.refresh_memory()
        else:ai.exclude(item.text())
        self.refresh()
    def clear(self):
        if QMessageBox.question(self,'Очистить память','Создать резервную копию и очистить статистику? Стандарты, словарь, избранное и документы сохранятся.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        self.window.library.backup();self.window.library.ai.clear()
        with self.window.library.db:
            self.window.library.db.execute('DELETE FROM adaptive_continuations')
            self.window.library.db.execute('DELETE FROM adaptive_documents')
        self.window.library.set_setting('restore_verified_memory','0')
        self.refresh()
