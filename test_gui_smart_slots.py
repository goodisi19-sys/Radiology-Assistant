"""Actual Qt editing flow for saved quick lines and required patient-specific slots."""
import os,tempfile,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QTextCursor
import app

class QuickSlotUITests(unittest.TestCase):
 def test_tab_accepts_quick_line_and_moves_between_slots(self):
  qt=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as tmp,patch.object(app,'app_data_dir',return_value=Path(tmp)):
   window=app.MainWindow();window.show();qt.processEvents()
   try:
    source='На уровне L4-L5 определяется грыжа справа размерами 12x14 мм.'
    self.assertTrue(window.library.add_quick_line(source,'Позвоночник'))
    initial='\n'*7+'На уровне '
    window.editor.setPlainText(initial)
    cursor=window.editor.textCursor();cursor.movePosition(QTextCursor.MoveOperation.End)
    window.editor.setTextCursor(cursor)
    window.update_suggestions();qt.processEvents()
    label=next((x for x in window._library_options if x.startswith('Моя быстрая строка: ')),None)
    self.assertIsNotNone(label)
    popup=window.completer.popup()
    row=window.completion_model.stringList().index(label)
    popup.setCurrentIndex(popup.model().index(row,0))
    QTest.keyClick(window.editor,Qt.Key.Key_Tab);qt.processEvents()
    text=window.editor.toPlainText()
    self.assertIn('[уровень]',text)
    self.assertIn('[находка]',text)
    self.assertIn('[сторона]',text)
    self.assertIn('[размер]',text)
    self.assertNotIn('12x14 мм',text)
    self.assertEqual(window.editor.textCursor().selectedText(),'[уровень]')
    QTest.keyClicks(window.editor,'L3-L4');qt.processEvents()
    window.completer.popup().hide()
    QTest.keyClick(window.editor,Qt.Key.Key_Tab);qt.processEvents()
    self.assertEqual(window.editor.textCursor().selectedText(),'[находка]')
   finally:
    window.editor.document().setModified(False);window.close()
