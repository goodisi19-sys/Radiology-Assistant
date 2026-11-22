import sqlite3,tempfile,unittest,socket
from pathlib import Path
from unittest.mock import patch
from radiology_ai import LocalAI,classify
from protocol_check import consistency_findings,language_findings

CORPUS=[('Срединные структуры не смещены. Контуры ровные. Структуры мозга не смещены.','ГМ'),('Суставные поверхности конгруэнтны. Контуры ровные и четкие.','Суставы')]
def db():
    c=sqlite3.connect(':memory:');c.executescript('CREATE TABLE spelling_words(word TEXT PRIMARY KEY);CREATE TABLE app_settings(key TEXT PRIMARY KEY,value TEXT);');return c

class LocalAITests(unittest.TestCase):
    def setUp(self):self.db=db();self.ai=LocalAI(self.db,CORPUS)
    def tearDown(self):self.db.close()
    def test_prefix_completion_and_partial_typo(self):
        self.assertIn('структуры',self.ai.complete('стру','Срединные '))
        self.assertIn('структуры',self.ai.complete('стрк','Срединные '))
        self.assertFalse(self.ai.complete('не'))
    def test_wrong_keyboard_layout(self):
        self.assertEqual(self.ai.corrections('cnhernehs')[0],'структуры')
        from spell_check import find_typos
        self.assertEqual([x.word for x in find_typos('cnhernehs T2 FLAIR ADC')],['cnhernehs'])
    def test_context_transposition_and_omission(self):
        self.assertEqual(self.ai.corrections('струткуры','Срединные ',' не смещены','ГМ')[0],'структуры')
        self.assertEqual(self.ai.corrections('смещны','Срединные структуры не ','','ГМ')[0],'смещены')
    def test_critical_tokens_never_suggested_for_rewrite(self):
        for word in ('не','нет','без','левый','правый','L4-L5','3.5','30x21x36','МРТ','T2'):
            self.assertEqual(self.ai.corrections(word),(),word)
    def test_only_confirmed_sources_and_disable(self):
        self.assertEqual(self.ai.learn_text('Контуры ровные и четкие.'),0)
        self.assertGreater(self.ai.learn_text('Контуры ровные и четкие.',confirmed=True),0)
        before=self.ai.stats();self.ai.learn_text('Контуры ровные и четкие.',confirmed=True);self.assertEqual(before,self.ai.stats())
        self.db.execute("INSERT INTO app_settings VALUES('self_learning','0')")
        self.ai.confirm_correction('контруы','контуры');self.assertEqual(self.ai.stats()['Исправления'],0)
    def test_new_confirmed_medical_word_is_available_after_restart(self):
        self.ai.confirm_correction('нейротермн','нейротермин')
        restarted=LocalAI(self.db,CORPUS)
        self.assertIn('нейротермин',restarted.corrections('нейротермн'))
        restarted.clear();self.assertNotIn('нейротермин',restarted.words)
    def test_personal_corrections_persist(self):
        self.ai.confirm_correction('контруы','контуры','ГМ')
        self.assertEqual(LocalAI(self.db,CORPUS).confirmed[('контруы','контуры','ГМ')],1)
    def test_no_identity_numbers_or_raw_documents(self):
        self.ai.learn_text('Пациент Иванов Иван Иванович\nДата рождения 01.01.1970\nРазмер 30x21x36 мм\nКонтуры ровные.',confirmed=True)
        words={x[0] for x in self.db.execute('SELECT word FROM ai_words')}
        self.assertFalse({'иванов','иван','иванович','размер'} & words)
        self.assertNotIn('30',' '.join(words))
    def test_exclude_and_clear(self):
        self.ai.learn_text('Контуры ровные и четкие.',confirmed=True)
        self.ai.exclude('ровные');self.assertNotIn('ровные',self.ai.continuations('Контуры '))
        self.db.execute("INSERT INTO spelling_words VALUES('нейротермин')")
        self.ai.clear();self.assertFalse(any(self.ai.stats().values()))
        self.assertEqual(self.db.execute('SELECT word FROM spelling_words').fetchone()[0],'нейротермин')
    def test_offline(self):
        with patch.object(socket,'create_connection',side_effect=AssertionError('network')):
            self.ai.corrections('струткуры','Срединные ')
            self.ai.search('стрктуры',[(1,'Структуры мозга','ГМ')])
    def test_classification_and_fuzzy_search(self):
        for text,area in [('МРТ головного мозга','ГМ'),('КТ брюшной полости','Брюшная полость'),('Поясничный позвоночник','Позвоночник'),('КТ сосудов артерий','Сосуды')]:self.assertEqual(classify(text),area)
        self.assertTrue(self.ai.search('струткуры',[(1,'Структуры мозга','ГМ')]))
    def test_bounded_cache(self):
        for i in range(2100):self.ai.corrections('струткуры',str(i))
        self.assertLessEqual(self.ai.corrections.cache_info().currsize,2048)
    def test_medical_warnings_not_rewrites(self):
        text='Правая почка размером 30 мм.\nЗаключение: правая почка размером 40 мм.'
        self.assertTrue(consistency_findings(text));self.assertIn('30',text)
        self.assertTrue(consistency_findings('Грыжа L4-L5.\nЗаключение: грыжа L5-S1.'))
        self.assertTrue(consistency_findings('Выпот определяется.\nЗаключение: выпот не определяется.'))
        self.assertTrue(language_findings('Контуры контуры ровные'))

