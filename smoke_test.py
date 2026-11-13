"""Exercise the packaged executable with an isolated user database."""
import json
import tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication, QTreeWidgetItemIterator, QListWidget
from PySide6.QtCore import Qt


def run(result_path):
    import app as module
    # When frozen, the entry point is __main__; use its actual classes and globals.
    import __main__
    if hasattr(__main__, 'MainWindow'): module = __main__
    from document_io import read_docx
    application = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        module.app_data_dir = lambda: Path(tmp)
        window = module.MainWindow()
        window.show()
        application.processEvents()
        iterator = QTreeWidgetItemIterator(window.template_list)
        visible = 0
        while iterator.value():
            visible += iterator.value().data(0, Qt.ItemDataRole.UserRole) is not None
            iterator += 1
        assert visible == 497, visible
        window.show_quick_lines()
        assert window.quick_dialog.findChild(QListWidget).count() >= 20
        text = 'Протокол МРТ: L4-L5, 3.5 мм.\nЗаключение: без динамики.'
        window.editor.setPlainText(text)
        target = Path(tmp) / 'smoke.docx'
        window.export_to_path(target)
        assert read_docx(target) == text
        cursor = window.editor.textCursor()
        cursor.select(cursor.SelectionType.Document)
        window.editor.setTextCursor(cursor)
        window.add_selection_to_quick_lines()
        assert text in window.library.quick_lines()
        window.show_expert()
        assert window.expert_dialog.source_text == text
        window.expert_dialog.close()
        window.side_tabs.setCurrentWidget(window.chat)
        session = window.chat.session_id
        window.library.save_chat_turn(session, 'Что такое T2?', 'Справочный ответ.')
        window.chat.render()
        assert 'Справочный ответ.' in window.chat.transcript.toPlainText()
        assert window.editor.toPlainText() == text
        window.editor.document().setModified(False)
        window.close()
        Path(result_path).write_text(json.dumps({'protocols': visible, 'docx': 'ok', 'quick_lines': 'ok', 'expert_dialog': 'ok', 'reference_chat': 'ok'}), encoding='utf-8')
