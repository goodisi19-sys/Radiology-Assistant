import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QWheelEvent, QTextCursor
from editor_zoom import ReportEditor
from document_io import write_docx
from docx import Document


class EditorZoomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_scale_preserves_html_export_selection_and_undo(self):
        editor = ReportEditor(); editor.setHtml('<p><b><span style="font-size:14pt">Контуры</span></b> ровные.</p>')
        editor.show(); self.application.processEvents()
        cursor = editor.textCursor(); cursor.setPosition(2); cursor.setPosition(5, QTextCursor.MoveMode.KeepAnchor); editor.setTextCursor(cursor)
        editor.document().setModified(False)
        original = editor.toHtml(); height = editor.cursorRect().height()
        editor.set_scale(200); self.application.processEvents()
        self.assertGreater(editor.cursorRect().height(), height * 1.5)
        self.assertEqual(editor.toHtml(), original)
        self.assertEqual(editor.textCursor().selectedText(), 'нту')
        self.assertFalse(editor.document().isModified())
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'scaled.docx'; write_docx(p, editor.document())
            run = Document(p).paragraphs[0].runs[0]
            self.assertEqual(run.font.size.pt, 14); self.assertTrue(run.bold)
        editor.moveCursor(QTextCursor.MoveOperation.End); editor.insertPlainText(' Тест')
        editor.set_scale(150); editor.undo()
        self.assertEqual(editor.toPlainText(), 'Контуры ровные.')
        editor.close()

    def test_ctrl_wheel_and_limits(self):
        editor = ReportEditor()
        event = QWheelEvent(QPointF(10,10), QPointF(10,10), QPoint(), QPoint(0,120), Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier, Qt.ScrollPhase.NoScrollPhase, False)
        self.application.sendEvent(editor.viewport(), event)
        self.assertEqual(editor.scale_percent, 125)
        editor.set_scale(500); self.assertEqual(editor.scale_percent, 250)
        editor.set_scale(1); self.assertEqual(editor.scale_percent, 75)
        editor.close()

    def test_setting_survives_restart_and_new_document(self):
        import app
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'app_data_dir', return_value=Path(tmp)):
            first = app.MainWindow(); first.zoom_control.setValue(175)
            first.editor.setPlainText('Тест.'); first.editor.document().setModified(False)
            first.new_file(); self.assertEqual(first.editor.scale_percent, 175)
            first.editor.document().setModified(False); first.close()
            second = app.MainWindow()
            self.assertEqual(second.zoom_control.value(), 175)
            self.assertEqual(second.editor.scale_percent, 175)
            second.editor.document().setModified(False); second.close()
