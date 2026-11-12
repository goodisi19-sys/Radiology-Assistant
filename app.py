from __future__ import annotations
import os, sys, re, sqlite3, zipfile, json, base64, brotli
from pathlib import Path
from typing import Iterable
from PySide6.QtCore import Qt, QStringListModel, QStandardPaths
from PySide6.QtGui import QAction, QFont, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QPlainTextEdit, QTextEdit, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QFileDialog, QMessageBox, QToolBar, QFontComboBox, QSpinBox,
    QCompleter, QInputDialog, QStatusBar, QTabWidget)

APP_NAME = "Radiology Assistant"

def app_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        p = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)) / "RadiologyAssistant"
    else:
        p = Path(__file__).resolve().parent / "user_data"
    p.mkdir(parents=True, exist_ok=True)
    return p

def bundled_data_path(name: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / name

def database_path() -> Path:
    return app_data_dir() / "radiology_library.sqlite3"

class PhraseLibrary:
    def __init__(self):
        self.path = database_path()
        self.db = sqlite3.connect(str(self.path))
        self.db.execute("""CREATE TABLE IF NOT EXISTS phrases(
            id INTEGER PRIMARY KEY, text TEXT UNIQUE NOT NULL, count INTEGER DEFAULT 1,
            source TEXT DEFAULT '', category TEXT DEFAULT 'Общее')""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS templates(
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL,
            content TEXT NOT NULL, source TEXT DEFAULT '')""")
        self.db.commit()
        self.load_bundled_templates()

    def load_bundled_templates(self):
        count = self.db.execute("SELECT COUNT(*) FROM templates").fetchone()[0]
        if count:
            return
        source = bundled_data_path("protocols.json.br.b64")
        if not source.exists():
            return
        try:
            packed = base64.b64decode(source.read_text(encoding="ascii"))
            data = json.loads(brotli.decompress(packed).decode("utf-8"))
            for title, category, content in data:
                self.db.execute("INSERT INTO templates(title,category,content,source) VALUES(?,?,?,?)",
                                (title, category, content, "Встроенная библиотека МРТ"))
                for line in content.splitlines():
                    phrase = re.sub(r"\s+", " ", line).strip(" •-—\t\r\n")
                    if len(phrase) >= 25 and len(phrase) <= 900:
                        self.db.execute("""INSERT INTO phrases(text,count,source,category) VALUES(?,1,?,?)
                            ON CONFLICT(text) DO UPDATE SET count=count+1""",
                            (phrase, "Встроенный протокол", category))
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            raise RuntimeError("Не удалось загрузить встроенную библиотеку протоколов: " + str(exc))

    def search(self, query: str = "", category: str = ""):
        sql = "SELECT text, count, category FROM phrases WHERE 1=1"
        args = []
        if query:
            sql += " AND text LIKE ?"
            args.append("%" + query + "%")
        if category and category != "Все категории":
            sql += " AND category = ?"
            args.append(category)
        sql += " ORDER BY count DESC, text COLLATE NOCASE LIMIT 500"
        return self.db.execute(sql, args).fetchall()

    def search_templates(self, query: str = ""):
        return self.db.execute("""SELECT id,title,category FROM templates
            WHERE title LIKE ? OR content LIKE ? ORDER BY category,title LIMIT 500""",
            ("%" + query + "%", "%" + query + "%")).fetchall()

    def get_template(self, template_id: int):
        return self.db.execute("SELECT title,content FROM templates WHERE id=?", (template_id,)).fetchone()

    def suggestions(self, prefix: str, limit: int = 12):
        if len(prefix.strip()) < 2:
            return []
        return [r[0] for r in self.db.execute(
            "SELECT text FROM phrases WHERE text LIKE ? ORDER BY count DESC LIMIT ?",
            (prefix.strip() + "%", limit)).fetchall()]

    def add(self, text: str, source: str, category: str):
        text = re.sub(r"\s+", " ", text).strip(" •-—\t\r\n")
        if len(text) < 18 or len(text) > 900:
            return False
        self.db.execute("""INSERT INTO phrases(text,count,source,category) VALUES(?,1,?,?)
            ON CONFLICT(text) DO UPDATE SET count=count+1""", (text, source, category or "Общее"))
        return True

    def import_files(self, paths: Iterable[str]):
        total = 0
        for raw in paths:
            p = Path(raw)
            candidates = []
            if p.is_dir():
                candidates = [x for x in p.rglob("*") if x.suffix.lower() in (".docx", ".txt")]
            elif p.suffix.lower() == ".zip":
                try:
                    with zipfile.ZipFile(p) as z:
                        for name in z.namelist():
                            if name.lower().endswith(".docx"):
                                try:
                                    from docx import Document
                                    import io
                                    doc = Document(io.BytesIO(z.read(name)))
                                    candidates.append((name, "\n".join(x.text for x in doc.paragraphs)))
                                except Exception:
                                    pass
                            elif name.lower().endswith(".txt"):
                                try: candidates.append((name, z.read(name).decode("utf-8", "ignore")))
                                except Exception: pass
                except Exception:
                    continue
            else:
                candidates = [p]
            for item in candidates:
                if isinstance(item, tuple):
                    name, content = item
                else:
                    name = str(item)
                    try:
                        if item.suffix.lower() == ".docx":
                            from docx import Document
                            doc = Document(str(item))
                            content = "\n".join(x.text for x in doc.paragraphs)
                            for table in doc.tables:
                                for row in table.rows:
                                    content += "\n" + " ".join(c.text for c in row.cells)
                        elif item.suffix.lower() == ".txt":
                            content = item.read_text(encoding="utf-8", errors="ignore")
                        else:
                            continue
                    except Exception:
                        continue
                category = self.guess_category(name + " " + content[:1000])
                for line in content.splitlines():
                    line = re.sub(r"^\s*(?:[•●▪◦\-–—]+|\d+[.)])\s*", "", line).strip()
                    if not line:
                        continue
                    pieces = re.split(r"(?<=[.!?])\s+(?=[А-ЯA-Z])", line)
                    for phrase in pieces:
                        if self.add(phrase, str(name), category):
                            total += 1
        self.db.commit()
        return total

    @staticmethod
    def guess_category(text: str):
        t = text.lower()
        terms = [("Головной мозг", ["головн", "brain", "мозг"]), ("Позвоночник", ["позвон", "диск", "спинн"]), 
          ("Коленный сустав", ["коленн", "knee"]), ("Плечевой сустав", ["плечев", "shoulder"]),
          ("Таз и малый таз", ["малого таза", "тазобед", "простата", "матк"]), ("Брюшная полость", ["брюшн", "печен", "поджелуд", "abdomen"]),
          ("Стопа и голеностоп", ["стоп", "голеностоп", "ankle"]), ("Прочее", ["сустав", "мрт"])]
        for cat, keys in terms:
            if any(k in t for k in keys): return cat
        return "Общее"

    def categories(self):
        return ["Все категории"] + [r[0] for r in self.db.execute(
            "SELECT DISTINCT category FROM phrases ORDER BY category COLLATE NOCASE")]

    def used(self, phrase: str):
        self.db.execute("UPDATE phrases SET count=count+1 WHERE text=?", (phrase,))
        self.db.commit()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.library = PhraseLibrary()
        self.current_file = None
        self.setWindowTitle(APP_NAME)
        self.resize(1400, 900)
        self.setMinimumSize(980, 650)
        self.build_ui()
        self.refresh_categories()
        self.refresh_phrases()
        self.refresh_templates()
        self.update_status()

    def build_ui(self):
        self.setStatusBar(QStatusBar())
        self.editor = QTextEdit()
        self.editor.setAcceptRichText(True)
        self.editor.setFont(QFont("Times New Roman", 12))
        self.editor.setPlaceholderText("Начните составлять протокол МРТ…")
        self.editor.textChanged.connect(self.update_status)
        self.editor.textChanged.connect(self.update_suggestions)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.editor)
        side = QWidget(); side_l = QVBoxLayout(side); side_l.setContentsMargins(10,10,10,10)
        tabs = QTabWidget()
        phrase_tab = QWidget(); phrase_l = QVBoxLayout(phrase_tab)
        self.search = QLineEdit(); self.search.setPlaceholderText("Поиск по фразам…")
        self.search.textChanged.connect(self.refresh_phrases); phrase_l.addWidget(self.search)
        self.category = QLineEdit(); self.category.setPlaceholderText("Фильтр: категория")
        self.category.textChanged.connect(self.refresh_phrases); phrase_l.addWidget(self.category)
        self.phrases = QListWidget(); self.phrases.itemDoubleClicked.connect(self.insert_selected)
        phrase_l.addWidget(self.phrases, 1)
        add = QPushButton("Вставить фразу"); add.clicked.connect(self.insert_selected)
        phrase_l.addWidget(add)
        self.phrase_count = QLabel("Фраз: 0"); phrase_l.addWidget(self.phrase_count)
        template_tab = QWidget(); template_l = QVBoxLayout(template_tab)
        self.template_search = QLineEdit(); self.template_search.setPlaceholderText("Поиск по готовым протоколам…")
        self.template_search.textChanged.connect(self.refresh_templates); template_l.addWidget(self.template_search)
        self.template_list = QListWidget(); self.template_list.itemDoubleClicked.connect(self.insert_template)
        template_l.addWidget(self.template_list, 1)
        insert_template_btn = QPushButton("Вставить протокол целиком")
        insert_template_btn.clicked.connect(self.insert_template); template_l.addWidget(insert_template_btn)
        self.template_count = QLabel("Протоколов: 0"); template_l.addWidget(self.template_count)
        tabs.addTab(phrase_tab, "Фразы")
        tabs.addTab(template_tab, "Протоколы")
        side_l.addWidget(tabs, 1)
        splitter.addWidget(side); splitter.setStretchFactor(0, 4); splitter.setStretchFactor(1, 2)
        self.setCentralWidget(splitter)
        self.create_actions()
        self.apply_style()

    def apply_style(self):
        self.setStyleSheet("""
        QMainWindow { background: #f4f6f8; }
        QTextEdit { background: white; border: 1px solid #cbd3dc; padding: 24px; selection-background-color: #c8def5; }
        QLineEdit { padding: 8px; border: 1px solid #cbd3dc; border-radius: 5px; background: white; }
        QListWidget { background: white; border: 1px solid #cbd3dc; }
        QListWidget::item { padding: 8px; border-bottom: 1px solid #edf0f3; }
        QListWidget::item:selected { background: #dcecff; color: #183b60; }
        QPushButton { padding: 8px 14px; border: 1px solid #aebdca; border-radius: 5px; background: #ffffff; }
        QPushButton:hover { background: #eaf2fa; }
        """)
    def action(self, name, shortcut, fn):
        a = QAction(name, self); a.setShortcut(shortcut); a.triggered.connect(fn); return a
    def create_actions(self):
        bar = QToolBar("Основная панель"); bar.setMovable(False); self.addToolBar(bar)
        for name, key, fn in [("Новый","Ctrl+N",self.new_file),("Открыть","Ctrl+O",self.open_file),("Сохранить","Ctrl+S",self.save_file),("Экспорт DOCX","Ctrl+Shift+S",self.export_docx)]:
            a=self.action(name,key,fn); bar.addAction(a)
        bar.addSeparator()
        font = QFontComboBox(); font.setCurrentFont(QFont("Times New Roman"))
        font.currentFontChanged.connect(lambda f: self.editor.setCurrentFont(f)); bar.addWidget(font)
        size = QSpinBox(); size.setRange(8,36); size.setValue(12); size.valueChanged.connect(lambda n: self.editor.setFontPointSize(n)); bar.addWidget(size)
        for label, key, fn in [("Ж","Ctrl+B",self.toggle_bold),("К","Ctrl+I",self.toggle_italic),("Ч","Ctrl+U",self.toggle_underline)]:
            a=self.action(label,key,fn); bar.addAction(a)
        menu = self.menuBar().addMenu("Файл")
        for n,k,f in [("Новый","Ctrl+N",self.new_file),("Открыть…","Ctrl+O",self.open_file),("Сохранить","Ctrl+S",self.save_file),("Экспорт в DOCX…","Ctrl+Shift+S",self.export_docx)]:
            menu.addAction(self.action(n,k,f))
        lib = self.menuBar().addMenu("Библиотека")
        lib.addAction(self.action("Импорт шаблонов…","",self.import_templates))
        lib.addAction(self.action("Обновить список фраз","",self.refresh_phrases))
        edit = self.menuBar().addMenu("Правка")
        edit.addAction(self.action("Найти…","Ctrl+F",self.find_text))
        edit.addAction(self.action("Заменить…","Ctrl+H",self.replace_text))
        edit.addAction(self.action("Отменить","Ctrl+Z",self.editor.undo))
        edit.addAction(self.action("Повторить","Ctrl+Y",self.editor.redo))

    def toggle_bold(self):
        fmt=QTextCharFormat(); fmt.setFontWeight(QFont.Weight.Bold if self.editor.fontWeight()!=QFont.Weight.Bold else QFont.Weight.Normal); self.editor.mergeCurrentCharFormat(fmt)
    def toggle_italic(self):
        fmt=QTextCharFormat(); fmt.setFontItalic(not self.editor.fontItalic()); self.editor.mergeCurrentCharFormat(fmt)
    def toggle_underline(self):
        fmt=QTextCharFormat(); fmt.setFontUnderline(not self.editor.fontUnderline()); self.editor.mergeCurrentCharFormat(fmt)
    def new_file(self):
        if self.editor.document().isModified():
            ans=QMessageBox.question(self,"Сохранить изменения?","Сохранить текущий документ перед созданием нового?")
            if ans==QMessageBox.StandardButton.Yes: self.save_file()
        self.editor.clear(); self.current_file=None; self.editor.document().setModified(False); self.update_status()
    def open_file(self):
        path,_=QFileDialog.getOpenFileName(self,"Открыть протокол","","Документы (*.docx *.txt);;Все файлы (*)")
        if not path: return
        try:
            if path.lower().endswith(".docx"):
                from docx import Document
                doc=Document(path); self.editor.setPlainText("\n".join(p.text for p in doc.paragraphs))
            else: self.editor.setPlainText(Path(path).read_text(encoding="utf-8",errors="replace"))
            self.current_file=path; self.editor.document().setModified(False); self.update_status()
        except Exception as e: QMessageBox.critical(self,"Ошибка открытия",str(e))
    def save_file(self):
        path=self.current_file
        if not path: path,_=QFileDialog.getSaveFileName(self,"Сохранить протокол","","Текст (*.txt)")
        if not path: return
        try:
            Path(path).write_text(self.editor.toPlainText(),encoding="utf-8")
            self.current_file=path; self.editor.document().setModified(False); self.update_status()
        except Exception as e: QMessageBox.critical(self,"Ошибка сохранения",str(e))
    def export_docx(self):
        path,_=QFileDialog.getSaveFileName(self,"Экспорт в DOCX","","Документ Word (*.docx)")
        if not path: return
        try:
            from docx import Document
            from docx.shared import Pt
            doc=Document()
            style=doc.styles["Normal"]; style.font.name="Times New Roman"; style.font.size=Pt(12)
            for line in self.editor.toPlainText().splitlines(): doc.add_paragraph(line)
            doc.save(path); self.statusBar().showMessage("Экспортировано: "+path,5000)
        except Exception as e: QMessageBox.critical(self,"Ошибка экспорта",str(e))
    def import_templates(self):
        paths=QFileDialog.getOpenFileNames(self,"Выберите DOCX/TXT или ZIP с шаблонами","","Шаблоны (*.docx *.txt *.zip)")
        if not paths[0]: return
        n=self.library.import_files(paths[0]); self.refresh_categories(); self.refresh_phrases()
        QMessageBox.information(self,"Импорт завершён",f"Добавлено/обновлено фрагментов: {n}\nВсего фраз в библиотеке: {self.library.db.execute('SELECT COUNT(*) FROM phrases').fetchone()[0]}")
    def refresh_categories(self):
        self.category.setToolTip("Доступные категории: "+", ".join(self.library.categories()))
    def refresh_phrases(self):
        if not hasattr(self,"phrases"): return
        cat_text=self.category.text().strip()
        cat=next((x for x in self.library.categories() if x.lower()==cat_text.lower()),"")
        rows=self.library.search(self.search.text().strip(),cat)
        self.phrases.clear()
        for phrase,count,category in rows:
            item=QListWidgetItem(phrase); item.setToolTip(f"{category} • использований: {count}"); self.phrases.addItem(item)
        self.phrase_count.setText(f"Найдено фраз: {len(rows)}")

    def refresh_templates(self):
        if not hasattr(self,"template_list"): return
        rows=self.library.search_templates(self.template_search.text().strip())
        self.template_list.clear()
        for template_id,title,category in rows:
            item=QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, template_id)
            item.setToolTip(category)
            self.template_list.addItem(item)
        self.template_count.setText(f"Найдено протоколов: {len(rows)}")

    def insert_template(self, *_):
        item=self.template_list.currentItem()
        if not item: return
        result=self.library.get_template(item.data(Qt.ItemDataRole.UserRole))
        if result:
            title,content=result
            cursor=self.editor.textCursor()
            if not self.editor.toPlainText().strip():
                self.editor.setPlainText(content)
            else:
                cursor.insertText(content + "\\n")
            self.editor.setFocus()
            self.statusBar().showMessage("Вставлен протокол: " + title, 4000)
    def insert_selected(self, *_):
        item=self.phrases.currentItem()
        if item:
            phrase=item.text(); self.editor.textCursor().insertText(phrase+" ")
            self.library.used(phrase); self.refresh_phrases(); self.editor.setFocus()
    def update_suggestions(self):
        text=self.editor.toPlainText()
        token=re.search(r"([^\s\n]{2,})$",text)
        if not token: return
        matches=self.library.suggestions(token.group(1))
        if matches and matches[0].lower()!=token.group(1).lower():
            self.statusBar().showMessage("Подсказки: "+"  |  ".join(matches[:3]),2500)
    def find_text(self):
        q,ok=QInputDialog.getText(self,"Найти","Текст:")
        if ok and q and not self.editor.find(q):
            self.editor.moveCursor(QTextCursor.MoveOperation.Start)
            if not self.editor.find(q): QMessageBox.information(self,"Поиск","Совпадений не найдено.")
    def replace_text(self):
        old,ok=QInputDialog.getText(self,"Заменить","Найти:")
        if not ok or not old: return
        new,ok=QInputDialog.getText(self,"Заменить","Заменить на:")
        if not ok: return
        text=self.editor.toPlainText().replace(old,new); self.editor.setPlainText(text)
    def update_status(self):
        if hasattr(self,"editor"):
            words=len(re.findall(r"\S+",self.editor.toPlainText()))
            self.statusBar().showMessage(f"Слов: {words}   |   Символов: {len(self.editor.toPlainText())}")

if __name__ == "__main__":
    app=QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w=MainWindow(); w.show()
    sys.exit(app.exec())
