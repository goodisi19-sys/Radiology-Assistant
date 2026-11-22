"""Local editable rich-text favorites, separate from verified standards."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QInputDialog, QMessageBox

class FavoritesPanel(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.db = window.library.db
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Поиск по избранным шаблонам…')
        layout.addWidget(self.search)
        self.items = QListWidget()
        layout.addWidget(self.items, 1)
        for label, action in [('★ Сохранить текущий протокол', self.save_current), ('Открыть', self.open_current), ('Переименовать', self.rename), ('Удалить из избранного', self.remove)]:
            button = QPushButton(label)
            button.clicked.connect(action)
            layout.addWidget(button)
        self.items.itemDoubleClicked.connect(self.open_current)
        self.search.textChanged.connect(self.refresh)
        self.refresh()

    def refresh(self, *_):
        self.items.clear()
        q = self.search.text().casefold().strip()
        for key, title, category in self.db.execute('SELECT id,title,category FROM favorites ORDER BY category,title'):
            if q not in (title + ' ' + category).casefold(): continue
            item = QListWidgetItem(category + ' / ' + title)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.items.addItem(item)

    def store(self, title, category, html):
        self.db.execute('INSERT INTO favorites(title,category,html) VALUES(?,?,?) ON CONFLICT(title,category) DO UPDATE SET html=excluded.html', (title,category,html))
        self.db.commit()
        self.refresh()

    def save_current(self, *_):
        editor = self.window.editor
        text = editor.toPlainText().strip()
        if not text: return
        title, ok = QInputDialog.getText(self, 'В избранное', 'Название шаблона:', text=text.splitlines()[0][:100])
        if not ok or not title.strip(): return
        title = title.strip()
        category, ok = QInputDialog.getText(self, 'В избранное', 'Анатомическая категория:', text=self.window.library.guess_category(title+' '+text[:300]))
        if not ok: return
        category = category.strip() or 'Общее'
        if self.db.execute('SELECT 1 FROM favorites WHERE title=? AND category=?', (title,category)).fetchone():
            if QMessageBox.question(self, 'Избранное', 'Обновить существующий шаблон? Для отдельного варианта выберите другое название.') != QMessageBox.StandardButton.Yes: return
        self.store(title,category,editor.toHtml())
        self.window.side_tabs.setCurrentWidget(self)
        self.window.statusBar().showMessage('Шаблон сохранён в избранное.', 4000)

    def selected_id(self):
        item = self.items.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def open_current(self, *_):
        key = self.selected_id()
        if key is None or not self.window.confirm_discard(): return
        row = self.db.execute('SELECT html FROM favorites WHERE id=?',(key,)).fetchone()
        if row:
            self.window.editor.setHtml(row[0])
            self.window.current_file = None
            self.window.editor.document().setModified(False)
            self.window.editor.setFocus()

    def rename(self, *_):
        key = self.selected_id()
        if key is None: return
        title, category = self.db.execute('SELECT title,category FROM favorites WHERE id=?',(key,)).fetchone()
        value, ok = QInputDialog.getText(self,'Избранное','Новое название:',text=title)
        if not ok or not value.strip(): return
        value = value.strip()
        if self.db.execute('SELECT 1 FROM favorites WHERE title=? AND category=? AND id!=?',(value,category,key)).fetchone():
            QMessageBox.warning(self,'Избранное','Шаблон с таким названием уже существует.')
            return
        self.db.execute('UPDATE favorites SET title=? WHERE id=?',(value,key))
        self.db.commit(); self.refresh()

    def remove(self, *_):
        key = self.selected_id()
        if key is None: return
        if QMessageBox.question(self,'Избранное','Удалить выбранный шаблон из избранного?') != QMessageBox.StandardButton.Yes: return
        self.db.execute('DELETE FROM favorites WHERE id=?',(key,))
        self.db.commit(); self.refresh()
