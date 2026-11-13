import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QTreeWidgetItemIterator, QListWidget, QLineEdit, QMessageBox
from PySide6.QtCore import QObject, Signal
import threading
from PySide6.QtGui import QTextCursor, QTextCharFormat, QFont
from docx import Document
import app
from document_io import read_docx

QT = QApplication.instance() or QApplication([])

class FakeChatThread(QObject):
    completed = Signal(str)
    failed = Signal(str)
    finished = Signal()
    def __init__(self, server, model, history, parent):
        super().__init__(parent)
        self.history = history
        self.cancelled = threading.Event()
    def start(self): pass

class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.override = patch.object(app, 'app_data_dir', return_value=Path(self.tmp.name))
        self.override.start()
        self.window = app.MainWindow()
    def tearDown(self):
        self.window.editor.document().setModified(False)
        self.window.close()
        self.override.stop()
        self.tmp.cleanup()
    def test_all_protocols_visible_and_restart(self):
        ids = []
        iterator = QTreeWidgetItemIterator(self.window.template_list)
        while iterator.value():
            value = iterator.value().data(0, app.Qt.ItemDataRole.UserRole)
            if value is not None: ids.append(value)
            iterator += 1
        self.assertEqual(len(ids), 497)
        before = self.window.library.db.execute('SELECT id,content FROM templates ORDER BY id').fetchall()
        self.window.library.db.close()
        self.window.library = app.PhraseLibrary()
        self.assertEqual(before, self.window.library.db.execute('SELECT id,content FROM templates ORDER BY id').fetchall())
        self.assertEqual(self.window.library.db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
    def test_verified_priority_and_upgrade_backup(self):
        lib = self.window.library
        own = 'Контуры личного стандарта ровные и четкие'
        lib.add('Контуры распространенного протокола ровные', 'test', 'ГМ')
        lib.db.execute('UPDATE phrases SET count=100000 WHERE source=?', ('test',))
        lib.verify('Мой стандарт', 'ГМ', own)
        self.assertEqual(lib.suggestions('контуры')[0], own)
        backup = lib.backup()
        self.assertTrue(backup.exists())
        lib.db.close(); self.window.library = app.PhraseLibrary()
        self.assertEqual(self.window.library.suggestions('контуры')[0], own)
        self.assertEqual(self.window.library.db.execute('SELECT COUNT(*) FROM verified_standards').fetchone()[0], 1)
    def test_import_exclusions_and_variants(self):
        root = Path(self.tmp.name)
        for folder in ['ЛДЦ МИБС', 'Шаблоны МРТ-2006', 'ГМ']:
            (root / folder).mkdir()
            (root / folder / 'test.txt').write_text('Описание исследования: очаг до 3.5 мм без отека.', encoding='utf-8')
        self.assertEqual(self.window.library.import_files([str(root)])[1], 1)
        lib = self.window.library
        self.assertTrue(lib.import_full_protocol('Вариант', 'ГМ', 'Описание исследования: очаг до 4.5 мм без отека.', 'test'))
        self.assertFalse(lib.import_full_protocol('Копия', 'ГМ', 'Описание исследования: очаг до 4.5 мм без отека.', 'test'))
    def test_quick_lines_and_search(self):
        self.window.show_quick_lines()
        dialog = self.window.quick_dialog
        listing = dialog.findChild(QListWidget)
        self.assertGreaterEqual(listing.count(), 20)
        search = dialog.findChild(QLineEdit)
        phrase = listing.item(0).text()
        search.setText(phrase.upper())
        self.assertGreater(listing.count(), 0)
        listing.setCurrentRow(0)
        listing.itemDoubleClicked.emit(listing.item(0))
        self.assertTrue(self.window.editor.toPlainText().strip())
    def test_docx_roundtrip_and_formatting(self):
        editor = self.window.editor
        text = 'очаг L4-L5 до 3.5 мм\n\nЗаключение: без динамики'
        editor.setPlainText(text)
        cursor = editor.textCursor(); cursor.setPosition(0); cursor.setPosition(4, QTextCursor.MoveMode.KeepAnchor)
        fmt = QTextCharFormat(); fmt.setFontWeight(QFont.Weight.Bold); cursor.mergeCharFormat(fmt)
        target = Path(self.tmp.name) / 'report.docx'
        self.window.export_to_path(target)
        self.assertEqual(read_docx(target), text)
        doc = Document(target)
        self.assertTrue(doc.paragraphs[0].runs[0].bold)
        self.assertEqual(doc.styles['Normal'].font.size.pt, 12)
        self.assertEqual(editor.toPlainText(), text)
    def test_cancel_save_keeps_document(self):
        self.window.editor.setPlainText('Несохраненный протокол')
        self.window.editor.document().setModified(True)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Save), patch.object(self.window, 'save_file', return_value=False):
            self.window.new_file()
        self.assertEqual(self.window.editor.toPlainText(), 'Несохраненный протокол')
    def test_selected_quick_line_persists_and_deduplicates(self):
        text = 'Личная строка: очаг 3.5 мм, T2 FLAIR.'
        self.window.editor.setPlainText(text)
        cursor = self.window.editor.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        self.window.editor.setTextCursor(cursor)
        count = len(self.window.library.quick_lines())
        self.window.add_selection_to_quick_lines()
        self.window.add_selection_to_quick_lines()
        self.assertEqual(len(self.window.library.quick_lines()), count + 1)
        self.assertEqual(self.window.editor.toPlainText(), text)
        self.window.library.db.close(); self.window.library = app.PhraseLibrary()
        self.assertIn(text, self.window.library.quick_lines('ЛИЧНАЯ'))
        self.window.show_quick_lines()
        self.assertEqual(self.window.quick_listing.item(0).text(), text)

    def test_expert_preview_apply_and_undo(self):
        self.window.editor.setPlainText('Контуры ровные. Размер 3 мм.')
        cursor = self.window.editor.textCursor()
        cursor.setPosition(0); cursor.setPosition(15, QTextCursor.MoveMode.KeepAnchor)
        self.window.editor.setTextCursor(cursor)
        self.window.show_expert()
        dialog = self.window.expert_dialog
        self.assertEqual(dialog.source_text, 'Контуры ровные.')
        dialog.receive_result('Ровные контуры.')
        self.assertEqual(self.window.editor.toPlainText(), 'Контуры ровные. Размер 3 мм.')
        dialog.apply_variant()
        self.assertEqual(self.window.editor.toPlainText(), 'Ровные контуры. Размер 3 мм.')
        self.window.editor.undo()
        self.assertEqual(self.window.editor.toPlainText(), 'Контуры ровные. Размер 3 мм.')
        dialog.close()

    def test_expert_warns_about_values_and_blocks_stale_document(self):
        self.window.editor.setPlainText('Очаг 3 мм.')
        self.window.show_expert()
        dialog = self.window.expert_dialog
        dialog.receive_result('Очаг 4 мм.')
        self.assertFalse(dialog.apply.isEnabled())
        dialog.receive_result('Размер очага 3 мм.')
        self.window.editor.insertPlainText('Изменено.')
        before = self.window.editor.toPlainText()
        dialog.apply_variant()
        self.assertEqual(self.window.editor.toPlainText(), before)
        dialog.close()

    def test_expert_review_can_apply_and_full_scope(self):
        self.window.editor.setPlainText('Очаг 3 мм.\nЗаключение: очаг.')
        cursor = self.window.editor.textCursor()
        cursor.setPosition(0); cursor.setPosition(10, QTextCursor.MoveMode.KeepAnchor)
        self.window.editor.setTextCursor(cursor)
        self.window.show_expert()
        dialog = self.window.expert_dialog
        self.assertFalse(dialog.whole_document.isChecked())
        dialog.whole_document.setChecked(True)
        self.assertEqual(dialog.source_text, self.window.editor.toPlainText())
        proposed = 'Описание: очаг 3 мм.\nЗаключение: очаг 3 мм.'
        dialog.receive_result(proposed)
        # Repeating the size in the conclusion is a legitimate structural rewrite.
        self.assertFalse(dialog.apply.isEnabled())
        dialog.review_confirm.setChecked(True)
        self.assertTrue(dialog.apply.isEnabled())
        dialog.apply_variant()
        self.assertEqual(self.window.editor.toPlainText(), proposed)
        self.window.editor.undo()
        self.assertEqual(self.window.editor.toPlainText(), 'Очаг 3 мм.\nЗаключение: очаг.')
        dialog.close()

    def test_chat_followup_and_editor_independence(self):
        self.window.editor.setPlainText('Исходный протокол.')
        chat = self.window.chat
        with patch('local_chat.ChatThread', FakeChatThread):
            chat.input.setPlainText('Что такое FLAIR?')
            chat.send_message()
            first = chat.thread
            self.assertTrue(chat.is_busy())
            self.assertFalse(chat.new_button.isEnabled())
            first.completed.emit('Последовательность с подавлением сигнала ликвора.')
            first.finished.emit()
            chat.input.setPlainText('А зачем его подавлять?')
            chat.send_message()
            second = chat.thread
            self.assertEqual([item['role'] for item in second.history], ['user', 'assistant', 'user'])
            self.assertIn('подавлением', second.history[1]['content'])
            second.completed.emit('Чтобы лучше видеть изменения рядом с ликвором.')
            second.finished.emit()
        self.assertEqual(len(self.window.library.chat_history(chat.session_id)), 4)
        self.assertEqual(self.window.editor.toPlainText(), 'Исходный протокол.')
        chat.copy_answer()
        self.assertEqual(QT.clipboard().text(), 'Чтобы лучше видеть изменения рядом с ликвором.')

    def test_chat_new_session_and_restart(self):
        chat = self.window.chat
        old = chat.session_id
        self.window.library.save_chat_turn(old, 'Вопрос', 'Ответ')
        chat.new_session()
        self.assertNotEqual(chat.session_id, old)
        self.assertEqual(self.window.library.chat_history(chat.session_id), [])
        self.assertEqual(len(self.window.library.chat_history(old)), 2)
        selected = chat.session_id
        self.window.editor.document().setModified(False)
        self.window.close()
        self.window = app.MainWindow()
        self.assertEqual(self.window.chat.session_id, selected)
        combo = self.window.chat.sessions
        combo.setCurrentIndex(combo.findData(old))
        self.assertIn('Ответ', self.window.chat.transcript.toPlainText())

    def test_chat_stop_and_retry(self):
        chat = self.window.chat
        with patch('local_chat.ChatThread', FakeChatThread):
            chat.input.setPlainText('Мой вопрос')
            chat.send_message()
            worker = chat.thread
            chat.stop_generation()
            self.assertTrue(worker.cancelled.is_set())
            worker.completed.emit('Поздний ответ, который не должен сохраняться')
            worker.finished.emit()
        self.assertEqual(self.window.library.chat_history(chat.session_id), [])
        self.assertEqual(chat.input.toPlainText(), 'Мой вопрос')
        self.assertFalse(chat.is_busy())
        self.assertTrue(chat.send.isEnabled())

    def test_chat_prevents_parallel_ai_and_empty_question(self):
        chat = self.window.chat
        chat.input.clear()
        chat.send_message()
        self.assertFalse(chat.is_busy())
        with patch('local_chat.ChatThread', FakeChatThread):
            chat.input.setPlainText('Вопрос')
            chat.send_message()
            self.window.show_expert()
            self.assertFalse(hasattr(self.window, 'expert_dialog'))
            self.assertIs(self.window.side_tabs.currentWidget(), chat)
            chat.thread.failed.emit('Ошибка движка')
            chat.thread.finished.emit()
        self.assertEqual(chat.input.toPlainText(), 'Вопрос')
        self.assertEqual(self.window.library.chat_history(chat.session_id), [])

    def test_formatting_keeps_paragraphs(self):
        self.window.editor.setPlainText("описание\n\nзаключение")
        self.window.format_all_text()
        self.assertEqual(self.window.editor.toPlainText(), "Описание.\n\nЗаключение.")

    def test_anatomy_and_cyrillic_search(self):
        for folder, expected in [('Позвоночник М/Спинной мозг', 'Позвоночник'), ('Суставы М/Локоть М', 'Суставы'), ('Малый таз М', 'ОМТ')]:
            self.assertEqual(app.PhraseLibrary.guess_category(folder), expected)
        self.window.template_search.setText('НОРМА')
        self.assertGreater(self.window.template_list.topLevelItemCount(), 0)

if __name__ == '__main__': unittest.main()
