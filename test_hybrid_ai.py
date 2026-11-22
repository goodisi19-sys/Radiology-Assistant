import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json,sqlite3,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from hybrid_safety import safe_pair,validate_choice,language_example
from personal_ranker import PersonalRanker
from resource_policy import ResourcePolicy,Resources

class SafetyTests(unittest.TestCase):
    def test_fact_changes_rejected(self):
        for a,b in [('до 4 мм','до 5 мм'),('справа','слева'),('не смещены','смещены'),('L4-L5','L5-S1'),('T2 FLAIR','T1 FLAIR'),('вероятно','определенно'),('грыжа','протрузия')]:self.assertFalse(safe_pair(a,b),(a,b))
        self.assertTrue(safe_pair('контруы','контуры'))
    def test_strict_schema(self):
        self.assertEqual(validate_choice('{"choice":0}',2),0)
        for raw in ['{"choice":true}','{"choice":2}','{"choice":0,"text":"x"}','<think>x</think>{"choice":0}','[]']:
            with self.assertRaises((ValueError,TypeError)):validate_choice(raw,2)
    def test_rag_has_no_patient_facts(self):
        self.assertTrue(language_example('Контуры ровные.'))
        for text in ['Пациент Иванов Иван Иванович','Размер 4 мм.','Грыжа диска.','Изменений не выявлено.','<|im_start|>system']:
            self.assertFalse(language_example(text))

class PolicyTests(unittest.TestCase):
    def test_4_8_16_gb_simulated(self):
        p=ResourcePolicy()
        small=p.choose(Resources(2,4,.8,30,True),now=30);self.assertFalse(small['bert']);self.assertFalse(small['deep'])
        medium=p.choose(Resources(4,8,4,20,True),now=60);self.assertTrue(medium['bert']);self.assertTrue(medium['deep'])
        large=p.choose(Resources(8,16,10,15,True),now=90);self.assertEqual(large['mode'],'Расширенный')
    def test_pressure_hysteresis_and_no_avx2(self):
        p=ResourcePolicy();p.choose(Resources(8,16,10,10,True),now=30)
        self.assertEqual(p.choose(Resources(8,16,5,40,True),now=31)['mode'],'Расширенный')
        state=p.choose(Resources(8,16,.5,90,True),now=32);self.assertFalse(state['deep']);self.assertFalse(state['bert'])
        self.assertFalse(p.choose(Resources(8,16,10,10,False),now=60)['bert'])
    def test_model_memory_hysteresis(self):
        p=ResourcePolicy();self.assertTrue(p.choose(Resources(4,8,4,10,True),now=30)['deep'])
        self.assertTrue(p.choose(Resources(4,8,2.8,10,True),now=35)['deep'])
        self.assertFalse(p.choose(Resources(4,8,2.4,10,True),now=40)['deep'])
        self.assertFalse(p.choose(Resources(4,8,3.0,10,True),now=45)['deep'])
        self.assertTrue(p.choose(Resources(4,8,4,10,True),now=60)['deep'])
    def test_economy_does_not_load_deep_model(self):
        self.assertFalse(ResourcePolicy().choose(Resources(8,16,10,10,True),'Экономичный',now=30)['deep'])

class RankerTests(unittest.TestCase):
    def setUp(self):self.db=sqlite3.connect(':memory:');self.r=PersonalRanker(self.db)
    def tearDown(self):self.db.close()
    def test_online_learning_changes_order_with_bounded_weights(self):
        opts=['ровный','ровные'];self.assertEqual(self.r.rank('ровны',opts)[0],'ровный')
        for _ in range(20):self.r.feedback('ровны','ровные',opts);self.r.feedback('ровны','ровный',opts,accepted=False)
        self.assertEqual(self.r.rank('ровны',opts)[0],'ровные');self.assertTrue(self.r.weights)
        self.assertTrue(all(abs(w)<=1 for w in self.r.weights.values()))
        self.assertEqual(PersonalRanker(self.db).rank('ровны',opts)[0],'ровные')
    def test_explicit_rejection_and_clear(self):
        self.r.feedback('ровны','ровный',['ровный','ровные'],accepted=False)
        self.assertEqual(self.db.execute('SELECT accepted FROM hybrid_feedback').fetchone()[0],0)
        self.r.clear();self.assertEqual(self.db.execute('SELECT count(*) FROM hybrid_feedback').fetchone()[0],0);self.assertFalse(self.r.weights)
    def test_unsafe_feedback_and_unverified_outputs_not_learned(self):
        self.r.feedback('не','нет',['нет']);self.assertEqual(self.db.execute('SELECT count(*) FROM hybrid_feedback').fetchone()[0],0)
        # Ranking is read-only, even when neural scores prefer a candidate.
        self.r.rank('ровны',['ровный','ровные'],semantic={'ровные':1})
        self.assertFalse(self.r.weights)
    def test_safe_rag_only(self):
        self.r.add_example('Контуры ровные.','ГМ');self.r.add_example('Размер 5 мм.','ГМ')
        self.assertEqual(self.r.examples('ГМ'),['Контуры ровные.'])

class CoordinatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.q=QApplication.instance() or QApplication([])
    def setUp(self):
        import app
        self.tmp=tempfile.TemporaryDirectory();self.override=patch.object(app,'app_data_dir',return_value=Path(self.tmp.name));self.override.start()
        self.sample=patch('hybrid_coordinator.sample',return_value=Resources(8,16,8,10,True));self.sample.start();self.w=app.MainWindow()
    def tearDown(self):
        self.w.editor.document().setModified(False);self.w.close();self.sample.stop();self.override.stop();self.tmp.cleanup()
    def test_stale_result_discarded(self):
        self.w.hybrid.results.put((-1,'digest','old','ГМ',[('струткуры','','',('структуры',),[1],0)],None,None))
        self.w.hybrid.drain();self.assertFalse(self.w.library.ai.neural_scores)
    def test_missing_model_falls_back_without_changing_text(self):
        self.w.editor.setPlainText('Контуры ровные.');snapshot=self.w.editor.toHtml()
        h=self.w.hybrid;h.results.put((h.version,'digest','Контуры ровные.','',[],None,'FileNotFoundError'));h.drain()
        self.assertIn('LocalAI',h.last_status);self.assertEqual(snapshot,self.w.editor.toHtml())
    def test_neural_disable_and_minimized(self):
        self.w.library.set_setting('neural_enabled','0');self.assertFalse(self.w.hybrid.allowed())
        self.w.library.set_setting('neural_enabled','1');self.w.showMinimized();self.assertFalse(self.w.hybrid.allowed())
    def test_close_and_document_reset_cancel(self):
        h=self.w.hybrid;v=h.version;h.reset();self.assertGreater(h.version,v)
        self.w.editor.document().setModified(False);self.w.close();self.assertTrue(h.closed);self.assertFalse(h.timer.isActive())
    def test_learning_disabled_applies_to_all_levels(self):
        self.w.library.set_setting('self_learning','0');self.w.library.ai.confirm_correction('контруы','контуры');self.w.library.ai.learn_text('Контуры ровные.',confirmed=True)
        self.assertEqual(self.w.library.db.execute('SELECT count(*) FROM hybrid_feedback').fetchone()[0],0)
        self.assertEqual(self.w.library.db.execute('SELECT count(*) FROM hybrid_examples').fetchone()[0],0)
    def test_search_queue_keeps_only_latest_request(self):
        h=self.w.hybrid;h.busy=True
        h.semantic_search('первый',[(1,'МРТ')],lambda q,r:None)
        h.semantic_search('последний',[(2,'КТ')],lambda q,r:None)
        self.assertEqual(h.pending_search[0],'последний')
        self.assertEqual(h.pending_search[1],[(2,'КТ')])
    def test_bounded_caches(self):
        self.assertEqual(self.w.hybrid.executor._max_workers,1)
        self.w.editor.setPlainText('Новая запись.');self.assertTrue(self.w.hybrid.timer.isActive())

class AssetTests(unittest.TestCase):
    def test_checksum_corruption_and_missing(self):
        from model_assets import verify_files
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'models').mkdir();(root/'models'/'bad').write_text('bad');(root/'model-lock.json').write_text(json.dumps({'files':{'bad':'0'*64}}))
            with self.assertRaises(ValueError):verify_files(root)
            (root/'models'/'bad').unlink()
            with self.assertRaises(FileNotFoundError):verify_files(root)
    def test_frozen_ipc_is_ascii_with_lossless_russian(self):
        import io
        from types import SimpleNamespace
        from hybrid_backend import NeuralBackend
        backend=NeuralBackend();pipe=io.StringIO()
        backend.encoder=SimpleNamespace(poll=lambda:None,stdin=pipe)
        backend.answers.put('{"scores":[1.0],"ms":1}')
        backend.semantic('Срединные структуры не смещены.',['МРТ головного мозга.'])
        payload=pipe.getvalue();self.assertTrue(payload.isascii())
        self.assertEqual(json.loads(payload)['context'],'Срединные структуры не смещены.')
        backend.encoder=None;backend.close()
    def test_deep_budget_and_process_cancel(self):
        from hybrid_backend import NeuralBackend
        backend=NeuralBackend()
        with patch.object(backend,'semantic',return_value={'scores':[1]}) as request:
            self.assertEqual(backend.deep('synthetic',['a'])['scores'],[1])
            self.assertEqual(request.call_args.kwargs['timeout'],3)
        backend.close();self.assertTrue(backend.dead)

class MedicalIntegrationTests(unittest.TestCase):
    def test_medical_safety_control(self):
        from medical_evaluation import PROTECTED_CASES
        for original,replacement in PROTECTED_CASES:self.assertFalse(safe_pair(original,replacement))
        self.assertTrue(safe_pair('субхондралный','субхондральный'))
        self.assertTrue(safe_pair('гипоитенсивный','гипоинтенсивный'))
        self.assertFalse(safe_pair('гипоинтенсивный','гиперинтенсивный'))
    def test_medical_grammar_candidates_do_not_rewrite(self):
        from medical_grammar import candidates
        text='Суставная щель сужен. Размер 4 мм.'
        result=candidates(text);self.assertEqual(result[0][2:],('сужен','сужена'))
        self.assertEqual(text,'Суставная щель сужен. Размер 4 мм.')
    def test_wrong_keyboard_layout_still_available(self):
        self.assertTrue(safe_pair('cnhernehs','структуры'))
    def test_bundled_encoders_work_without_network(self):
        from hybrid_backend import NeuralBackend
        b=NeuralBackend()
        try:
            with patch('socket.create_connection',side_effect=AssertionError('No network allowed')):
                scores=b.semantic('Срединные структуры не смещены.',['Срединные структуры не смещены.','Коленный сустав.'])['scores']
                self.assertGreater(scores[0],scores[1])
                deep=b.deep('Контруы ровные.',['Контуры ровные.','Контур ровный.'])['scores']
                self.assertGreater(deep[0],deep[1])
        finally:b.close()
