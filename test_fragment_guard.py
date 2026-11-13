import unittest,os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QTextEdit
from PySide6.QtGui import QTextCursor
from fragment_guard import FragmentGuard
from shorthand_patterns import make_pattern,apply_patterns
APP=QApplication.instance() or QApplication([])
class FragmentTests(unittest.TestCase):
 def test_continue_elsewhere(self):
  editor=QTextEdit();editor.setPlainText('Первая строка.\nСледующая.')
  cursor=QTextCursor(editor.document());cursor.setPosition(0);cursor.setPosition(14,QTextCursor.MoveMode.KeepAnchor)
  guard=FragmentGuard(editor.document(),cursor)
  other=QTextCursor(editor.document());other.movePosition(QTextCursor.MoveOperation.End);other.insertText(' Ещё текст.')
  self.assertTrue(guard.valid);self.assertTrue(guard.replace('Новая строка.'));self.assertIn('Следующая. Ещё текст.',editor.toPlainText());guard.close()
 def test_changed_target_blocks(self):
  editor=QTextEdit();editor.setPlainText('Исходник.')
  cursor=QTextCursor(editor.document());cursor.select(QTextCursor.SelectionType.Document)
  guard=FragmentGuard(editor.document(),cursor);cursor.insertText('Изменено.')
  self.assertFalse(guard.valid);self.assertFalse(guard.replace('Нельзя'));guard.close()
 def test_pattern_preserves_new_values(self):
  pattern=make_pattern('прот L5-S1 до 4 мм','Протрузия L5–S1 до 4 мм.')
  self.assertIsNotNone(pattern)
  self.assertEqual(apply_patterns('прот L4-L5 до 5 мм',[pattern]),'Протрузия L4-L5 до 5 мм.')
  self.assertIsNone(make_pattern('ь5-с1 до 4 мм','L5-S1 до 4 мм.'))

 def test_repeat_own_replacement_and_edit_before_target(self):
  editor=QTextEdit();editor.setPlainText('До. Цель. После.')
  cursor=QTextCursor(editor.document());cursor.setPosition(4);cursor.setPosition(9,QTextCursor.MoveMode.KeepAnchor)
  guard=FragmentGuard(editor.document(),cursor)
  before=QTextCursor(editor.document());before.setPosition(0);before.insertText('Вступление. ')
  self.assertTrue(guard.replace('Вариант.'));self.assertTrue(guard.replace('Другой.'))
  self.assertEqual(editor.toPlainText(),'Вступление. До. Другой. После.');guard.close()
 def test_closed_guard_cannot_replace(self):
  editor=QTextEdit();editor.setPlainText('Цель.')
  cursor=QTextCursor(editor.document());cursor.select(QTextCursor.SelectionType.Document)
  guard=FragmentGuard(editor.document(),cursor);guard.close()
  self.assertFalse(guard.replace('Нельзя.'))

 def test_opposite_sign_is_not_generalized(self):
  self.assertIsNone(make_pattern('смещение до -4 мм','Смещение до 4 мм.'))
  self.assertIsNone(make_pattern('смещение до−4 мм','Смещение до 4 мм.'))
