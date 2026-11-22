"""Exercise the packaged Windows executable with an isolated user database."""
import json
import tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication, QTreeWidgetItemIterator, QListWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QInputMethodEvent


def run(result_path):
    import app as module
    import __main__
    if hasattr(__main__, 'MainWindow'): module = __main__
    from document_io import read_docx
    application = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        module.app_data_dir = lambda: Path(tmp)
        window = module.MainWindow()
        window.show(); application.processEvents()
        iterator = QTreeWidgetItemIterator(window.template_list)
        visible = 0
        while iterator.value():
            visible += iterator.value().data(0, Qt.ItemDataRole.UserRole) is not None
            iterator += 1
        assert visible == 497, visible
        window.show_quick_lines()
        assert window.quick_dialog.findChild(QListWidget).count() >= 20
        text = '- контруы ровные; размер L4-L5 до 3.5 мм;\n\nЗаключение:'
        window.editor.setPlainText(text)
        cursor = window.editor.textCursor(); cursor.select(cursor.SelectionType.Document)
        window.editor.setTextCursor(cursor); window.add_selection_to_quick_lines()
        assert text in window.library.quick_lines()
        window.show_spelling()
        spelling = window.spelling_dialog
        assert [issue.word for issue in spelling.matches] == ['контруы']
        spelling.suggestions.setEditText('контуры'); spelling.replace.click(); spelling.close()
        assert 'контруы' not in window.editor.toPlainText()
        unscaled_html = window.editor.toHtml()
        window.zoom_control.setValue(175)
        assert window.editor.scale_percent == 175
        assert window.editor.toHtml() == unscaled_html
        target = Path(tmp) / 'smoke.docx'; window.current_file = str(target)
        assert window.save_file()
        expected = 'Контуры ровные; размер L4-L5 до 3.5 мм.\n\nЗаключение:'
        assert read_docx(target) == expected
        window.side_tabs.setCurrentWidget(window.reference)
        event = QInputMethodEvent(); event.setCommitString('Проверка ввода')
        QApplication.sendEvent(window.reference.input, event)
        assert window.reference.input.toPlainText() == 'Проверка ввода'
        assert window.editor.toPlainText() == expected
        from yandex_editor import BrowserBridge
        import urllib.request
        window.show_yandex_editor()
        dialog = window.yandex_dialog
        dialog.bridge = BrowserBridge(dialog.source_text)
        candidate = 'Ровные контуры; размер L4-L5 до 3.5 мм.\n\nЗаключение:'
        request = urllib.request.Request(dialog.bridge.origin + dialog.bridge.result_path,
            data=json.dumps({'text': candidate}).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'Origin': dialog.bridge.origin})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=3) as response: assert response.status == 200
        dialog.poll_result()
        assert dialog.result.toPlainText() == candidate
        dialog.apply.click()
        assert window.editor.toPlainText() == candidate
        window.editor.undo()
        assert window.editor.toPlainText() == expected
        dialog.close()
        assert dialog.bridge.closed
        from report_format import format_report
        mra_id = window.library.db.execute("SELECT id FROM templates WHERE source='Google Drive: 1p6-C-2cJcZoFxBoHBaaXKx6H__yXWKcG'").fetchone()[0]
        mra = format_report(window.library.get_template(mra_id)[1])
        assert 'обычной формы' in mra and 'клинико-лабораторными данными' in mra
        assert 'обычной.\nФормы' not in mra
        window.editor.setPlainText(mra)
        fixed_path = Path(tmp) / 'mra-fixed.docx'
        window.export_to_path(fixed_path)
        assert read_docx(fixed_path) == mra
        assert len(window.library.layout_audit) == 497
        for title in ('Колено норма МЕГИ', 'Плечев суст норма МЕГИ', 'М таз простата норма МЕГИ'):
            rows = window.library.db.execute('SELECT id FROM templates WHERE title=?', (title,)).fetchall()
            for key, in rows:
                text = format_report(window.library.get_template(key)[1])
                assert text.splitlines()[0].startswith('На серии') and 'Т1W' in text.splitlines()[0]
                window.editor.setPlainText(text)
                window.export_to_path(fixed_path)
                assert read_docx(fixed_path) == text
        assert sum(row['kind'] == 'base-restored' for row in window.library.layout_audit) == 127
        assert sum(row['needs_source_review'] for row in window.library.layout_audit) == 18
        window.editor.setPlainText('Правый коленный сустав.\nЗаключение: левый коленный сустав. Размер ___ мм.')
        window.show_protocol_check()
        assert len(window.protocol_check_dialog.matches) == 2
        assert len(window.editor.extraSelections()) >= 3
        window.protocol_check_dialog.close()
        window.editor.setPlainText('Контруы ровные.')
        window.live_spelling.reload_words()
        assert window.live_spelling.issues('Контруы ровные.')[0].word == 'Контруы'
        window.favorites.store('Тест','ГМ',window.editor.toHtml())
        assert window.favorites.items.count() == 1
        window.editor.setPlainText('зад цент прот l5-s1 до 4 мм с лок деформ дура мешка')
        window.show_shorthand()
        assert window.shorthand_dialog.apply.isEnabled()
        window.shorthand_dialog.apply_result()
        assert 'с локальной деформацией дурального мешка.' in window.editor.toPlainText()
        window.export_to_path(fixed_path)
        assert read_docx(fixed_path) == window.editor.toPlainText()
        window.editor.undo()
        assert window.editor.toPlainText().startswith('зад цент прот')
        window.editor.setPlainText('Задняя центральная грыжа диска L5-S1 до 4 мм, с локальной деформацией дурального мешка.')
        window.export_to_path(fixed_path)
        window.learn_confirmed_description()
        window.editor.setPlainText('Грыжа диска L4-L5 до 5 мм ')
        cursor=window.editor.textCursor();cursor.movePosition(cursor.MoveOperation.End);window.editor.setTextCursor(cursor)
        window.update_suggestions()
        assert window._adaptive_options
        window.accept_completion(next(iter(window._adaptive_options)))
        assert 'L4-L5 до 5 мм, с локальной деформацией' in window.editor.toPlainText()
        assert 'L5-S1' not in window.editor.toPlainText()
        window.editor.setPlainText('Моя запись.\nСледующий абзац.')
        cursor=window.editor.textCursor();cursor.setPosition(0);window.editor.setTextCursor(cursor)
        window.improve_fragment()
        cursor=window.editor.textCursor();cursor.movePosition(cursor.MoveOperation.End);cursor.insertText(' Продолжаю.');window.editor.setTextCursor(cursor)
        window.shorthand_dialog.result.setPlainText('Улучшенная запись.')
        window.shorthand_dialog.apply_result()
        assert window.editor.toPlainText() == 'Улучшенная запись.\nСледующий абзац. Продолжаю.'
        window.export_to_path(fixed_path)
        assert read_docx(fixed_path) == window.editor.toPlainText()
        window.shorthand_dialog.close()
        from shorthand_patterns import make_pattern,apply_patterns
        pattern=make_pattern('прот L5-S1 до 4 мм','Протрузия L5-S1 до 4 мм.')
        assert apply_patterns('прот L4-L5 до 5 мм',[pattern]) == 'Протрузия L4-L5 до 5 мм.'
        assert window.library.ai.corrections('струткуры','Срединные ',' не смещены','ГМ')[0]=='структуры'
        assert window.library.ai.corrections('смещны','Срединные структуры не ','','ГМ')[0]=='смещены'
        assert not window.library.ai.corrections('L4-L5')
        before=window.library.ai.stats()
        assert window.library.ai.learn_text('Непроверенная формулировка.')==0
        assert before==window.library.ai.stats()
        window.live_spelling.ignore('контруы')
        assert not window.live_spelling.issues('Контруы ровные.')
        window.library.ai.exclude('ошибочно изученная фраза')
        assert 'ошибочно изученная фраза' in window.library.ai.excluded
        assert window.library.backup().exists()
        from model_assets import verify_files
        verify_files()
        from hybrid_backend import NeuralBackend
        neural=NeuralBackend()
        try:
            semantic=neural.semantic('Срединные структуры не смещены.',['Срединные структуры не смещены.','МРТ коленного сустава.'])
            assert semantic['scores'][0]>semantic['scores'][1]
            deep=neural.deep('Контруы ровные.',['Контуры ровные.','Контур ровный.'])
            assert deep['scores'][0]>deep['scores'][1]
        finally:neural.close()
        window.editor.document().setModified(False); window.close()
        Path(result_path).write_text(json.dumps({'protocols': visible, 'docx': 'ok', 'view_scale': 'ok',
            'quick_lines': 'ok', 'spelling': 'ok', 'punctuation': 'ok', 'google_input': 'ok', 'yandex_exchange': 'ok',
            'mra_paragraphs': 'ok', 'layouts_audited': 497, 'methodology': 'ok', 'protocol_check': 'ok', 'live_spelling': 'ok', 'favorites': 'ok', 'shorthand': 'ok', 'adaptive_completion': 'ok', 'fragment_flow': 'ok', 'local_ai': 'ok', 'bundled_rubert': 'ok', 'bundled_sage': 'ok', 'critical_tokens': 'ok', 'explicit_learning': 'ok', 'memory_backup': 'ok',
            'base_sources_restored': 127, 'source_review_required': 18}), encoding='utf-8')
