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
        window.editor.document().setModified(False); window.close()
        Path(result_path).write_text(json.dumps({'protocols': visible, 'docx': 'ok',
            'quick_lines': 'ok', 'spelling': 'ok', 'punctuation': 'ok', 'google_input': 'ok', 'yandex_exchange': 'ok'}), encoding='utf-8')
