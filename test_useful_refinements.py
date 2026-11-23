import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from unittest.mock import Mock
from PySide6.QtCore import QUrl
from completion_overlap import trim_right_overlap,insertion_text
from protocol_context import ProtocolContextState,conflicts

class RightContextTests(unittest.TestCase):
    def test_trim_existing_tail_without_touching_it(self):
        for suffix,right,expected in [('уктуры не смещены.',' не смещены.','уктуры'),('не смещены.',' смещены.','не'),('не смещены.','. Другая строка.','не смещены')]:
            with self.subTest(right=right):
                actual=trim_right_overlap(suffix,right)
                self.assertEqual(actual,expected)
                self.assertEqual(insertion_text(actual,right),expected)
    def test_unrelated_or_partial_word_right_context_abstains(self):
        for right in (' 20 мм.',' смещеными.',' не определяются.'):
            self.assertIsNone(trim_right_overlap('не смещены.',right))
    def test_fully_existing_suffix_does_not_insert_again(self):
        self.assertFalse(trim_right_overlap('не смещены.',' не смещены.'))
    def test_unknown_area_does_not_exclude_known_medical_sources(self):
        import tempfile
        from pathlib import Path
        from test_context_retrieval import Library
        from context_retrieval import ContextIndex
        with tempfile.TemporaryDirectory() as tmp:
            lib=Library(Path(tmp)/'user.db')
            lib.db.execute('INSERT INTO templates VALUES(1,?,?,?)',('МРТ','Срединные структуры не смещены.','ГМ'));lib.db.commit()
            index=ContextIndex(lib)
            try:
                self.assertTrue(index.suggest('Срединные стр',' не смещены.','Другие исследования'))
                self.assertFalse(index.suggest('Срединные стр',' не смещены.','ОМТ'))
            finally:index.close();lib.db.close()
    def test_end_of_line_spacing_unchanged(self):
        self.assertEqual(insertion_text('не смещены.',''),'не смещены. ')

class ClinicalRegressionTests(unittest.TestCase):
    def test_two_independently_located_lesions_side_inversion(self):
        text=('Киста верхнего полюса правой почки 10 мм; киста нижнего полюса левой почки 20 мм.\n'
              'Заключение: Киста верхнего полюса левой почки 10 мм; киста нижнего полюса правой почки 20 мм.')
        issues=conflicts(ProtocolContextState().update(text))
        self.assertEqual(len(issues),2)
        self.assertTrue(all('стороны' in i[2] and len(i[3])==2 for i in issues))
        for issue in issues:
            self.assertTrue(all(text[a:b].strip() for a,b in issue[3]))
    def test_two_sides_on_same_level_keep_size_comparison(self):
        text=('Грыжа диска L4-L5 справа 4 мм; грыжа диска L4-L5 слева 6 мм.\n'
              'Заключение: Грыжа диска L4-L5 справа 8 мм; грыжа диска L4-L5 слева 6 мм.')
        issues=conflicts(ProtocolContextState().update(text))
        self.assertEqual(len(issues),1);self.assertIn('размеров',issues[0][2])
    def test_swapped_sizes_on_two_levels(self):
        text=('Грыжа диска L4-L5 4 мм; грыжа диска L5-S1 6 мм.\n'
              'Заключение: Грыжа диска L4-L5 6 мм; грыжа диска L5-S1 4 мм.')
        issues=conflicts(ProtocolContextState().update(text))
        self.assertEqual(len(issues),2);self.assertTrue(all('размеров' in i[2] for i in issues))
    def test_ne_polucheno_is_absence(self):
        text='Признаков кисты правой почки не получено.\nЗаключение: Киста правой почки выявлена.'
        issues=conflicts(ProtocolContextState().update(text));self.assertTrue(issues)
        self.assertIn('отрицания',issues[0][2])
    def test_unrelated_negative_evidence_does_not_negate_cyst(self):
        text='Киста правой почки 10 мм, данных за инвазию не получено.\nЗаключение: Киста правой почки 10 мм.'
        self.assertFalse(conflicts(ProtocolContextState().update(text)))
    def test_differential_is_not_certain_evidence(self):
        text=('Киста правой почки 10 мм, дифференцировать с расширением чашечки.\n'
              'Заключение: Киста правой почки 20 мм.')
        state=ProtocolContextState().update(text)
        self.assertEqual(state.facts[0].polarity,'uncertain');self.assertFalse(conflicts(state))
    def test_ambiguous_multiple_levels_abstains(self):
        text='Грыжи L4-L5 и L5-S1 4 мм и 6 мм.\nЗаключение: Грыжа L4-L5 8 мм.'
        self.assertTrue(ProtocolContextState().update(text).facts[0].ambiguous)
        self.assertFalse(conflicts(ProtocolContextState().update(text)))
    def test_equivalent_measurements_and_unchanged_laterality(self):
        text=('Киста верхнего полюса правой почки 10x20 мм; киста нижнего полюса левой почки 30 мм.\n'
              'Заключение: Киста верхнего полюса правой почки 2x1 см; киста нижнего полюса левой почки 3 см.')
        self.assertFalse(conflicts(ProtocolContextState().update(text)))