class LocalAIApplicationTests(unittest.TestCase):
    def setUp(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        import app
        from PySide6.QtWidgets import QApplication
        self.app=QApplication.instance() or QApplication([])
        self.tmp=tempfile.TemporaryDirectory();self.override=patch.object(app,'app_data_dir',return_value=Path(self.tmp.name));self.override.start()
        self.window=app.MainWindow()
    def tearDown(self):
        self.window.editor.document().setModified(False);self.window.close();self.override.stop();self.tmp.cleanup()
    def test_async_highlight_ignore_and_export(self):
        from PySide6.QtTest import QTest
        from docx import Document
        self.window.editor.setPlainText('Срединные струткуры не смещны.')
        self.window.live_spelling.reload_words()
        for _ in range(200):
            self.app.processEvents();QTest.qWait(20)
            if self.window.editor.document().firstBlock().layout().formats():break
        self.assertTrue(self.window.editor.document().firstBlock().layout().formats())
        self.window.live_spelling.ignore('струткуры')
        self.assertNotIn('струткуры',[x.word for x in self.window.live_spelling.issues(self.window.editor.toPlainText())])
        p=Path(self.tmp.name)/'clean.docx';self.window.export_to_path(p)
        self.assertTrue(all(not r.underline for para in Document(p).paragraphs for r in para.runs))
    def test_no_learning_from_save_or_favorite_and_backup_migration(self):
        self.window.editor.setPlainText('Контуры ровные; структура однородная.')
        self.window.export_to_path(Path(self.tmp.name)/'draft.docx')
        self.window.favorites.store('Личный шаблон','ГМ',self.window.editor.toHtml())
        self.assertFalse(any(self.window.library.ai.stats().values()))
        self.assertEqual(self.window.library.db.execute('SELECT count(*) FROM templates').fetchone()[0],497)
        backup=self.window.library.backup();self.assertTrue(backup.exists())
        self.assertNotEqual(backup,self.window.library.backup())
    def test_dictation_and_replacement_undo(self):
        from PySide6.QtGui import QInputMethodEvent,QTextCursor
        event=QInputMethodEvent();event.setCommitString('Контруы ровные.')
        self.app.sendEvent(self.window.editor,event)
        cursor=self.window.editor.textCursor();cursor.setPosition(0);cursor.setPosition(7,QTextCursor.MoveMode.KeepAnchor)
        self.assertTrue(self.window.live_spelling.replace(cursor,'Контруы','Контуры'))
        self.window.editor.undo();self.assertEqual(self.window.editor.toPlainText(),'Контруы ровные.')
    def test_personal_db_survives_restart(self):
        import app
        self.window.library.ai.confirm_correction('контруы','контуры')
        self.window.live_spelling.accept('нейротерминтест')
        second=app.PhraseLibrary()
        try:
            self.assertEqual(second.ai.stats()['Исправления'],1)
            self.assertTrue(second.db.execute("SELECT 1 FROM spelling_words WHERE word='нейротерминтест'").fetchone())
            self.assertEqual(second.db.execute('SELECT count(*) FROM templates').fetchone()[0],497)
        finally:second.db.close()
    def test_upgrade_creates_backup_and_preserves_favorites(self):
        import app
        self.window.favorites.store('Сохранить','ГМ','<b>Проверенный текст</b>')
        self.window.library.db.execute('DROP TABLE local_ai_metadata');self.window.library.db.commit()
        upgraded=app.PhraseLibrary()
        try:
            self.assertEqual(upgraded.db.execute('SELECT html FROM favorites WHERE title=?',('Сохранить',)).fetchone()[0],'<b>Проверенный текст</b>')
            copies=list((Path(self.tmp.name)/'backups').glob('before-catalog-v2-*.sqlite3'));self.assertTrue(copies)
            snapshot=sqlite3.connect(str(copies[-1]))
            try:self.assertTrue(snapshot.execute("SELECT 1 FROM favorites WHERE title='Сохранить'").fetchone())
            finally:snapshot.close()
        finally:upgraded.db.close()
    def test_typing_does_not_wait_for_dictionary_worker(self):
        import time
        self.window.live_spelling.reload_words()
        self.window.editor.setPlainText(('Контуры ровные; структура однородная.\n')*200)
        start=time.perf_counter()
        for _ in range(50):self.window.editor.insertPlainText('а')
        elapsed=time.perf_counter()-start
        # Generous regression bound: no synchronous full dictionary scan on keystrokes.
        self.assertLess(elapsed,1.0)
        self.assertTrue(self.window.completion_timer.isActive())

    def test_pending_search_stops_before_database_close(self):
        self.window.template_search.setText('гловного мозга')
        self.assertTrue(self.window.search_timer.isActive())
        self.window.editor.document().setModified(False);self.window.close()
        self.assertFalse(self.window.search_timer.isActive())
        self.window.refresh_templates();self.window.refresh_phrases()

    def test_settings_stop_learning_and_clear_with_backup(self):
        from ai_settings import AISettings
        from PySide6.QtWidgets import QMessageBox
        dialog=AISettings(self.window);dialog.change('self_learning',False)
        self.window.learn_confirmed_description()
        self.window.library.ai.confirm_correction('контруы','контуры')
        self.assertFalse(any(self.window.library.ai.stats().values()))
        dialog.change('self_learning',True)
        self.window.library.verify('Проверено','ГМ','Контуры ровные; структура однородная.')
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):dialog.clear()
        self.assertFalse(any(self.window.library.ai.stats().values()))
        self.assertEqual(self.window.library.adaptive.count(),0)
        self.assertTrue(list((Path(self.tmp.name)/'backups').glob('*.sqlite3')))
        dialog.close()
