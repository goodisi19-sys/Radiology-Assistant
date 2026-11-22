import sqlite3,tempfile,unittest,hashlib,time
from pathlib import Path
from context_retrieval import ContextIndex,context_key
from protocol_context import ProtocolContextState,conflicts
from phrase_memory import PhraseMemory
class Library:
 def __init__(self,path):
  self.path=path;self.db=sqlite3.connect(path);self.db.create_function('raw_digest',1,lambda t:hashlib.sha256(t.encode()).hexdigest())
  self.db.executescript('CREATE TABLE templates(id INTEGER PRIMARY KEY,title,content,category);CREATE TABLE template_layouts(template_id,content,original_digest,kind);CREATE TABLE verified_standards(id,content,category);CREATE TABLE phrases(text,category,source);CREATE TABLE hybrid_weights(feature PRIMARY KEY,weight);')
  self.ai=type('AI',(),{'enabled':lambda s,k:True})()
 def backup(self):
  dst=self.path.with_suffix('.bak');conn=sqlite3.connect(dst);self.db.backup(conn);conn.close();return dst
class RetrievalTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.lib=Library(Path(self.tmp.name)/'user.db')
  self.lib.db.execute('INSERT INTO templates VALUES(1,?,?,?)',('МРТ головного мозга','Срединные структуры не смещены. Контуры ровные четкие.','ГМ'));self.lib.db.commit();self.idx=ContextIndex(self.lib)
 def tearDown(self):self.idx.close();self.lib.db.close();self.tmp.cleanup()
 def test_suffix_prefetch_and_no_queries_per_letter(self):
  q='Срединные структуры ';self.assertEqual(self.idx.suggest(q)[0]['suffix'],'не смещены.')
  count=self.idx.query_count
  for tail in ('н','не','не с','не см'):self.idx.suggest(q+tail)
  self.assertLessEqual(self.idx.query_count-count,1)
  self.assertEqual(self.idx.suggest('Срединные стр')[0]['suffix'],'уктуры не смещены.')
 def test_safe_source_and_incremental_removal(self):
  self.lib.db.execute('INSERT INTO templates VALUES(2,?,?,?)',('МРТ','Срединные структуры смещены влево до мм.','ГМ'));self.lib.db.commit();self.idx.sync()
  self.assertFalse(any('мм' in r['suffix'] for r in self.idx.suggest('Срединные структуры ')))
  self.lib.db.execute('DELETE FROM templates');self.lib.db.commit();self.idx.sync();self.assertEqual(self.idx.suggest('Срединные структуры '),[])
 def test_fts_query_injection(self):self.assertIsInstance(self.idx.retrieve('структуры OR "NEAR(*)"'),list)
 def test_restart(self):
  self.idx.close();self.idx=ContextIndex(self.lib);self.assertTrue(self.idx.suggest('Срединные структуры '));self.assertEqual(self.idx.generation,0)
 def test_personal_priority(self):
  self.lib.db.execute('INSERT INTO phrases VALUES(?,?,?)',('Срединные структуры расположены обычно.','ГМ','Личный стандарт'));self.lib.db.commit()
  self.assertTrue(self.idx.suggest('Срединные структуры ')[0]['personal'])
 def test_memory_explicit_undo_persistence(self):
  memory=PhraseMemory(self.lib);event=memory.record('Срединные структуры ','Срединные структуры не смещены.','ГМ','МРТ','template:1')
  self.assertGreater(memory.boost('Срединные структуры ','Срединные структуры не смещены.','ГМ','МРТ'),0)
  memory.undo(event);self.assertEqual(memory.boost('Срединные структуры ','Срединные структуры не смещены.','ГМ','МРТ'),0)
  self.assertTrue(self.lib.path.with_suffix('.bak').exists())
 def test_key_invalidation(self):
  a=context_key('word','текст','справа','ГМ',candidates=['а']);self.assertNotEqual(a,context_key('word','текст','слева','ГМ',candidates=['а']))
class ContextTests(unittest.TestCase):
 def test_units_dimensions_and_ambiguity(self):
  text='Описание: Киста правой почки 10x20 мм.\nЗаключение: Киста правой почки 2x1 см.'
  self.assertFalse(conflicts(ProtocolContextState().update(text)))
  self.assertTrue(conflicts(ProtocolContextState().update(text.replace('2x1','3x1'))))
  self.assertFalse(conflicts(ProtocolContextState().update(text.replace('Киста правой почки 2x1','Возможная киста правой почки 3x1'))))
 def test_incremental_spans_equal_full_recompute(self):
  state=ProtocolContextState();state.update('Киста правой почки 10 мм.\nЗаключение: Киста левой почки 20 мм.')
  self.assertTrue(conflicts(state));text='Методика: МРТ.\n'+state.text;state.update(text)
  self.assertEqual(state.facts,ProtocolContextState().update(text).facts);self.assertEqual(state.changed_blocks,1)
