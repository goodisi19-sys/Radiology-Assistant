import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QTreeWidgetItemIterator, QListWidget, QLineEdit, QMessageBox
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt, QUrlQuery
from PySide6.QtGui import QInputMethodEvent, QTextCursor, QTextCharFormat, QFont
from docx import Document
import app
from document_io import read_docx

QT = QApplication.instance() or QApplication([])



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












    def test_google_opens_only_the_question(self):
        chat = self.window.reference
        self.window.editor.setPlainText('Private report must stay local')
        chat.input.setPlainText('Классификация Stoller?')
        with patch('PySide6.QtGui.QDesktopServices.openUrl', return_value=True) as open_url:
            chat.search_google()
        url = open_url.call_args.args[0]
        self.assertEqual(url.host(), 'www.google.com')
        self.assertEqual(QUrlQuery(url).queryItemValue('q'), 'Классификация Stoller?')
        self.assertNotIn('Private', url.toString())

    def test_google_field_accepts_russian_input(self):
        self.window.show(); self.window.side_tabs.setCurrentWidget(self.window.reference)
        field = self.window.reference.input
        QTest.mouseClick(field.viewport(), Qt.MouseButton.LeftButton)
        QTest.keyClicks(field, 'MRI ')
        event = QInputMethodEvent(); event.setCommitString('вопрос')
        QApplication.sendEvent(field, event)
        self.assertEqual(field.toPlainText(), 'MRI вопрос')
        self.assertFalse(field.isReadOnly())

    def test_spelling_is_manual_and_undoable(self):
        self.window.editor.setPlainText('Контруы ровные.')
        self.window.show_spelling()
        dialog = self.window.spelling_dialog
        self.assertEqual(self.window.editor.toPlainText(), 'Контруы ровные.')
        self.assertEqual(dialog.matches[0].word, 'Контруы')
        dialog.suggestions.setEditText('Контуры')
        QTest.mouseClick(dialog.replace, Qt.MouseButton.LeftButton)
        self.assertEqual(self.window.editor.toPlainText(), 'Контуры ровные.')
        self.window.editor.undo()
        self.assertEqual(self.window.editor.toPlainText(), 'Контруы ровные.')

    def test_personal_spelling_dictionary_persists(self):
        self.window.editor.setPlainText('Нейротерминтест.')
        self.window.show_spelling()
        dialog = self.window.spelling_dialog
        self.assertTrue(dialog.matches)
        dialog.add_word()
        self.assertFalse(dialog.matches)
        self.window.editor.document().setModified(False); self.window.close()
        self.window = app.MainWindow()
        self.window.editor.setPlainText('Нейротерминтест.')
        self.window.show_spelling()
        self.assertFalse(self.window.spelling_dialog.matches)

    def test_spelling_refuses_stale_replacement(self):
        self.window.editor.setPlainText('Контруы ровные.')
        self.window.show_spelling()
        dialog = self.window.spelling_dialog
        dialog.suggestions.setEditText('Контуры')
        self.window.editor.setPlainText('Другой текст.')
        dialog.replace_word()
        self.assertEqual(self.window.editor.toPlainText(), 'Другой текст.')

    def test_saved_docx_has_semicolons_and_no_line_dashes(self):
        source = '- контуры ровные; размеры не увеличены;\n- очаг L4-L5 до 3.5 мм;'
        self.window.editor.setPlainText(source)
        target = Path(self.tmp.name) / 'saved.docx'
        self.window.current_file = str(target)
        self.assertTrue(self.window.save_file())
        self.assertEqual(read_docx(target), 'Контуры ровные; размеры не увеличены.\nОчаг L4-L5 до 3.5 мм.')

    def test_upgrade_retains_previous_saved_data(self):
        db = self.window.library.db
        db.execute('CREATE TABLE IF NOT EXISTS ai_chat_sessions(id INTEGER PRIMARY KEY, title TEXT)')
        db.execute("INSERT INTO ai_chat_sessions(id,title) VALUES(1,'Сохранённая история')")
        self.window.library.set_setting('expert_model', 'previous-model.gguf')
        self.window.editor.document().setModified(False); self.window.close()
        self.window = app.MainWindow()
        self.assertEqual(self.window.library.db.execute('SELECT title FROM ai_chat_sessions WHERE id=1').fetchone()[0], 'Сохранённая история')
        self.assertEqual(self.window.library.get_setting('expert_model'), 'previous-model.gguf')
        self.assertFalse(hasattr(self.window, 'chat'))

    def test_yandex_result_preview_apply_and_undo(self):
        from yandex_editor import BrowserBridge
        source = 'Контуры ровные.\nРазмеры сохранены.'
        self.window.editor.setPlainText(source)
        cursor = self.window.editor.textCursor()
        cursor.setPosition(0); cursor.setPosition(15, QTextCursor.MoveMode.KeepAnchor)
        self.window.editor.setTextCursor(cursor)
        self.window.show_yandex_editor()
        dialog = self.window.yandex_dialog
        dialog.bridge = BrowserBridge(dialog.source_text)
        dialog.bridge.inbox.put('Ровные контуры.')
        dialog.poll_result()
        self.assertEqual(self.window.editor.toPlainText(), source)
        dialog.apply_result()
        self.assertEqual(self.window.editor.toPlainText(), 'Ровные контуры.\nРазмеры сохранены.')
        self.window.editor.undo()
        self.assertEqual(self.window.editor.toPlainText(), source)
        dialog.close()
        self.assertTrue(dialog.bridge.closed)

    def test_yandex_rejects_same_and_stale_result(self):
        self.window.editor.setPlainText('Контуры ровные.')
        self.window.show_yandex_editor()
        dialog = self.window.yandex_dialog
        dialog.result.setPlainText('Контуры ровные.')
        self.assertFalse(dialog.apply.isEnabled())
        dialog.result.setPlainText('Ровные контуры.')
        self.window.editor.setPlainText('Другой документ.')
        dialog.apply_result()
        self.assertEqual(self.window.editor.toPlainText(), 'Другой документ.')
        dialog.close()

    def test_yandex_launch_passes_only_local_url(self):
        target = Path(self.tmp.name) / 'browser.exe'; target.touch()
        self.window.editor.setPlainText('Private text stays out of URL')
        self.window.show_yandex_editor()
        dialog = self.window.yandex_dialog
        dialog.browser.setText(str(target))
        with patch('yandex_editor.subprocess.Popen') as launch:
            dialog.open_browser()
        args = launch.call_args.args[0]
        self.assertEqual(args[0], str(target.resolve()))
        self.assertTrue(args[1].startswith('http://127.0.0.1:'))
        self.assertNotIn('Private', args[1])
        dialog.close()

    def test_escape_closes_yandex_exchange(self):
        from yandex_editor import BrowserBridge
        self.window.editor.setPlainText('Текст.')
        self.window.show_yandex_editor()
        dialog = self.window.yandex_dialog
        dialog.bridge = BrowserBridge(dialog.source_text)
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        self.assertTrue(dialog.bridge.closed)
        self.assertFalse(dialog.timer.isActive())

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
