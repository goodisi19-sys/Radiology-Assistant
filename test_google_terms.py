import json,os,tempfile,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from unittest.mock import patch
from medical_glossary import MedicalGlossary
from google_term_lookup import sanitized_query,search_url,uncertain_terms

class GlossaryTests(unittest.TestCase):
    def test_verified_only_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'med_glossary.json';g=MedicalGlossary(path)
            g.save('субламинарный','Проверенное пояснение термина.','https://www.google.com/search?q=term')
            self.assertFalse(g.verified_context('Субламинарный доступ.'));self.assertFalse(g.verified_words())
            g.save('субламинарный','Проверенное пояснение термина.','https://www.google.com/search?q=term',True)
            self.assertIn('субламинарный',MedicalGlossary(path).verified_words())
            self.assertTrue(MedicalGlossary(path).verified_context('Субламинарный доступ.'))
            g.save('субламинарный','Непроверенный новый ответ','google',False)
            self.assertEqual(g.records['субламинарный']['definition'],'Проверенное пояснение термина.')
    def test_corrupt_glossary_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'med_glossary.json';p.write_text('broken');g=MedicalGlossary(p)
            with self.assertRaises(ValueError):g.save('термин','определение','google')
            self.assertEqual(p.read_text(),'broken')

class QueryTests(unittest.TestCase):
    def test_term_only_and_domain(self):
        from urllib.parse import urlsplit,parse_qs
        url=search_url('Шморля','Позвоночник');p=urlsplit(url)
        self.assertEqual(p.netloc,'www.google.com');self.assertEqual(parse_qs(p.query)['udm'],['50'])
        self.assertNotIn('неизвестная категория',sanitized_query('Шморля','неизвестная категория'))
    def test_obvious_identifiers_and_protocols_rejected(self):
        for value in ['Иванов Иван Иванович','Пациент Иванов','01.02.1990','Карта 123456','mail@example.org','Рост 170 см','https://evil.com','термин\nФИО','<script>']:
            with self.assertRaises(ValueError,msg=value):sanitized_query(value)
    def test_uncertainty_is_conservative(self):
        self.assertEqual(uncertain_terms('Субламинарный доступ.',set()),['Субламинарный'])
        self.assertFalse(uncertain_terms('Пациент Иванов. Субламинарный доступ.',set()))
        self.assertFalse(uncertain_terms('Субламинарный доступ.',{'субламинарный'}))
        self.assertEqual(uncertain_terms('Изменения по классификации Пфиррмана.'),['Пфиррмана'])
    def test_names_matching_medical_prefix_are_not_sent(self):
        for text in ['Субботин Иван Иванович','Субботин И. И.','Субботин','Субботин контуры Иван Иванович']:
            self.assertFalse(uncertain_terms(text),text)
        self.assertEqual(uncertain_terms('Субламинарный доступ.'),['Субламинарный'])
    def test_browser_domain_allowlist(self):
        from google_term_lookup import allowed_url
        self.assertTrue(allowed_url('https://www.google.com/search?q=test&udm=50'))
        for url in ['https://www.google.com.evil.org','https://google.com','http://www.google.com','https://accounts.google.com','https://generativelanguage.googleapis.com','file:///etc/passwd','javascript:alert(1)']:
            self.assertFalse(allowed_url(url),url)

class FakeBrowser:
    def __init__(self):self.calls=[];self.callback=None
    def search(self,url,callback):self.calls.append(url);self.callback=callback
    def cancel(self):self.callback=None
    def close(self):pass

class AutoLookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.q=QApplication.instance() or QApplication([])
    def setUp(self):
        import app
        self.tmp=tempfile.TemporaryDirectory();self.override=patch.object(app,'app_data_dir',return_value=Path(self.tmp.name));self.override.start();self.w=app.MainWindow()
        self.fake=FakeBrowser();self.w.term_lookup.factory=lambda:self.fake;self.w.term_lookup.allow_network=True
    def tearDown(self):
        self.w.editor.document().setModified(False);self.w.close();self.override.stop();self.tmp.cleanup()
    def test_auto_search_cache_then_no_repeat_and_no_implicit_learning(self):
        h=self.w.term_lookup;self.w.editor.setPlainText('Субламинарный доступ.');h.analyze()
        self.assertEqual(len(self.fake.calls),1)
        self.fake.callback('Пояснение термина для справки.','https://www.google.com/search?q=term','')
        self.assertFalse(self.w.glossary.records['субламинарный']['verified'])
        self.assertNotIn('субламинарный',self.w.library.ai.words)
        h.analyze();self.assertEqual(len(self.fake.calls),1)
        self.w.reference.verify_term();self.assertIn('субламинарный',self.w.library.ai.words)
    def test_three_request_budget_and_timeout_fallback(self):
        h=self.w.term_lookup
        for word in ['субламинарный','параменисковый','интракортикальный']:
            h.lookup(word);self.fake.callback('','','нет ответа за 10 секунд')
        self.assertFalse(h.lookup('ретроменисковый'));self.assertEqual(len(self.fake.calls),3)
        self.assertFalse(self.w.glossary.records);self.assertIn('Локальный анализ продолжается',self.w.reference.term_status.text())
    def test_edit_does_not_overwrite_current_review(self):
        h=self.w.term_lookup;h.lookup('субламинарный');callback=self.fake.callback
        self.w.editor.setPlainText('Другая запись.');self.w.reference.definition.setPlainText('Проверяется врачом')
        callback('Новая внешняя справка.','https://www.google.com/search?q=term','')
        self.assertEqual(self.w.reference.definition.toPlainText(),'Проверяется врачом')
        self.assertIn('субламинарный',self.w.glossary.records)
    def test_disabled_and_closed_do_not_search(self):
        self.w.library.set_setting('google_terms_auto','0');self.w.editor.setPlainText('Субламинарный доступ.');self.w.term_lookup.analyze();self.assertFalse(self.fake.calls)
        self.w.term_lookup.close();self.assertFalse(self.w.term_lookup.lookup('субламинарный'))
