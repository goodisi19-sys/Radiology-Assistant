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
    def test_protocol_check_highlighting_navigation_and_stale_text(self):
        text = '😀 Правый коленный сустав.\nЗаключение: левый коленный сустав. Размер ___ мм.'
        self.window.editor.setPlainText(text)
        self.window.show_protocol_check()
        dialog = self.window.protocol_check_dialog
        self.assertEqual(len(dialog.matches), 2)
        self.assertGreaterEqual(len(self.window.editor.extraSelections()), 3)
        dialog.issues.setCurrentRow(0)
        self.assertEqual(self.window.editor.textCursor().selectedText(), 'левый')
        self.assertEqual(self.window.editor.toPlainText(), text)
        self.window.editor.insertPlainText('правый')
        self.assertFalse(dialog.issues.isEnabled())
        self.assertEqual(len(self.window.editor.extraSelections()), 0)
        dialog.scan()
        self.assertEqual(len(dialog.matches), 1)
        dialog.close()
        self.assertEqual(len(self.window.editor.extraSelections()), 0)

    def test_shorthand_current_line_apply_undo_and_personal_mapping(self):
        self.window.editor.setPlainText('зад цент прот l5-s1 до 4 мм с лок деформ дура мешка\nСледующий абзац.')
        cursor=self.window.editor.textCursor();cursor.setPosition(0);self.window.editor.setTextCursor(cursor)
        before=self.window.editor.toPlainText()
        self.window.show_shorthand(); dialog=self.window.shorthand_dialog
        self.assertNotIn('Следующий',dialog.original)
        self.assertTrue(dialog.apply.isEnabled())
        dialog.remember_phrase()
        self.assertIn('зад цент прот',self.window.library.get_setting('shorthand_personal'))
        dialog.apply_result()
        self.assertTrue(self.window.editor.toPlainText().endswith('\nСледующий абзац.'))
        self.assertIn('дурального мешка.',self.window.editor.toPlainText())
        self.window.editor.undo();self.assertEqual(self.window.editor.toPlainText(),before)

    def test_shorthand_unknown_no_send_and_stale_guard(self):
        self.window.editor.setPlainText('зад цент прот ь5-с1 дл 4 мм')
        self.window.show_shorthand(); dialog=self.window.shorthand_dialog
        self.assertFalse(dialog.apply.isEnabled())
        dialog.result.setPlainText('Мой проверенный текст.')
        self.window.editor.setPlainText('Новая редакция.')
        dialog.apply_result(); self.assertEqual(self.window.editor.toPlainText(),'Новая редакция.')
        dialog.close()

    def test_live_spelling_favorites_and_quick_line(self):
        from PySide6.QtWidgets import QMenu
        self.window.editor.setPlainText('Контруы ровные.')
        self.window.live_spelling.reload_words()
        self.assertEqual([x.word for x in self.window.live_spelling.issues('Контруы ровные.')], ['Контруы'])
        cursor=self.window.editor.textCursor(); cursor.setPosition(0); self.window.editor.setTextCursor(cursor)
        menu=QMenu(); self.window.live_spelling.add_menu(menu,cursor)
        self.assertTrue(menu.actions())
        cursor.setPosition(7,QTextCursor.MoveMode.KeepAnchor)
        self.assertTrue(self.window.live_spelling.replace(cursor,'Контруы','Контуры'))
        self.assertEqual(self.window.editor.toPlainText(),'Контуры ровные.')
        self.window.add_selection_to_quick_lines()
        self.assertIn('Контуры ровные.',self.window.library.quick_lines())
        self.window.favorites.store('Тест','ГМ',self.window.editor.toHtml())
        self.assertEqual(self.window.favorites.items.count(),1)
        self.window.favorites.store('Тест','ГМ',self.window.editor.toHtml())
        self.assertEqual(self.window.favorites.items.count(),1)
        self.window.editor.document().setModified(False)
        self.window.favorites.items.setCurrentRow(0); self.window.favorites.open_current()
        self.assertEqual(self.window.editor.toPlainText(),'Контуры ровные.')

    def test_adaptive_saved_docx_tab_apply_and_undo(self):
        from test_adaptive_completion import SAMPLE,QUERY
        self.window.editor.setPlainText(SAMPLE)
        self.window.export_to_path(Path(self.tmp.name)/'learn.docx')
        self.assertEqual(self.window.library.adaptive.count(),0)
        self.window.learn_confirmed_description()
        self.assertGreater(self.window.library.adaptive.count(),0)
        self.window.show()
        self.window.editor.setPlainText('\n'*7+QUERY)
        cursor=self.window.editor.textCursor();cursor.movePosition(QTextCursor.MoveOperation.End);self.window.editor.setTextCursor(cursor)
        self.window.update_suggestions()
        self.assertTrue(self.window._adaptive_options)
        label=next(iter(self.window._adaptive_options))
        index=self.window.completion_model.index(self.window.completion_model.stringList().index(label))
        self.window.completer.popup().setCurrentIndex(index)
        QTest.keyClick(self.window.editor,Qt.Key.Key_Tab)
        text=self.window.editor.toPlainText()
        self.assertIn('L4-L5 до 5 мм, с локальной деформацией',text)
        self.assertNotIn('L5-S1',text)
        self.window.editor.undo();self.assertEqual(self.window.editor.toPlainText(),'\n'*7+QUERY)

    def test_adaptive_enter_does_not_accept_clinical_suggestion(self):
        from test_adaptive_completion import SAMPLE,QUERY
        self.window.library.adaptive.learn(SAMPLE,verified=True)
        self.window.show();self.window.editor.setPlainText(QUERY)
        cursor=self.window.editor.textCursor();cursor.movePosition(QTextCursor.MoveOperation.End);self.window.editor.setTextCursor(cursor)
        self.window.update_suggestions()
        label=next(iter(self.window._adaptive_options))
        self.window.completer.popup().setCurrentIndex(self.window.completion_model.index(self.window.completion_model.stringList().index(label)))
        QTest.keyClick(self.window.editor,Qt.Key.Key_Return)
        self.assertNotIn('деформацией',self.window.editor.toPlainText())
        self.assertEqual(self.window.editor.toPlainText(),QUERY+'\n')

    def test_adaptive_disabled_and_failed_export_do_not_learn(self):
        from test_adaptive_completion import SAMPLE
        self.window.editor.setPlainText(SAMPLE)
        with patch('document_io.write_docx',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.window.export_to_path(Path(self.tmp.name)/'failed.docx')
        self.assertEqual(self.window.library.adaptive.count(),0)
        self.window.library.set_setting('adaptive_enabled','0')
        self.window.export_to_path(Path(self.tmp.name)/'disabled.docx')
        self.assertEqual(self.window.library.adaptive.count(),0)

    def test_adaptive_callbacks_stop_after_window_close(self):
        self.window.editor.setPlainText('Грыжа диска ')
        self.window.editor.document().setModified(False)
        self.window.close()
        self.window.update_suggestions()
        self.window.accept_completion('Любая устаревшая подсказка')
        self.assertFalse(self.window.autosave_timer.isActive())
        self.assertFalse(self.window.completer.popup().isVisible())
        self.assertEqual(self.window.editor.toPlainText(),'Грыжа диска ')

    def test_fragment_result_applies_while_next_paragraph_is_written(self):
        self.window.editor.setPlainText('Моя заметка.\nСледующий абзац.')
        cursor=self.window.editor.textCursor();cursor.setPosition(0);self.window.editor.setTextCursor(cursor)
        cursor=self.window.fragment_target();self.window.editor.setTextCursor(cursor)
        self.window.improve_fragment();dialog=self.window.shorthand_dialog
        cursor=self.window.editor.textCursor();cursor.movePosition(QTextCursor.MoveOperation.End);cursor.insertText(' Продолжаю описание.');self.window.editor.setTextCursor(cursor)
        dialog.result.setPlainText('Отредактированная фраза.')
        dialog.apply_result()
        self.assertEqual(self.window.editor.toPlainText(),'Отредактированная фраза.\nСледующий абзац. Продолжаю описание.')
        self.assertTrue(self.window.editor.textCursor().atEnd())
        self.window.editor.undo()
        self.assertEqual(self.window.editor.toPlainText(),'Моя заметка.\nСледующий абзац. Продолжаю описание.')
        dialog.close()

    def test_confirmed_note_can_be_saved_with_variable_values(self):
        self.window.editor.setPlainText('смещение L5-S1 4 мм')
        self.window.show_shorthand();dialog=self.window.shorthand_dialog
        dialog.result.setPlainText('Смещение на уровне L5-S1 до 4 мм.')
        dialog.variable_example.setChecked(True);dialog.remember_phrase()
        dialog.source.setPlainText('смещение L4-L5 5 мм');dialog.expand_local()
        self.assertEqual(dialog.result.toPlainText(),'Смещение на уровне L4-L5 до 5 мм.')
        self.assertEqual(self.window.editor.toPlainText(),'смещение L5-S1 4 мм')
        dialog.close()

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

    def test_all_497_layouts_are_audited_and_original_rows_unchanged(self):
        self.assertEqual(len(self.window.library.layout_audit), 497)
        before = self.window.library.db.execute('SELECT id,content FROM templates ORDER BY id').fetchall()
        from report_format import format_report
        for template_id, original in before:
            rendered = self.window.library.get_template(template_id)[1]
            formatted = format_report(rendered)
            self.assertEqual(format_report(formatted), formatted, str(template_id))
        self.assertEqual(before, self.window.library.db.execute('SELECT id,content FROM templates ORDER BY id').fetchall())

    def test_screenshot_mra_template_and_docx(self):
        lib = self.window.library
        row = lib.db.execute("SELECT id,content FROM templates WHERE source='Google Drive: 1p6-C-2cJcZoFxBoHBaaXKx6H__yXWKcG'").fetchone()
        self.assertIsNotNone(row)
        template_id, original = row
        self.assertIn('обычной\nформы', original)
        rendered = lib.get_template(template_id)[1]
        self.assertIn('обычной формы', rendered)
        self.assertIn('клинико-лабораторными данными', rendered)
        self.assertIn('предшествующих МР или РКТ исследований', rendered)
        self.window.editor.setPlainText(rendered)
        self.window.format_all_text()
        text = self.window.editor.toPlainText()
        self.assertNotIn('обычной.\nФормы', text)
        self.assertNotIn('четкими.\nРовными', text)
        target = Path(self.tmp.name) / 'mra.docx'
        self.window.export_to_path(target)
        self.assertEqual(read_docx(target), text)
        self.assertFalse(lib.import_full_protocol('Копия правильного шаблона', 'ГМ', rendered, 'manual'))

    def test_layout_cache_does_not_override_personal_edits(self):
        lib = self.window.library
        template_id = lib.db.execute("SELECT id FROM templates WHERE source='Google Drive: 1p6-C-2cJcZoFxBoHBaaXKx6H__yXWKcG'").fetchone()[0]
        own = 'Мой отредактированный текст.\nЗаключение: без изменений.'
        lib.db.execute('UPDATE templates SET content=? WHERE id=?', (own,template_id)); lib.db.commit()
        self.assertEqual(lib.get_template(template_id)[1], own)
        lib.db.close(); self.window.library = app.PhraseLibrary()
        self.assertEqual(self.window.library.get_template(template_id)[1], own)

    def test_original_method_and_negative_findings_restored_for_knee_and_shoulder(self):
        lib = self.window.library
        for title in ('Колено норма МЕГИ', 'Плечев суст норма МЕГИ'):
            rows = lib.db.execute("SELECT id,content FROM templates WHERE title=? AND source='Встроенная библиотека МРТ'", (title,)).fetchall()
            self.assertTrue(rows)
            for key, original in rows:
                full = lib.get_template(key)[1]
                first = full.splitlines()[0]
                self.assertTrue(first.startswith('На серии') and first.endswith(':'))
                self.assertIn('Т1W', first)
                self.assertIn('не изменены', full)
                self.assertGreater(len(full), len(original))
                self.assertFalse(lib.template_needs_source_review(key))
                self.window.editor.setPlainText(full)
                target = Path(self.tmp.name)/'complete-report.docx'
                self.window.export_to_path(target)
                self.assertEqual(read_docx(target), self.window.editor.toPlainText())
                self.assertNotIn('выполненных в.', self.window.editor.toPlainText())

    def test_clinical_header_recovered_for_existing_legacy_template(self):
        lib = self.window.library
        rows = lib.db.execute("SELECT id,content FROM templates WHERE title='М таз простата норма МЕГИ'").fetchall()
        self.assertEqual(len(rows), 2)
        for key, raw in rows:
            self.assertNotIn('На серии', raw)
            restored = lib.get_template(key)[1]
            self.assertTrue(restored.startswith('На серии МР томограмм'))
            self.assertIn('мочевой пузырь наполнен', restored)

    def test_ambiguous_fragments_marked_and_can_cancel_insertion(self):
        lib = self.window.library
        pending = [r for r in lib.layout_audit if r['needs_source_review']]
        self.assertEqual(len(pending), 18)
        iterator = QTreeWidgetItemIterator(self.window.template_list)
        while iterator.value():
            item = iterator.value()
            key = item.data(0, Qt.ItemDataRole.UserRole)
            if key == pending[0]['id']:
                self.assertIn('[проверить исходник]', item.text(0))
                self.window.template_list.setCurrentItem(item)
                self.window.editor.setPlainText('Мой документ.')
                with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No) as prompt:
                    self.window.insert_template()
                prompt.assert_called_once()
                self.assertEqual(self.window.editor.toPlainText(), 'Мой документ.')
                break
            iterator += 1
        else: self.fail('Missing marked source fragment')

    def test_truncated_builtin_autocomplete_hidden_without_deleting_user_data(self):
        lib = self.window.library
        broken = 'Уникальный тестовый фрагмент хрящи не'
        lib.add(broken, 'Встроенный протокол', 'Суставы')
        self.assertNotIn(broken, lib.suggestions('Уникальный'))
        self.assertTrue(lib.db.execute('SELECT 1 FROM phrases WHERE text=?', (broken,)).fetchone())
        lib.verify('Мой проверенный вариант', 'Суставы', broken)
        self.assertEqual(lib.suggestions('Уникальный')[0], broken)

    def test_docx_manual_break_is_not_a_new_paragraph(self):
        from docx import Document
        source = Path(self.tmp.name) / 'soft-break.docx'
        doc = Document(); paragraph = doc.add_paragraph()
        paragraph.add_run('обычной').add_break(); paragraph.add_run('формы; контуры ровные;')
        doc.add_paragraph('Заключение:'); doc.save(source)
        raw = read_docx(source)
        self.assertIn('обычной\u2028формы', raw)
        self.window.editor.setPlainText(raw)
        self.window.format_all_text()
        self.assertEqual(self.window.editor.toPlainText(), 'Обычной формы; контуры ровные.\nЗаключение:')

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
