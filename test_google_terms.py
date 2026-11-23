import os,json,tempfile,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QUrlQuery,QUrl
from medical_glossary import MedicalGlossary
from google_dispatch import google_url,open_review

class GlossaryTests(unittest.TestCase):
    def test_verified_only_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'med_glossary.json';g=MedicalGlossary(path)
            g.save('субламинарный','Пояснение термина.','Личный словарь')
            self.assertFalse(g.verified_context('Субламинарный доступ.'))
            g.save('субламинарный','Проверенное пояснение.','Личный словарь',True)
            g.save('субламинарный','Непроверенный ответ','Google',False)
            restored=MedicalGlossary(path)
            self.assertIn('субламинарный',restored.verified_words())
            self.assertEqual(restored.records['субламинарный']['definition'],'Проверенное пояснение.')
    def test_corrupt_glossary_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'med_glossary.json';p.write_text('broken');g=MedicalGlossary(p)
            with self.assertRaises(ValueError):g.save('термин','определение','local')
            self.assertEqual(p.read_text(),'broken')

class BrowserDispatchTests(unittest.TestCase):
    def test_short_unicode_protocol_is_preserved_in_query(self):
        calls=[];copies=[];prompt='Проверь:\nКонтруы ровные; L4-L5, 4 мм, не выявлено.\nТ1+C; CD4+; A&B; 100%.'
        result=open_review(prompt,lambda url:calls.append(url) or True,copies.append)
        self.assertTrue(result.opened);self.assertFalse(result.copied);self.assertFalse(copies)
        self.assertEqual(calls[0].host(),'www.google.com')
        self.assertEqual(QUrlQuery(calls[0]).queryItemValue('q',QUrl.ComponentFormattingOption.FullyDecoded),prompt)
        self.assertEqual(QUrlQuery(calls[0]).queryItemValue('udm'),'50')
        from urllib.parse import urlsplit,parse_qs
        self.assertEqual(parse_qs(urlsplit(bytes(calls[0].toEncoded()).decode()).query)['q'],[prompt])
    def test_long_protocol_copied_whole_never_put_in_url(self):
        calls=[];copies=[];prompt='МРТ: протокол с размерами 30x21x36 мм.\n'*500
        result=open_review(prompt,lambda url:calls.append(url) or True,copies.append)
        self.assertTrue(result.opened and result.copied);self.assertEqual(copies,[prompt])
        self.assertFalse(QUrlQuery(calls[0]).hasQueryItem('q'))
        self.assertNotIn('30x21',calls[0].toString())
    def test_failed_browser_and_empty_query_are_reported(self):
        result=open_review('Короткий вопрос',lambda url:False,lambda text:self.fail('Unexpected copy'))
        self.assertFalse(result.opened);self.assertIn('Не удалось',result.message)
        result=open_review(' ',lambda url:self.fail('Unexpected open'))
        self.assertFalse(result.opened)

class ManualBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.q=QApplication.instance() or QApplication([])
    def setUp(self):
        import app
        self.tmp=tempfile.TemporaryDirectory();self.override=patch.object(app,'app_data_dir',return_value=Path(self.tmp.name));self.override.start();self.w=app.MainWindow()
    def tearDown(self):
        self.w.editor.document().setModified(False);self.w.close();self.override.stop();self.tmp.cleanup()
    def test_selection_is_previewed_and_editor_is_unchanged(self):
        from PySide6.QtGui import QTextCursor
        text='Частная запись.\nКонтруы ровные.';self.w.editor.setPlainText(text)
        cursor=self.w.editor.textCursor();cursor.setPosition(text.index('Контруы'));cursor.movePosition(QTextCursor.MoveOperation.End,QTextCursor.MoveMode.KeepAnchor)
        self.w.editor.setTextCursor(cursor)
        with patch('privacy_review.approve_preview',return_value='Одобренный запрос') as preview,patch('google_dispatch.open_review') as dispatch:
            dispatch.return_value.message='Открыто';self.w.reference.review_protocol(cursor)
        self.assertIn('Контруы ровные',preview.call_args.args[1]);self.assertNotIn('Частная запись',preview.call_args.args[1])
        dispatch.assert_called_once_with('Одобренный запрос');self.assertEqual(self.w.editor.toPlainText(),text)
    def test_cancel_does_not_open_browser_or_change_clipboard(self):
        self.w.editor.setPlainText('Контруы ровные.')
        with patch('privacy_review.approve_preview',return_value=None),patch('google_dispatch.open_review') as dispatch:
            self.w.reference.review_protocol();dispatch.assert_not_called()
    def test_typing_never_creates_embedded_browser_or_network_lookup(self):
        self.assertFalse(hasattr(self.w,'term_lookup'))
        self.w.editor.setPlainText('Субламинарный доступ.');self.q.processEvents()
        import sys
        self.assertNotIn('google_browser',sys.modules)
    def test_reviewed_glossary_remains_available_without_google(self):
        r=self.w.reference;r.term.setText('субламинарный');r.definition.setPlainText('Определение подтверждено врачом.');r.verify_term()
        self.assertIn('субламинарный',self.w.glossary.verified_words())
        r.definition.clear();r.load_term();self.assertEqual(r.definition.toPlainText(),'Определение подтверждено врачом.')