class OptionalToolsTests(unittest.TestCase):
 def test_volume_units(self):
  from document_tools import ellipsoid_ml
  self.assertAlmostEqual(ellipsoid_ml([10,20,30]),ellipsoid_ml([1,2,3],'см'))
  with self.assertRaises(ValueError):ellipsoid_ml([0,2,3])
 def test_privacy_preview_preserves_medical_numbers(self):
  from privacy_review import redact
  preview=redact('ФИО: Иванов Иван Иванович\nДата рождения: 01.02.1970\nКиста правой почки 10x20 мм.')
  self.assertNotIn('Иванов',preview.text);self.assertIn('10x20',preview.text);self.assertEqual(preview.removed,2)
 def test_rank_guard_rejects_excessive_drift(self):
  from rank_guard import validate
  self.assertFalse(validate({},dict(base=1))[0]);self.assertTrue(validate({},dict(base=.01))[0])
 def test_decoder_single_word_alignment_and_protected_facts(self):
  from tools.evaluate_sage_generation import aligned_change
  self.assertIsNotNone(aligned_change('Контруы ровные.','Контуры ровные.'))
  self.assertIsNone(aligned_change('Киста 10 мм.','Киста 20 мм.'))
  self.assertIsNone(aligned_change('Не выявлено.','Выявлено.'))
class FallbackTests(unittest.TestCase):
 def test_without_fts_then_rebuild(self):
  with tempfile.TemporaryDirectory() as tmp:
   lib=Library(Path(tmp)/'user.db');lib.db.execute('INSERT INTO templates VALUES(1,?,?,?)',('МРТ','Срединные структуры не смещены.','ГМ'));lib.db.commit()
   idx=ContextIndex(lib,fts=False);self.assertFalse(idx.fts);self.assertTrue(idx.suggest('Срединные структуры '));idx.close()
   idx=ContextIndex(lib);self.assertTrue(idx.suggest('Срединные структуры '));idx.close();lib.db.close()
 def test_phrase_rejection_persists_and_does_not_delete_sources(self):
  with tempfile.TemporaryDirectory() as tmp:
   lib=Library(Path(tmp)/'user.db');memory=PhraseMemory(lib)
   event=memory.record('Контуры ровные ','Контуры ровные четкие.','ГМ','МРТ','phrase:1',accepted=False)
   self.assertLess(memory.boost('Контуры ровные ','Контуры ровные четкие.','ГМ','МРТ'),0)
   memory.undo(event);self.assertEqual(memory.boost('Контуры ровные ','Контуры ровные четкие.','ГМ','МРТ'),0)
   self.assertEqual(lib.db.execute('SELECT count(*) FROM phrase_events WHERE active=0').fetchone()[0],1);lib.db.close()
class SafetyRegressionTests(unittest.TestCase):
 def test_no_new_diagnosis_from_source_suffix(self):
  from context_retrieval import safe_suffix
  self.assertFalse(safe_suffix(' метастазы не выявлены.','Контуры ровные'))
  self.assertFalse(safe_suffix(' смещены влево до мм.','Срединные структуры'))
 def test_equivalent_th_and_t_levels(self):
  self.assertFalse(conflicts(ProtocolContextState().update('Грыжа Th11-Th12.\nЗаключение: Грыжа T11-T12.')))
 def test_saturated_count_undo_does_not_remove_previous_experience(self):
  with tempfile.TemporaryDirectory() as tmp:
   lib=Library(Path(tmp)/'user.db');memory=PhraseMemory(lib)
   for _ in range(101):event=memory.record('Контуры ровные','Контуры ровные четкие.','ГМ','МРТ','phrase:1')
   memory.undo(event);self.assertEqual(lib.db.execute('SELECT accepted_count FROM user_phrase_memory').fetchone()[0],100);lib.db.close()
class GlossaryProvenanceTests(unittest.TestCase):
 def test_legacy_evidence_never_becomes_verified_on_restart(self):
  from medical_glossary import MedicalGlossary
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'glossary.json';g=MedicalGlossary(path);g.save('термин','Старая статья.','google')
   restored=MedicalGlossary(path);self.assertFalse(restored.records['термин']['verified']);self.assertNotEqual(restored.records['термин'].get('evidence'),'google-ai-container-v2')
   restored.save('термин','Справка AI Mode.','google',evidence='google-ai-container-v2')
   self.assertEqual(MedicalGlossary(path).records['термин']['evidence'],'google-ai-container-v2')
   restored.save('термин','Проверено врачом.','google',verified=True)
   restored.save('термин','Новая статья.','google',evidence='google-ai-container-v2')
   self.assertEqual(restored.records['термин']['definition'],'Проверено врачом.')

class UnicodeContextTests(unittest.TestCase):
 def test_qt_cursor_does_not_cross_following_heading(self):
  text='😀 Описание: Контуры ровные.\nЗаключение: Норма.'
  state=ProtocolContextState().update(text);position=text.index('Заключение')-1
  qt=len(text[:position].encode('utf-16-le'))//2
  self.assertEqual(state.at_qt(qt)['section'],'description')
  self.assertEqual(state.at_qt(len(text.encode('utf-16-le'))//2)['section'],'conclusion')