class TLSDiagnosticTests(unittest.TestCase):
    def test_bad_certificate_is_rejected_and_query_not_disclosed(self):
        from tls_diagnostics import reject_and_describe
        certificate=Mock();certificate.issuerInfo.return_value=['Corporate CA']
        error=Mock();error.url.return_value=QUrl('https://www.google.com/search?q=PRIVATE_PROTOCOL')
        error.type.return_value=type('Error',(),{'name':'CertificateAuthorityInvalid'})()
        error.certificateChain.return_value=[certificate]
        message=reject_and_describe(error)
        error.rejectCertificate.assert_called_once();error.acceptCertificate.assert_not_called()
        self.assertIn('www.google.com',message);self.assertIn('Corporate CA',message)
        self.assertIn('CertificateAuthorityInvalid',message);self.assertNotIn('PRIVATE_PROTOCOL',message)

class EditorOverlapTests(unittest.TestCase):
    def test_midline_tab_insertion_is_single_undo_and_preserves_right_text(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from PySide6.QtWidgets import QApplication
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt
        import app
        qt=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'app_data_dir',return_value=Path(tmp)):
            w=app.MainWindow();w.show();qt.processEvents()
            try:
                phrase='Срединные структуры не смещены.'
                w.library.add(phrase,'Личный стандарт','ГМ');w.library.db.commit()
                for left,right in [('Срединные стр',' не смещены.'),('Срединные структуры ',' смещены.')]:
                    original='\n'*7+left+right
                    w.editor.setPlainText(original)
                    cursor=w.editor.textCursor();cursor.setPosition(len('\n'*7+left));w.editor.setTextCursor(cursor)
                    w.update_suggestions();label='Личный стандарт: '+phrase
                    self.assertIn(label,w._library_options)
                    row=w.completion_model.stringList().index(label)
                    popup=w.completer.popup();popup.setCurrentIndex(popup.model().index(row,0))
                    QTest.keyClick(w.editor,Qt.Key.Key_Tab)
                    self.assertEqual(w.editor.toPlainText(),'\n'*7+phrase)
                    w.editor.undo();qt.processEvents();self.assertEqual(w.editor.toPlainText(),original)
            finally:
                w.editor.document().setModified(False);w.close()

class StageMetricTests(unittest.TestCase):
    def test_stage_metrics_are_bounded_and_do_not_store_text(self):
        import io,json
        from types import SimpleNamespace
        from hybrid_backend import NeuralBackend
        backend=NeuralBackend();backend.encoder=SimpleNamespace(poll=lambda:None,stdin=io.StringIO())
        for _ in range(140):
            backend.answers.put(json.dumps({'scores':[1],'ms':1,'onnx_ms':.5,'load_ms':.3}))
            backend.semantic('PRIVATE_PROTOCOL',['PRIVATE_CANDIDATE'])
        rows=backend.timing_snapshot()
        self.assertEqual(len(rows),128);self.assertEqual(rows[-1]['onnx_ms'],.5)
        self.assertNotIn('PRIVATE',str(rows));self.assertGreaterEqual(rows[-1]['roundtrip_overhead_ms_including_startup'],0)
        backend.encoder=None;backend.close()
