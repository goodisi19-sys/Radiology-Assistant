import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from word_scoring import safe_completion,safe_word_correction,word_key,local_window
from hybrid_safety import safe_pair

class WordContractTests(unittest.TestCase):
    def test_explicit_trusted_prefix_completion_is_not_fragment_replacement(self):
        for left,right in [('моз','мозг'),('мен','мениск'),('печ','печень'),('позв','позвонок'),('гры','грыжа'),('кис','киста')]:
            self.assertTrue(safe_completion(left,right,{right}))
            self.assertFalse(safe_pair(left,right))
        self.assertFalse(safe_completion('мен','мениск',set()))
    def test_anatomical_typo_requires_trusted_target(self):
        for left,right in [('мозза','мозга'),('менсик','мениск'),('позвнока','позвонка')]:
            self.assertTrue(safe_word_correction(left,right,{right}))
            self.assertFalse(safe_word_correction(left,right,set()))
    def test_side_signal_numbers_and_negation_remain_blocked(self):
        for left,right in [('левый','правый'),('гипоинтенсивный','гиперинтенсивный'),('не','нет'),('4','5'),('L4-L5','L5-S1'),('киста','опухоль')]:
            self.assertFalse(safe_word_correction(left,right,{right}))
        for left,right in [('пра','правый'),('гип','гипоинтенсивный'),('L4','L4-L5')]:self.assertFalse(safe_completion(left,right,{right}))
    def test_key_preserves_effective_context_and_not_candidate_order(self):
        self.assertEqual(word_key('слово','Заголовок\nДо ',' после\nКонец','ГМ','МРТ'),word_key('слово','До ',' после','ГМ','МРТ'))
        self.assertNotEqual(word_key('слово','До ',' после','ГМ'),word_key('слово','До ',' после','ОМТ'))
        self.assertNotEqual(word_key('слово','До ',' после','ГМ'),word_key('слово','До ','','ГМ'))
        self.assertNotEqual(word_key('слово','До, ','','ГМ'),word_key('слово','До ','','ГМ'))
    def test_window_is_local_and_does_not_rewrite_protected_facts(self):
        left,word,right=local_window('Первая другая фраза. Наблюдается ','форма',' справа L4-L5 4 мм; другая запись')
        self.assertNotIn('Первая',left);self.assertNotIn('другая',right)
        self.assertIn('L4-L5 4 мм',right);self.assertEqual(word,'форма')

class NeuralDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.qt=QApplication.instance() or QApplication([])
    def setUp(self):
        import app
        from resource_policy import Resources
        self.tmp=tempfile.TemporaryDirectory();self.path=patch.object(app,'app_data_dir',return_value=Path(self.tmp.name));self.path.start()
        self.resources=patch('hybrid_coordinator.sample',return_value=Resources(4,8,4,10,True));self.resources.start()
        self.w=app.MainWindow();self.w.show();self.w.live_spelling.timer.stop();self.w.completion_timer.stop()
    def tearDown(self):
        self.w.editor.document().setModified(False);self.w.close();self.resources.stop();self.path.stop();self.tmp.cleanup()
    def test_scores_reach_visible_popup_and_correction_menu_before_tab(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QMenu
        from spell_check import Typo
        from word_scoring import word_key
        w=self.w;h=w.hybrid;ai=w.library.ai
        word='длинноват';choices=('длинноватый','длинноватая')
        text='\n'*7+'МРТ головного мозга.\nПоверхность '+word+'.'
        w.editor.setPlainText(text);cursor=w.editor.textCursor();cursor.setPosition(len(text)-1);w.editor.setTextCursor(cursor)
        block=cursor.block().text();before='Поверхность ';after='.'
        ai.words.update(choices);w.live_spelling.cache[block]=(Typo(word,len(before),len(before)+len(word),9),)
        h.timer.stop()
        with patch.object(ai,'complete',return_value=choices),patch.object(ai,'corrections',return_value=choices),patch.object(w.completion_index,'suggest',return_value=[]),patch.object(h.backend,'deep',return_value={'scores':[-8.,-4.]}) as deep,patch.object(h.backend,'semantic',side_effect=AssertionError('No unconsumed classification or spelling cosine')):
            w.update_suggestions();self.assertEqual(w.completion_model.stringList()[0],choices[0])
            h.analyze()
            for _ in range(100):
                self.qt.processEvents();h.drain()
                if not h.busy:break
                QTest.qWait(20)
            self.assertFalse(h.busy);deep.assert_called_once()
            self.assertEqual(w.completion_model.stringList()[0],choices[1])
            context=w.ai_context();key=word_key(word,before,after,context['area'],context['modality'])
            self.assertIn(key,ai.deep_scores);self.assertGreater(ai.score_cache_stats['sage_hit'],0)
            menu=QMenu(w);point=w.editor.textCursor();point.setPosition(len(text)-3)
            w.live_spelling.ready=True;w.live_spelling.add_menu(menu,point)
            actions=menu.actions()
            correction_action=next(a for a in actions if a.text().startswith('Исправить:'))
            correction=correction_action.menu()
            self.assertEqual(correction.actions()[0].text(),choices[1])
            QTest.keyClick(w.editor,Qt.Key.Key_Tab)
            self.assertTrue(w.editor.toPlainText().endswith('Поверхность '+choices[1]+'.'))
            w.editor.undo();self.assertEqual(w.editor.toPlainText(),text)
    def test_unready_spelling_does_not_cache_empty_analysis(self):
        self.w.editor.setPlainText('Достаточно длинная строка.');self.w.hybrid.timer.stop()
        with patch.object(self.w.hybrid.backend,'semantic') as request:
            self.w.hybrid.analyze();self.assertFalse(self.w.hybrid.cache);request.assert_not_called()
            self.assertTrue(self.w.hybrid.timer.isActive())
    def test_partial_scores_are_neutral_and_caret_move_does_not_delete_valid_word_scores(self):
        from word_scoring import word_key
        from PySide6.QtGui import QTextCursor
        w=self.w;h=w.hybrid;w.editor.setPlainText('МРТ головного мозга.\nНовая строка.')
        area=w.ai_context()['area'];kind=w.ai_context()['modality'];key=word_key('абв','до ',' после',area,kind)
        h.results.put((h.version,'digest','block',area,[('абв','до ',' после',('абва','абвы'),[],[-8.,-4.])],{'cursor_snapshot':(-1,-1),'sage_tasks':1},None))
        h.drain();self.assertIn(key,w.library.ai.deep_scores)
        self.assertEqual(w.library.ai.deep_for(key,('абва','новый')),{});
        self.assertEqual(w.library.ai.deep_for(key,('абва','абвы'))['абвы'],1)

class SageBudgetTests(unittest.TestCase):
    def test_cold_sage_has_separate_budget_but_warm_call_stays_bounded(self):
        import io,json
        from types import SimpleNamespace
        from hybrid_backend import NeuralBackend
        backend=NeuralBackend();backend.encoder=SimpleNamespace(poll=lambda:None,stdin=io.StringIO())
        deadlines=[]
        class Answers:
            def get(self,timeout):
                deadlines.append(timeout);return json.dumps({'scores':[1],'ms':1,'loaded':{'sage':True}})
        backend.answers=Answers()
        backend.deep('Тест',['Один']);backend.deep('Тест',['Один'])
        self.assertEqual(deadlines,[15,3]);backend.encoder=None

class RetrievalContractTests(unittest.TestCase):
    def test_unknown_query_region_does_not_fill_pool_with_other_category(self):
        from neural_retrieval import shortlist
        from types import SimpleNamespace
        # A catch-all category is not evidence that an unrelated record is preferable.
        rows=[(1,'Нервная ткань внутри черепа','ГМ','Описание'),(2,'Несвязанный шаблон','Другие исследования','Описание')]
        pool=shortlist(SimpleNamespace(search=lambda *a,**k:[]),'нервная ткань',rows,limit=1)
        self.assertEqual(pool[0][0],1)
