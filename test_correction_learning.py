import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from types import SimpleNamespace
from unittest.mock import Mock
from PySide6.QtWidgets import QApplication,QWidget,QTextEdit
from PySide6.QtGui import QTextCursor
from correction_learning import CorrectionLearning


class CorrectionLearningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.qt=QApplication.instance() or QApplication([])
    def setUp(self):
        self.window=QWidget();self.window.editor=QTextEdit(self.window)
        self.ai=Mock();self.ai.enabled.return_value=True
        self.window.library=SimpleNamespace(ai=self.ai);self.now=0
        self.learning=CorrectionLearning(self.window,lambda:self.now)
        self.window.editor.setPlainText('Ошибка. Другой текст.')
        cursor=self.window.editor.textCursor();cursor.setPosition(6,QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText('Верный');self.learning.add('Ошибка','Верный',0)
    def tearDown(self):self.learning.clear();self.window.close()
    def test_surviving_choice_is_committed_once_after_ten_seconds(self):
        self.now=9.9;self.learning.flush();self.ai.confirm_correction.assert_not_called()
        cursor=self.window.editor.textCursor();cursor.movePosition(QTextCursor.MoveOperation.End);cursor.insertText(' Продолжение.')
        self.now=10.1;self.learning.flush();self.learning.flush()
        self.ai.confirm_correction.assert_called_once_with('Ошибка','Верный')
    def test_undo_before_deadline_never_changes_learning(self):
        self.window.editor.undo();self.now=11;self.learning.flush()
        self.assertTrue(self.window.editor.toPlainText().startswith('Ошибка.'))
        self.ai.confirm_correction.assert_not_called();self.assertFalse(self.learning.pending)
    def test_modified_word_and_disabling_learning_discard_pending_choices(self):
        cursor=self.window.editor.textCursor();cursor.setPosition(0);cursor.setPosition(6,QTextCursor.MoveMode.KeepAnchor);cursor.insertText('Иной')
        self.now=11;self.learning.flush();self.ai.confirm_correction.assert_not_called()
        self.learning.add('Иной','Иной',0);self.ai.enabled.return_value=False
        self.learning.flush();self.ai.enabled.return_value=True;self.now=100;self.learning.flush()
        self.ai.confirm_correction.assert_not_called()
