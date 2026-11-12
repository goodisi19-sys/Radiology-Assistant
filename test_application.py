import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QTreeWidgetItemIterator, QListWidget, QLineEdit, QMessageBox
from PySide6.QtGui import QTextCursor, QTextCharFormat, QFont
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
