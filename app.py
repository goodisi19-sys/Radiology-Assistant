from __future__ import annotations
from contextlib import closing
import difflib
import os, sys, re, sqlite3, zipfile, json, base64, brotli, hashlib, datetime, io, xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable
from PySide6.QtCore import Qt, QStringListModel, QStandardPaths, QTimer, QEvent
from PySide6.QtGui import QAction, QFont, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QPlainTextEdit, QTextEdit, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QFileDialog, QMessageBox, QToolBar, QFontComboBox, QSpinBox,
    QCompleter, QInputDialog, QStatusBar, QTabWidget, QTreeWidget, QTreeWidgetItem, QDialog)

from report_format import format_line, format_report
from template_layout import ParagraphEvidence, odt_paragraphs

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
        # Snapshot existing data before this version's metadata migration.
        if self.path.exists():
            with closing(sqlite3.connect(str(self.path))) as old:
                migrated = old.execute("SELECT 1 FROM sqlite_master WHERE name='catalog_metadata_v2'").fetchone()
                if not migrated:
                    folder = app_data_dir() / 'backups'
                    folder.mkdir(exist_ok=True)
                    target = folder / ('before-catalog-v2-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.sqlite3')
                    with closing(sqlite3.connect(str(target))) as destination: old.backup(destination)
        self.db = sqlite3.connect(str(self.path))
        self._layout_sources = []
        self.db.create_function("raw_digest", 1, lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest(), deterministic=True)
        self.db.create_function("casefold", 1, lambda value: (value or "").casefold())
        self.db.execute("""CREATE TABLE IF NOT EXISTS phrases(
            id INTEGER PRIMARY KEY, text TEXT UNIQUE NOT NULL, count INTEGER DEFAULT 1,
            source TEXT DEFAULT '', category TEXT DEFAULT 'Общее')""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS templates(
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL,
            content TEXT NOT NULL, source TEXT DEFAULT '')""")
        self.db.execute("CREATE TABLE IF NOT EXISTS template_folders(template_id INTEGER PRIMARY KEY, folder_path TEXT NOT NULL, fingerprint TEXT UNIQUE)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_template_folder_path ON template_folders(folder_path)")
        self.db.execute("CREATE TABLE IF NOT EXISTS verified_standards(id INTEGER PRIMARY KEY, title TEXT, category TEXT, content TEXT, digest TEXT UNIQUE, uses INTEGER DEFAULT 1, verified_at TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS quick_lines(id INTEGER PRIMARY KEY, text TEXT UNIQUE NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS app_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        for text in json.loads(bundled_data_path('quick_lines.json').read_text(encoding='utf-8'))['lines']:
            self.db.execute("INSERT OR IGNORE INTO quick_lines(text) VALUES(?)", (text,))
        self.db.execute("CREATE TABLE IF NOT EXISTS template_layouts(template_id INTEGER PRIMARY KEY, original_digest TEXT NOT NULL, content TEXT NOT NULL, fingerprint TEXT NOT NULL, kind TEXT NOT NULL)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_template_layout_fingerprint ON template_layouts(fingerprint)")
        self.db.execute("CREATE TABLE IF NOT EXISTS complete_builtin_phrases(text TEXT PRIMARY KEY)")
        self.db.execute("CREATE TABLE IF NOT EXISTS spelling_words(word TEXT PRIMARY KEY)")
        self.db.execute("CREATE TABLE IF NOT EXISTS favorites(id INTEGER PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL, html TEXT NOT NULL, UNIQUE(title,category))")
        self.db.commit()
        self.load_bundled_templates()
        self.index_existing_templates()
        self.load_extra_protocols()
        self.load_drive_odt_protocols()
        self.normalize_categories()
        self.install_bundled_layouts()
        from adaptive_completion import AdaptiveMemory
        self.adaptive = AdaptiveMemory(self.db)
        for (content,) in self.db.execute('SELECT content FROM verified_standards').fetchall():
            if content: self.adaptive.learn(content, verified=True)
        self.db.execute("CREATE TABLE IF NOT EXISTS catalog_metadata_v2(version INTEGER)")
        self.db.commit()

    def quick_lines(self, query=''):
        return [row[0] for row in self.db.execute(
            "SELECT text FROM quick_lines WHERE instr(casefold(text),?)>0 ORDER BY id DESC", (query.casefold(),))]

    def add_quick_line(self, text):
        text = text.strip()
        if not text: return False
        if len(text) > 12000: raise ValueError('Выберите строку или фрагмент до 12 000 символов.')
        result = self.db.execute("INSERT OR IGNORE INTO quick_lines(text) VALUES(?)", (text,))
        self.db.commit()
        return result.rowcount > 0

    def get_setting(self, key):
        row = self.db.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else ''

    def set_setting(self, key, value):
        self.db.execute("INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.db.commit()

    def load_bundled_templates(self):
        count = self.db.execute("SELECT COUNT(*) FROM templates WHERE source=?", ("Встроенная библиотека МРТ",)).fetchone()[0]
        source = bundled_data_path("protocols.json.br.b64")
        if not source.exists():
            return
        try:
            packed = base64.b64decode(source.read_text(encoding="ascii"))
            data = json.loads(brotli.decompress(packed).decode("utf-8"))
            self._layout_sources.extend({'source': 'Встроенная библиотека МРТ', 'title': title,
                'raw': content, 'layout': content, 'kind': 'base-evidence'} for title, category, content in data)
            if count: return
            for title, category, content in data:
                self.db.execute("INSERT INTO templates(title,category,content,source) VALUES(?,?,?,?)",
                                (title, category, content, "Встроенная библиотека МРТ"))
                for line in content.splitlines():
                    phrase = re.sub(r"\s+", " ", line).strip(" •-—\t\r\n")
                    if len(phrase) >= 25 and len(phrase) <= 900:
                        self.db.execute("""INSERT INTO phrases(text,count,source,category) VALUES(?,1,?,?)
                            ON CONFLICT(text) DO UPDATE SET count=count+1, source=CASE WHEN excluded.source='Личный стандарт' THEN excluded.source ELSE phrases.source END""",
                            (phrase, "Встроенный протокол", category))
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            raise RuntimeError("Не удалось загрузить встроенную библиотеку протоколов: " + str(exc))

    def verify(self, title, category, content):
        normalized = re.sub(r"\s+", " ", content).strip()
        if len(normalized) < 30: raise ValueError("Протокол слишком короткий")
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        self.db.execute("INSERT INTO verified_standards(title,category,content,digest,verified_at) VALUES(?,?,?,?,?) ON CONFLICT(digest) DO UPDATE SET uses=uses+1,verified_at=excluded.verified_at", (title,category,content,digest,datetime.datetime.now().isoformat()))
        for line in content.splitlines():
            phrase = re.sub(r"\s+", " ", line).strip(" •-—\t\r\n")
            if self.add(phrase,"Личный стандарт",category):
                self.db.execute("UPDATE phrases SET count=count+10 WHERE text=?", (phrase,))
        self.db.commit()
        self.adaptive.learn(content, verified=True)

    def backup(self):
        folder = app_data_dir() / "backups"
        folder.mkdir(exist_ok=True)
        target = folder / ("library-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ".sqlite3")
        with closing(sqlite3.connect(str(target))) as destination: self.db.backup(destination)
        return target

    def search(self, query: str = "", category: str = ""):
        sql = "SELECT text, count, category FROM phrases WHERE 1=1"
        args = []
        if query:
            sql += " AND casefold(text) LIKE ?"
            args.append("%" + query.casefold() + "%")
        if category and category != "Все категории":
            sql += " AND category = ?"
            args.append(category)
        sql += " ORDER BY (source='Личный стандарт') DESC, count DESC, text COLLATE NOCASE LIMIT 500"
        return self.db.execute(sql, args).fetchall()

    def search_templates(self, query: str = ""):
        return self.db.execute("""SELECT t.id,t.title,t.category FROM templates t
            LEFT JOIN template_layouts l ON l.template_id=t.id AND l.original_digest=raw_digest(t.content)
            WHERE casefold(t.title) LIKE ? OR casefold(COALESCE(l.content,t.content)) LIKE ?
            ORDER BY t.category,t.title""", ('%'+query.casefold()+'%', '%'+query.casefold()+'%')).fetchall()

    def get_template(self, template_id: int):
        return self.db.execute("""SELECT t.title,COALESCE(l.content,t.content) FROM templates t
            LEFT JOIN template_layouts l ON l.template_id=t.id AND l.original_digest=raw_digest(t.content)
            WHERE t.id=?""", (template_id,)).fetchone()

    def template_needs_source_review(self, template_id):
        return bool(self.db.execute("""SELECT 1 FROM template_layouts l JOIN templates t ON t.id=l.template_id
            WHERE t.id=? AND l.kind='base-evidence' AND l.original_digest=raw_digest(t.content)""", (template_id,)).fetchone())

    def install_bundled_layouts(self):
        # Stored clinical text, IDs and old deduplication keys remain untouched.
        # Layout applies only while the row matches the original bundled text.
        evidence = ParagraphEvidence(record['layout'] for record in self._layout_sources if record['kind'] != 'base-evidence')
        originals = {record['source_id']: record for record in json.loads(bundled_data_path('protocol_sources.json').read_text(encoding='utf-8'))}
        originals.update({record['source'].removeprefix('Google Drive: '):
            {'content': record['layout'], 'binary_sha256': record['binary_sha256']}
            for record in self._layout_sources if record['kind'] == 'odt-original'})
        self.complete_originals = originals
        manifest = json.loads(bundled_data_path('protocol_source_map.json').read_text(encoding='utf-8'))
        repairs = {record['original_sha256']: record for record in manifest['repairs']}
        plans = {}
        for record in self._layout_sources:
            rendered, joined = (evidence.unwrap(record['raw']) if record['kind'] == 'base-evidence'
                                else (record['layout'], 0))
            kind, recovered_from = record['kind'], None
            repair = repairs.get(hashlib.sha256(record['raw'].encode('utf-8')).hexdigest()) if kind == 'base-evidence' else None
            if repair:
                original = originals[repair['source_id']]
                if original['binary_sha256'] != repair['source_binary_sha256']:
                    raise RuntimeError('Изменился исходник восстановления: ' + repair['source_title'])
                retained = iter(re.findall(r'\w+', original['content'].casefold()))
                if not all(any(word == candidate for candidate in retained) for word in re.findall(r'\w+', record['raw'].casefold())):
                    raise RuntimeError('Исходник не подтверждает сохранность текста: ' + record['title'])
                rendered, joined, kind = original['content'], 0, 'base-restored'
                recovered_from = repair['source_id']
            for template_id, current in self.db.execute('SELECT id,content FROM templates WHERE source=? AND title=?',
                                                       (record['source'], record['title'])):
                if current != record['raw']: continue  # Respect personal edits, including layout edits.
                original = hashlib.sha256(current.encode('utf-8')).hexdigest()
                fingerprint = hashlib.sha256(re.sub(r'\s+', ' ', rendered).strip().encode('utf-8')).hexdigest()
                plans[template_id] = (original, rendered, fingerprint, kind, joined, current != rendered, recovered_from)
        self.layout_audit = []
        self.db.execute('DELETE FROM complete_builtin_phrases')
        for template_id, (original, rendered, fingerprint, kind, joined, changed, recovered_from) in plans.items():
            self.db.execute("""INSERT INTO template_layouts(template_id,original_digest,content,fingerprint,kind)
                VALUES(?,?,?,?,?) ON CONFLICT(template_id) DO UPDATE SET original_digest=excluded.original_digest,
                content=excluded.content,fingerprint=excluded.fingerprint,kind=excluded.kind""",
                (template_id, original, rendered, fingerprint, kind))
            self.layout_audit.append({'id': template_id, 'kind': kind, 'changed': changed, 'joined_boundaries': joined,
                'recovered_from': recovered_from, 'needs_source_review': kind == 'base-evidence'})
            if kind != 'base-evidence':
                category = self.db.execute('SELECT category FROM templates WHERE id=?', (template_id,)).fetchone()[0]
                for line in rendered.splitlines():
                    phrase = re.sub(r'\s+', ' ', line).strip(' •-—\t\r\n')
                    if 18 <= len(phrase) <= 900:
                        self.db.execute('INSERT OR IGNORE INTO complete_builtin_phrases(text) VALUES(?)', (phrase,))
                        self.db.execute("INSERT OR IGNORE INTO phrases(text,count,source,category) VALUES(?,1,'Встроенный протокол',?)", (phrase,category))
        self.db.commit()

    def suggestions(self, prefix: str, limit: int = 12):
        if len(prefix.strip()) < 2:
            return []
        return [r[0] for r in self.db.execute(
            """SELECT text FROM phrases WHERE casefold(text) LIKE ? AND
            ((source!='Встроенный протокол' AND source NOT LIKE 'Google Drive: %')
             OR text IN (SELECT text FROM complete_builtin_phrases))
            ORDER BY (source='Личный стандарт') DESC, count DESC LIMIT ?""",
            (prefix.strip().casefold() + "%", limit)).fetchall()]

    def add(self, text: str, source: str, category: str):
        text = re.sub(r"\s+", " ", text).strip(" •-—\t\r\n")
        if len(text) < 18 or len(text) > 900:
            return False
        self.db.execute("""INSERT INTO phrases(text,count,source,category) VALUES(?,1,?,?)
            ON CONFLICT(text) DO UPDATE SET count=count+1, source=CASE WHEN excluded.source='Личный стандарт' THEN excluded.source ELSE phrases.source END""", (text, source, category or "Общее"))
        return True

    def index_existing_templates(self):
        """Index existing 145-template library to prevent duplicates on upgrade."""
        rows=self.db.execute("""SELECT t.id,t.category,t.content FROM templates t
            LEFT JOIN template_folders f ON f.template_id=t.id WHERE f.template_id IS NULL""").fetchall()
        for template_id,category,content in rows:
            normalized=re.sub(r"\s+"," ",content).strip()
            digest=hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            if self.db.execute("SELECT 1 FROM template_folders WHERE fingerprint=?", (digest,)).fetchone():
                digest = None  # Retain pre-existing duplicate records without losing their folders.
            self.db.execute("INSERT OR IGNORE INTO template_folders(template_id,folder_path,fingerprint) VALUES(?,?,?)",
                (template_id,category,digest))
        self.db.commit()

    def load_extra_protocols(self):
        for name in ("protocols_extra.json","protocols_legacy.json"):
            source=bundled_data_path(name)
            if not source.exists(): continue
            for record in json.loads(source.read_text(encoding="utf-8")):
                folder=record.get("folder","")
                if any(k in folder.casefold() for k in ("мибс","2006")): continue
                source_name = "Google Drive: " + record.get("source_id", "")
                self.import_full_protocol(record["title"],folder,record["content"], source_name)
                self._layout_sources.append({'source': source_name, 'title': record['title'], 'raw': record['content'],
                    'layout': record.get('layout_content', record['content']), 'legacy_body': record.get('body_layout', record['content']),
                    'kind': 'doc-original' if name == 'protocols_legacy.json' else 'extra'})
        self.db.commit()

    def load_drive_odt_protocols(self):
        """Read bundled ODT template archives. Never import from excluded sources."""
        namespace = {"text":"urn:oasis:names:tc:opendocument:xmlns:text:1.0"}
        for source in sorted(bundled_data_path(".").glob("drive_odt_*.json")):
            try:
                records=json.loads(source.read_text(encoding="utf-8"))
            except Exception as exc:
                raise RuntimeError(f"Ошибка библиотеки {source.name}: {exc}") from exc
            for record in records:
                folder=record.get("folder","")
                title=record.get("title","")
                if any(key in (folder+"/"+title).casefold() for key in ("мибс","2006")):
                    continue
                try:
                    blob=base64.b64decode(record["b64"])
                    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                        root=ET.fromstring(archive.read("content.xml"))
                    lines=["".join(node.itertext()).strip() for node in root.findall(".//text:p",namespace)]
                    content="\n".join(line for line in lines if line)
                    source_name = "Google Drive: " + record.get("id", "")
                    self.import_full_protocol(Path(title).stem,folder,content,source_name)
                    self._layout_sources.append({'source': source_name, 'title': Path(title).stem, 'raw': content,
                        'layout': odt_paragraphs(root), 'binary_sha256': hashlib.sha256(base64.b64decode(record['b64'])).hexdigest(),
                        'kind': 'odt-original'})
                except Exception as exc:
                    self.db.rollback()
                    raise RuntimeError(f"Ошибка протокола {title}: {exc}") from exc
        self.db.commit()

    def import_full_protocol(self, title, folder, content, source):
        normalized = re.sub(r"\s+", " ", content).strip()
        if self.excluded_source(folder + "/" + title): return False
        if len(normalized) < 35: return False
        fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        if self.db.execute("SELECT 1 FROM template_folders WHERE fingerprint=?", (fingerprint,)).fetchone():
            return False
        if self.db.execute("""SELECT 1 FROM template_layouts l JOIN templates t ON t.id=l.template_id
            WHERE l.fingerprint=? AND l.original_digest=raw_digest(t.content)""", (fingerprint,)).fetchone(): return False
        category = self.guess_category(folder + " " + title)
        cur = self.db.execute("INSERT INTO templates(title,category,content,source) VALUES(?,?,?,?)",
            (title,category,content,source))
        self.db.execute("INSERT INTO template_folders(template_id,folder_path,fingerprint) VALUES(?,?,?)",
            (cur.lastrowid,folder,fingerprint))
        for line in content.splitlines():
            self.add(line,source,category)
        return True

    def import_files(self, paths: Iterable[str]):
        total = 0
        full_total = 0
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
                                    import io
                                    from source_documents import read_word_source
                                    candidates.append((name, read_word_source(io.BytesIO(z.read(name)))['content']))
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
                candidate_name = item[0] if isinstance(item, tuple) else str(item)
                if self.excluded_source(str(p) + "/" + candidate_name):
                    continue
                if isinstance(item, tuple):
                    name, content = item
                else:
                    name = str(item)
                    try:
                        if item.suffix.lower() == ".docx":
                            from source_documents import read_word_source
                            content = read_word_source(str(item))['content']
                        elif item.suffix.lower() == ".txt":
                            content = item.read_text(encoding="utf-8", errors="ignore")
                        else:
                            continue
                    except Exception:
                        continue
                source_name = str(name)
                folder_path = str(Path(name).parent) if not isinstance(item, tuple) else str(Path(name).parent)
                if p.is_dir() and not isinstance(item, tuple):
                    folder_path = str(Path(name).parent.relative_to(p))
                if self.import_full_protocol(Path(name).stem, folder_path, content, source_name):
                    full_total += 1
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
        return total, full_total

    @staticmethod
    def excluded_source(path):
        return any(key in path.casefold() for key in ("мибс", "2006"))

    def normalize_categories(self):
        # Only migrate bundled metadata; never rewrite clinical content or personal data.
        mapping = {"Головной мозг": "ГМ", "Таз и малый таз": "ОМТ",
            "Прочие суставы": "Суставы", "Тазобедренный сустав": "Суставы",
            "Стопа и голеностоп": "Суставы", "Коленный сустав": "Суставы",
            "Плечевой сустав": "Суставы", "Общее": "Другие исследования"}
        for old, new in mapping.items():
            self.db.execute("UPDATE templates SET category=? WHERE category=? AND source=?",
                            (new, old, "Встроенная библиотека МРТ"))
        for template_id, folder in self.db.execute("SELECT t.id,f.folder_path FROM templates t JOIN template_folders f ON f.template_id=t.id WHERE t.source LIKE 'Google Drive:%'").fetchall():
            self.db.execute("UPDATE templates SET category=? WHERE id=?", (self.guess_category(folder), template_id))
        for (content,) in self.db.execute("SELECT content FROM verified_standards").fetchall():
            for line in content.splitlines():
                phrase = re.sub(r"\s+", " ", line).strip(" •-—\t\r\n")
                self.db.execute("UPDATE phrases SET source='Личный стандарт' WHERE text=?", (phrase,))
        self.db.commit()

    @staticmethod
    def guess_category(text: str):
        t = text.casefold()
        # The source anatomical folder takes precedence over words in a title.
        root = re.split(r"[/\\]", t)[0]
        if root.startswith("позвоночник"): return "Позвоночник"
        if root.startswith("суставы"): return "Суставы"
        if root.startswith("голова"): return "ГМ"
        if root.startswith("малый таз"): return "ОМТ"
        if root.startswith("брюшная полость"): return "Брюшная полость"
        if root.startswith("мягкие ткани"): return "Мягкие ткани"
        if any(k in t for k in ("голова м","головн","гм+","гм,","гм ","вены гм","мозг","гипофиз","мра","орбит","пазух","ппн","нейроваскуляр")):
            return "ГМ"
        if any(k in t for k in ("малый таз","малого таза","омт","матк","яичник","простата","предстател","pi-rads")):
            return "ОМТ"
        if any(k in t for k in ("суставы м","колен","плечев","тазобед","голеностоп","локтев","кисть","стопа","мениск","связк","внчс","кпс")):
            return "Суставы"
        if any(k in t for k in ("позвоночник","позвон","шоп","гоп","поп","спинн","диск l","диск th")):
            return "Позвоночник"
        return "Другие исследования"

    @staticmethod
    def folder_tree_path(folder, category):
        folder=folder.replace("\\","/").strip("/")
        if not folder or folder=="." or folder==category:
            return category
        starts=("ГМ/","ОМТ/","Позвоночник/","Суставы/","Другие исследования/")
        if folder.startswith(starts): return folder
        if folder.casefold().startswith(("голова","мрт голова")): return "ГМ/"+folder
        if folder.casefold().startswith(("малый таз","омт")) or "малый таз" in folder.casefold(): return "ОМТ/"+folder
        if folder.casefold().startswith(("позвоночник","шоп","гоп","поп")): return "Позвоночник/"+folder
        if folder.casefold().startswith(("суставы","колен","плечев","тазобед","кисть","стопа","голеностоп")): return "Суставы/"+folder
        if category in ("ГМ","ОМТ","Позвоночник","Суставы") and folder != category:
            return category+"/"+folder
        return "Другие исследования/"+folder

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
        self._closing = False
        self.setWindowTitle(APP_NAME)
        self.resize(1400, 900)
        self.setMinimumSize(980, 650)
        self.setFont(QFont("Segoe UI", 10))
        self.build_ui()
        self.refresh_phrases()
        self.refresh_templates()
        self.autosave_timer=QTimer(self)
        self.autosave_timer.timeout.connect(self.autosave_draft)
        self.autosave_timer.start(30000)
        self.update_status()

    def build_ui(self):
        self.setStatusBar(QStatusBar())
        self.editor = QTextEdit()
        self.editor.setObjectName("reportEditor")
        self.editor.setAcceptRichText(True)
        self.editor.setFont(QFont("Times New Roman", 12))
        self.editor.setPlaceholderText("Начните составлять протокол МРТ…")
        self.editor.textChanged.connect(self.update_status)
        self.editor.textChanged.connect(self.update_suggestions)
        self.editor.installEventFilter(self)
        self.editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.editor.customContextMenuRequested.connect(self.show_editor_menu)
        from live_spelling import LiveSpelling
        self.live_spelling = LiveSpelling(self)
        self.completer=QCompleter(self.editor)
        self.completion_model = QStringListModel(self.completer)
        self.completer.setModel(self.completion_model)
        self.completer.setWidget(self.editor)
        self.completer.popup().setStyleSheet("QAbstractItemView {background:white;color:#202b38;selection-background-color:#dcecff;selection-color:#183b60;}")
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.completer.setMaxVisibleItems(5)
        self.completer.activated.connect(self.accept_completion)
        self.editor.installEventFilter(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.editor)
        side = QWidget(); side_l = QVBoxLayout(side); side_l.setContentsMargins(10,10,10,10)
        tabs = self.side_tabs = QTabWidget()
        phrase_tab = QWidget(); phrase_l = QVBoxLayout(phrase_tab)
        self.search = QLineEdit(); self.search.setPlaceholderText("Поиск по быстрым строкам…")
        self.search.textChanged.connect(self.refresh_phrases); phrase_l.addWidget(self.search)
        self.phrases = QListWidget(); self.phrases.setWordWrap(True); self.phrases.itemDoubleClicked.connect(self.insert_selected)
        phrase_l.addWidget(self.phrases, 1)
        add = QPushButton("Вставить быструю строку"); add.clicked.connect(self.insert_selected)
        phrase_l.addWidget(add)
        self.phrase_count = QLabel("Быстрых строк: 0"); phrase_l.addWidget(self.phrase_count)
        template_tab = QWidget(); template_l = QVBoxLayout(template_tab)
        self.template_search = QLineEdit(); self.template_search.setPlaceholderText("Поиск по готовым протоколам…")
        self.template_search.textChanged.connect(self.refresh_templates); template_l.addWidget(self.template_search)
        self.template_list = QTreeWidget(); self.template_list.setHeaderHidden(True); self.template_list.itemDoubleClicked.connect(self.insert_template)
        template_l.addWidget(self.template_list, 1)
        insert_template_btn = QPushButton("Вставить протокол целиком")
        insert_template_btn.clicked.connect(self.insert_template); template_l.addWidget(insert_template_btn)
        self.template_count = QLabel("Протоколов: 0"); template_l.addWidget(self.template_count)
        tabs.addTab(phrase_tab, "Быстрые строки")
        tabs.insertTab(0, template_tab, "Протоколы")
        from favorites import FavoritesPanel
        self.favorites = FavoritesPanel(self)
        tabs.addTab(self.favorites, "★ Избранное")
        tabs.setCurrentWidget(template_tab)
        from google_reference import GoogleReference
        self.reference = GoogleReference(self)
        tabs.addTab(self.reference, "Google")
        tabs.currentChanged.connect(lambda index: self.reference.activate() if tabs.widget(index) is self.reference else None)
        side_l.addWidget(tabs, 1)
        splitter.addWidget(side); splitter.setStretchFactor(0, 4); splitter.setStretchFactor(1, 2)
        self.setCentralWidget(splitter)
        self.create_actions()
        self.apply_style()

    def apply_style(self):
        from appearance import apply
        apply(self)
    def action(self, name, shortcut, fn):
        a = QAction(name, self); a.setShortcut(shortcut); a.triggered.connect(fn); return a
    def create_actions(self):
        bar = QToolBar("Основная панель"); bar.setMovable(False); self.addToolBar(bar)
        for name, key, fn in [("Новый","Ctrl+N",self.new_file),("Открыть","Ctrl+O",self.open_file),("Сохранить","Ctrl+S",self.save_file),("Экспорт DOCX","Ctrl+Shift+S",self.export_docx)]:
            a=self.action(name,key,fn); bar.addAction(a)
        command_bar = bar
        self.addToolBarBreak()
        bar = QToolBar("Форматирование"); bar.setObjectName("formatBar"); bar.setMovable(False); self.addToolBar(bar)
        font = QFontComboBox(); font.setCurrentFont(QFont("Times New Roman"))
        font.currentFontChanged.connect(lambda f: self.editor.setCurrentFont(f)); bar.addWidget(font)
        size = QSpinBox(); size.setRange(8,36); size.setValue(12); size.valueChanged.connect(lambda n: self.editor.setFontPointSize(n)); bar.addWidget(size)
        for label, key, fn in [("Ж","Ctrl+B",self.toggle_bold),("К","Ctrl+I",self.toggle_italic),("Ч","Ctrl+U",self.toggle_underline)]:
            a=self.action(label,key,fn); bar.addAction(a)
        bar = command_bar
        menu = self.menuBar().addMenu("Файл")
        for n,k,f in [("Новый","Ctrl+N",self.new_file),("Открыть…","Ctrl+O",self.open_file),("Сохранить","Ctrl+S",self.save_file),("Экспорт в DOCX…","Ctrl+Shift+S",self.export_docx)]:
            menu.addAction(self.action(n,k,f))
        lib = self.menuBar().addMenu("Библиотека")
        lib.addAction(self.action("Импорт шаблонов…","",self.import_templates))
        lib.addAction(self.action("Импорт папки с подпапками…","",self.import_folder))
        lib.addAction(self.action("Быстрые строки протоколов","Ctrl+Shift+L",self.show_quick_lines))
        lib.addAction(self.action("Добавить выделенное в быстрые строки","Ctrl+Alt+L",self.add_selection_to_quick_lines))
        lib.addAction(self.action("Верифицировать стандарт","Ctrl+Shift+V",self.verify_current))
        lib.addAction(self.action("Резервная копия базы","",self.backup_database))
        adaptive_menu = lib.addMenu('Адаптивное продолжение')
        learning = QAction('Обучение и подсказки продолжений', self); learning.setCheckable(True)
        learning.setChecked(self.library.get_setting('adaptive_enabled') != '0')
        learning.toggled.connect(lambda value: self.library.set_setting('adaptive_enabled', '1' if value else '0'))
        adaptive_menu.addAction(learning)
        adaptive_menu.addAction(self.action('О памяти продолжений', '', self.adaptive_info))
        adaptive_menu.addAction(self.action('Очистить накопленные продолжения', '', self.clear_adaptive))
        bar.addAction(self.action("★ В избранное", "Ctrl+Alt+F", self.favorites.save_current))
        bar.addAction(self.action("Яндекс Редактор", "Ctrl+Alt+Y", self.show_yandex_editor))
        bar.addAction(self.action("Проверить опечатки", "F7", self.show_spelling))
        bar.addAction(self.action("Проверить протокол", "F8", self.show_protocol_check))
        bar.addAction(self.action("Оформить текст","Ctrl+Shift+F",self.format_all_text))
        edit = self.menuBar().addMenu("Правка")
        edit.addAction(self.action("Оформить предложения","Ctrl+Shift+F",self.format_all_text))
        edit.addAction(self.action("Проверить опечатки", "", self.show_spelling))
        live = QAction("Подчёркивать опечатки", self); live.setCheckable(True)
        live.setChecked(self.live_spelling.enabled)
        live.toggled.connect(self.live_spelling.set_enabled); edit.addAction(live)
        edit.addAction(self.action("Развернуть заметку", "Ctrl+Alt+R", self.show_shorthand))
        edit.addAction(self.action("Улучшить формулировку", "Ctrl+Alt+E", self.improve_fragment))
        edit.addAction(self.action("Найти…","Ctrl+F",self.find_text))
        edit.addAction(self.action("Заменить…","Ctrl+H",self.replace_text))
        edit.addAction(self.action("Отменить","Ctrl+Z",self.editor.undo))
        edit.addAction(self.action("Повторить","Ctrl+Y",self.editor.redo))

    def autosave_draft(self):
        if self.editor.document().isModified():
            target=app_data_dir() / "autosave-draft.txt"
            temp=target.with_suffix(".tmp")
            temp.write_text(self.editor.toPlainText(),encoding="utf-8")
            temp.replace(target)

    def backup_database(self):
        try: QMessageBox.information(self,"Копия базы",str(self.library.backup()))
        except Exception as exc: QMessageBox.critical(self,"Ошибка",str(exc))

    def verify_current(self):
        title,ok=QInputDialog.getText(self,"Личный стандарт","Название протокола:")
        if not ok or not title.strip(): return
        category=self.library.guess_category(title+" "+self.editor.toPlainText()[:300])
        try:
            self.library.verify(title,category,self.editor.toPlainText())
            self.live_spelling.reload_words()
            self.refresh_phrases()
            QMessageBox.information(self,"Верифицировано","Протокол сохранён как личный стандарт.")
        except Exception as exc: QMessageBox.critical(self,"Ошибка",str(exc))

    def toggle_bold(self):
        fmt=QTextCharFormat(); fmt.setFontWeight(QFont.Weight.Bold if self.editor.fontWeight()!=QFont.Weight.Bold else QFont.Weight.Normal); self.editor.mergeCurrentCharFormat(fmt)
    def toggle_italic(self):
        fmt=QTextCharFormat(); fmt.setFontItalic(not self.editor.fontItalic()); self.editor.mergeCurrentCharFormat(fmt)
    def toggle_underline(self):
        fmt=QTextCharFormat(); fmt.setFontUnderline(not self.editor.fontUnderline()); self.editor.mergeCurrentCharFormat(fmt)
    def confirm_discard(self):
        if not self.editor.document().isModified(): return True
        answer = QMessageBox.question(self, "Сохранить изменения?", "Сохранить текущий документ?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save: return bool(self.save_file())
        return answer == QMessageBox.StandardButton.Discard

    def closeEvent(self, event):
        if self.confirm_discard():
            self._closing = True
            self.completer.popup().hide()
            self.autosave_timer.stop()
            if hasattr(self, 'yandex_dialog'): self.yandex_dialog.close()
            self.live_spelling.stop()
            if hasattr(self, 'shorthand_dialog'): self.shorthand_dialog.close()
            if hasattr(self, 'protocol_check_dialog'): self.protocol_check_dialog.close()
            self.library.db.close()
            event.accept()
        else: event.ignore()

    def new_file(self):
        if not self.confirm_discard(): return
        self.editor.clear(); self.current_file=None; self.editor.document().setModified(False); self.update_status()

    def open_file(self):
        if not self.confirm_discard(): return
        path,_=QFileDialog.getOpenFileName(self,"Открыть протокол","","Документы (*.docx *.txt)")
        if not path: return
        try:
            if path.lower().endswith(".docx"):
                from document_io import read_docx
                text = read_docx(path)
            else: text = Path(path).read_text(encoding="utf-8")
            self.editor.setPlainText(text)
            self.current_file=path; self.editor.document().setModified(False); self.update_status()
        except Exception as e: QMessageBox.critical(self,"Ошибка открытия",str(e))
    def save_file(self):
        path=self.current_file
        if not path: path,_=QFileDialog.getSaveFileName(self,"Сохранить протокол","","Документ Word (*.docx);;Текст (*.txt)")
        if not path: return False
        if not Path(path).suffix: path += ".docx"
        try:
            self.format_all_text()
            if path.lower().endswith(".docx"): self.export_to_path(path)
            else:
                from document_io import atomic_write_text
                atomic_write_text(path, self.editor.toPlainText())
                self.learn_saved_description()
            self.current_file=path; self.editor.document().setModified(False); self.update_status()
            return True
        except Exception as e:
            QMessageBox.critical(self,"Ошибка сохранения",str(e))
            return False
    def export_to_path(self,path):
        from document_io import write_docx
        write_docx(path, self.editor.document())
        self.learn_saved_description()

    def learn_saved_description(self):
        if self.library.get_setting('adaptive_enabled') == '0': return
        try: self.library.adaptive.learn(self.editor.toPlainText())
        except sqlite3.Error:
            self.library.db.rollback()
            self.statusBar().showMessage('Документ сохранён, но память продолжений не обновилась.', 5000)

    def adaptive_info(self):
        QMessageBox.information(self, 'Адаптивное продолжение',
            f'Сохранено продолжений: {self.library.adaptive.count()}.\n'
            'Память пополняется после сохранения DOCX/TXT и верификации личного стандарта. '
            'Продолжения с цифрами, уровнями и явно указанной стороной не предлагаются. '
            'После пробела выбирайте продолжение по Tab или щелчком; Enter оставляет новый абзац. '
            'Это варианты из вашей базы, а не вывод о текущем исследовании.')

    def clear_adaptive(self):
        answer = QMessageBox.question(self, 'Очистить память продолжений?',
            'Удалить накопленные продолжения из сохранённых описаний? Личные стандарты и документы останутся.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.library.adaptive.clear_saved(); self.completer.popup().hide()

    def export_docx(self):
        path,_=QFileDialog.getSaveFileName(self,"Экспорт в DOCX","","Документ Word (*.docx)")
        if not path: return
        if not path.lower().endswith(".docx"): path += ".docx"
        try:
            self.format_all_text()
            self.export_to_path(path)
            self.statusBar().showMessage("Экспортировано: "+path,5000)
        except Exception as e: QMessageBox.critical(self,"Ошибка экспорта",str(e))
    def show_editor_menu(self, position):
        self.completer.popup().hide()
        menu = self.editor.createStandardContextMenu()
        self.live_spelling.add_menu(menu, self.editor.cursorForPosition(position))
        menu.addSeparator()
        action = menu.addAction('Добавить в быстрые строки протоколов')
        cursor = QTextCursor(self.editor.textCursor())
        if not cursor.hasSelection(): cursor = self.editor.cursorForPosition(position)
        action.triggered.connect(lambda: self.add_selection_to_quick_lines(cursor))
        menu.addAction('Развернуть заметку', self.show_shorthand)
        menu.addAction('Улучшить формулировку локально', self.improve_fragment)
        menu.addAction('★ В избранное', self.favorites.save_current)
        yandex = menu.addAction('Яндекс Редактор — через браузер')
        yandex.triggered.connect(self.show_yandex_editor)
        spelling = menu.addAction('Проверить опечатки')
        spelling.triggered.connect(self.show_spelling)
        menu.exec(self.editor.viewport().mapToGlobal(position))
        menu.deleteLater()

    def add_selection_to_quick_lines(self, cursor=None):
        cursor = QTextCursor(cursor) if isinstance(cursor, QTextCursor) else QTextCursor(self.editor.textCursor())
        if not cursor.hasSelection(): cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
        text = cursor.selectedText().replace('\u2029', '\n')
        if not text.strip(): return
        try:
            added = self.library.add_quick_line(text)
            self.refresh_phrases()
            if hasattr(self, 'quick_listing'): self.populate_quick_dialog()
            self.statusBar().showMessage('Строка добавлена в быстрые строки.' if added else 'Эта строка уже есть в списке.', 5000)
        except Exception as exc: QMessageBox.warning(self, 'Быстрые строки', str(exc))

    def fragment_target(self):
        cursor = QTextCursor(self.editor.textCursor())
        if not cursor.hasSelection():
            block = cursor.block()
            cursor.setPosition(block.position())
            cursor.setPosition(block.position() + block.length() - 1, QTextCursor.MoveMode.KeepAnchor)
        return cursor

    def show_shorthand(self):
        self.open_local_fragment(True)

    def improve_fragment(self):
        self.open_local_fragment(False)

    def open_local_fragment(self, expand):
        from local_editor import LocalEditorDialog
        if hasattr(self, 'shorthand_dialog'):
            self.shorthand_dialog.close(); self.shorthand_dialog.deleteLater()
        self.shorthand_dialog = LocalEditorDialog(self, self.fragment_target())
        self.shorthand_dialog.show()
        if expand: self.shorthand_dialog.expand_local()

    def show_yandex_editor(self):
        from yandex_editor import YandexEditorDialog
        if hasattr(self, 'yandex_dialog'):
            self.yandex_dialog.close(); self.yandex_dialog.deleteLater()
        self.yandex_dialog = YandexEditorDialog(self)
        self.yandex_dialog.show()

    def show_protocol_check(self):
        from protocol_check import create_dialog
        if not hasattr(self, "protocol_check_dialog"):
            self.protocol_check_dialog = create_dialog(self)
        self.protocol_check_dialog.scan()
        self.protocol_check_dialog.show(); self.protocol_check_dialog.raise_()

    def show_spelling(self):
        from spell_check import SpellingDialog
        if not hasattr(self, 'spelling_dialog'):
            self.spelling_dialog = SpellingDialog(self)
        self.spelling_dialog.scan()
        self.spelling_dialog.show(); self.spelling_dialog.raise_()

    def populate_quick_dialog(self):
        self.quick_listing.clear()
        for text in self.library.quick_lines(self.quick_search.text()):
            item = QListWidgetItem(text)
            item.setToolTip(text)
            self.quick_listing.addItem(item)

    def show_quick_lines(self):
        if not hasattr(self, 'quick_dialog'):
            self.quick_dialog = QDialog(self)
            self.quick_dialog.setWindowTitle('Быстрые строки протоколов')
            self.quick_dialog.resize(790, 620)
            layout = QVBoxLayout(self.quick_dialog)
            self.quick_search = QLineEdit()
            self.quick_search.setPlaceholderText('Поиск по быстрым строкам…')
            layout.addWidget(self.quick_search)
            self.quick_listing = QListWidget()
            self.quick_listing.setWordWrap(True)
            layout.addWidget(self.quick_listing)
            def insert_line(*_):
                item = self.quick_listing.currentItem()
                if item:
                    self.editor.textCursor().insertText(format_report(item.text()) + ' ')
                    self.editor.setFocus()
            self.quick_search.textChanged.connect(self.populate_quick_dialog)
            self.quick_listing.itemDoubleClicked.connect(insert_line)
            button = QPushButton('Вставить выбранную строку')
            button.clicked.connect(insert_line)
            layout.addWidget(button)
        self.populate_quick_dialog()
        self.quick_dialog.show()
        self.quick_dialog.raise_()
        self.quick_dialog.activateWindow()

    def import_folder(self):
        folder=QFileDialog.getExistingDirectory(self,"Выберите корневую папку протоколов")
        if not folder: return
        try:
            fragments,full=self.library.import_files([folder])
            self.refresh_phrases(); self.refresh_templates()
            QMessageBox.information(self,"Импорт",f"Новых полных протоколов: {full}\nФрагментов: {fragments}")
        except Exception as exc:
            QMessageBox.critical(self,"Ошибка импорта",str(exc))

    def import_templates(self):
        paths=QFileDialog.getOpenFileNames(self,"Выберите DOCX/TXT или ZIP с шаблонами","","Шаблоны (*.docx *.txt *.zip)")
        if not paths[0]: return
        n, full=self.library.import_files(paths[0]); self.refresh_phrases(); self.refresh_templates()
        QMessageBox.information(self,"Импорт завершён",f"Добавлено/обновлено фрагментов: {n}\nВсего фраз в библиотеке: {self.library.db.execute('SELECT COUNT(*) FROM phrases').fetchone()[0]}")
    def refresh_phrases(self):
        if not hasattr(self, 'phrases'): return
        self.phrases.clear()
        rows = self.library.quick_lines(self.search.text().strip())
        for text in rows:
            item = QListWidgetItem(text)
            item.setToolTip(text)
            self.phrases.addItem(item)
        self.phrase_count.setText(f'Быстрых строк: {len(rows)}')

    def refresh_templates(self):
        if not hasattr(self,"template_list"): return
        query=self.template_search.text().strip()
        rows=self.library.db.execute("""SELECT t.id,t.title,t.category,
            COALESCE(f.folder_path,t.category),l.kind FROM templates t
            LEFT JOIN template_folders f ON f.template_id=t.id
            LEFT JOIN template_layouts l ON l.template_id=t.id AND l.original_digest=raw_digest(t.content)
            WHERE casefold(t.title) LIKE ? OR casefold(COALESCE(l.content,t.content)) LIKE ?
            ORDER BY 4,t.title""", ("%"+query.casefold()+"%","%"+query.casefold()+"%")).fetchall()
        self.template_list.clear()
        nodes={}
        for template_id,title,category,path,kind in rows:
            path=self.library.folder_tree_path(path,category)
            parts=[p for p in re.split(r"[/\\\\]+",path) if p and p!="."]
            if not parts: parts=[category]
            parent=self.template_list
            key=""
            for part in parts:
                key += "/" + part
                if key not in nodes:
                    nodes[key]=QTreeWidgetItem(parent,[part])
                parent=nodes[key]
            item=QTreeWidgetItem(parent,[title + (' [проверить исходник]' if kind == 'base-evidence' else '')])
            item.setData(0,Qt.ItemDataRole.UserRole,template_id)
            item.setToolTip(0,category + ('\nПолный исходник не установлен: возможны пропуски строк.' if kind == 'base-evidence' else ''))
        total=self.library.db.execute("SELECT COUNT(*) FROM templates").fetchone()[0]
        self.template_count.setText(f"Протоколов в базе: {total} | Найдено: {len(rows)}")
        if query: self.template_list.expandAll()

    def eventFilter(self, obj, event):
        if obj is getattr(self, "editor", None) and event.type() == QEvent.Type.KeyPress:
            popup = self.completer.popup()
            selected = popup.currentIndex().data()
            if popup.isVisible() and selected in getattr(self, '_adaptive_options', {}):
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter): popup.hide()
                elif event.key() == Qt.Key.Key_Tab and not event.modifiers():
                    self.accept_completion(selected); return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
                event.modifiers() & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier)
            ):
                QTimer.singleShot(0, self.format_previous_line)
        return super().eventFilter(obj, event)

    def format_previous_line(self):
        block = self.editor.textCursor().block().previous()
        if not block.isValid():
            return
        current = block.text()
        formatted = format_line(current)
        if formatted != current:
            self.replace_block_text(block, current, formatted)

    @staticmethod
    def replace_block_text(block, current, updated):
        # Never select a paragraph separator; edit only changed characters so
        # both blank paragraphs and the surrounding font formatting survive.
        operations = difflib.SequenceMatcher(a=current, b=updated, autojunk=False).get_opcodes()
        for tag, left, right, new_left, new_right in reversed(operations):
            if tag == 'equal': continue
            cursor = QTextCursor(block)
            cursor.setPosition(block.position() + len(current[:left].encode('utf-16-le')) // 2)
            cursor.setPosition(block.position() + len(current[:right].encode('utf-16-le')) // 2, QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(updated[new_left:new_right])

    def format_all_text(self):
        doc = self.editor.document()
        saved_cursor = self.editor.textCursor()
        old_position = saved_cursor.position()
        changed = False
        saved_cursor.beginEditBlock()
        block = doc.firstBlock()
        while block.isValid():
            next_block = block.next()
            current = block.text()
            updated = format_line(current)
            if current != updated:
                self.replace_block_text(block, current, updated)
                changed = True
            block = next_block
        saved_cursor.endEditBlock()
        saved_cursor.setPosition(min(old_position, doc.characterCount() - 1))
        self.editor.setTextCursor(saved_cursor)
        self.statusBar().showMessage(
            "Предложения оформлены" if changed else "Текст уже оформлен", 3000
        )

    def insert_template(self, *_):
        item=self.template_list.currentItem()
        if not item: return
        template_id=item.data(0,Qt.ItemDataRole.UserRole)
        if template_id is None: return
        if self.library.template_needs_source_review(template_id):
            answer = QMessageBox.question(self, 'Проверить исходный шаблон',
                'Для этого старого шаблона не удалось однозначно установить полный исходник. '
                'В тексте могут отсутствовать методика или части предложений. '
                'Проверьте его по оригиналу перед использованием.\n\nВставить сохранившийся текст?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes: return
        result=self.library.get_template(template_id)
        if result:
            title,content=result
            cursor=self.editor.textCursor()
            if not self.editor.toPlainText().strip():
                self.editor.setPlainText(format_report(content))
            else:
                cursor.insertText(format_report(content) + "\n")
            self.editor.setFocus()
            self.statusBar().showMessage("Вставлен протокол: " + title,4000)
    def insert_selected(self, *_):
        item=self.phrases.currentItem()
        if item:
            phrase=item.text(); self.editor.textCursor().insertText(format_report(phrase)+" ")
            self.editor.setFocus()
    def accept_completion(self, phrase):
        if self._closing: return
        cursor = self.editor.textCursor()
        snapshot = getattr(self, '_completion_snapshot', None)
        if snapshot is not None and snapshot != (self.editor.toPlainText(), cursor.position(), cursor.anchor()):
            self.completer.popup().hide(); return
        continuation = getattr(self, '_adaptive_options', {}).get(phrase)
        if continuation:
            before = cursor.block().text().encode('utf-16-le')[:cursor.positionInBlock()*2].decode('utf-16-le')
            stripped = before.rstrip(' \t')
            cursor.beginEditBlock()
            if len(before) != len(stripped):
                cursor.movePosition(QTextCursor.MoveOperation.PreviousCharacter, QTextCursor.MoveMode.KeepAnchor, len(before)-len(stripped))
                cursor.removeSelectedText()
            separator = ' ' if stripped.endswith((',', ';', ':')) else continuation['separator']
            cursor.insertText(separator + continuation['text'] + ' ')
            cursor.endEditBlock()
        else:
            prefix = getattr(self, '_completion_word', self.completer.completionPrefix())
            if prefix and phrase.casefold().startswith(prefix.casefold()): cursor.insertText(phrase[len(prefix):] + ' ')
        self.editor.setTextCursor(cursor)
        self.completer.popup().hide()

    def update_suggestions(self):
        if self._closing or not hasattr(self,'completer'): return
        cursor = self.editor.textCursor()
        before = cursor.block().text().encode('utf-16-le')[:cursor.positionInBlock()*2].decode('utf-16-le')
        match = re.search(r'(\S{2,})$', before)
        prefix = match.group(1) if match else ''
        normal = self.library.suggestions(prefix, 20) if prefix else []
        self._adaptive_options = {}
        if self.library.get_setting('adaptive_enabled') != '0':
            for candidate in self.library.adaptive.suggest(before):
                label = ('Продолжить — личный стандарт (Tab): ' if candidate['verified'] else 'Продолжить — моя база (Tab): ') + candidate['text']
                self._adaptive_options[label] = candidate
        personal = [phrase for phrase in normal if self.library.db.execute("SELECT 1 FROM phrases WHERE text=? AND source='Личный стандарт'", (phrase,)).fetchone()]
        matches = personal + list(self._adaptive_options) + [phrase for phrase in normal if phrase not in personal]
        self._completion_word = prefix
        self._completion_snapshot = (self.editor.toPlainText(), cursor.position(), cursor.anchor())
        if not matches:
            self.completer.popup().hide(); return
        self.completion_model.setStringList(matches)
        self.completer.setCompletionPrefix('')
        # QCompleter.complete() normally positions the popup BELOW its rectangle.
        # Moving the rectangle alone is unreliable: Qt may resize/reposition
        # the popup afterwards. Position the actual popup above the typing line.
        popup = self.completer.popup()
        rect = self.editor.cursorRect()
        rect.setWidth(min(420, max(160, self.editor.viewport().width() - 24)))
        self.completer.complete(rect)
        self.position_completion_popup()
        # Qt can adjust a freshly shown popup during the next event cycle.
        QTimer.singleShot(0, self.position_completion_popup)

    def position_completion_popup(self):
        if self._closing or not hasattr(self, 'completer'):
            return
        popup = self.completer.popup()
        if not popup.isVisible():
            return
        viewport = self.editor.viewport()
        caret = self.editor.cursorRect()
        caret_global = viewport.mapToGlobal(caret.topLeft())
        viewport_global = viewport.mapToGlobal(viewport.rect().topLeft())
        screen = QApplication.screenAt(caret_global) or self.editor.screen()
        screen_area = screen.availableGeometry() if screen else None
        gap = 12

        # Show several choices, but do not cover the CURRENT line. Shrink the
        # list on short windows rather than allowing it to overlap the caret.
        rows = min(self.completion_model.rowCount(), 5)
        row_height = max(22, popup.sizeHintForRow(0))
        top_edge = max(viewport_global.y(), screen_area.top() if screen_area else viewport_global.y())
        bottom_edge = min(viewport_global.y() + viewport.height(),
                          screen_area.bottom() if screen_area else viewport_global.y() + viewport.height())
        space_above = max(0, caret_global.y() - gap - top_edge)
        space_below = max(0, bottom_edge - (caret_global.y() + caret.height() + gap))
        use_above = True
        available = space_above
        if available < row_height + 8:
            popup.hide()
            return
        height = min(rows * row_height + 8, available, 165)
        width = min(420, viewport.width() - 12)
        popup.resize(max(160, width), height)
        if use_above:
            y = caret_global.y() - gap - popup.height()
        else:
            y = caret_global.y() + caret.height() + gap
        x = max(viewport_global.x(),
                min(caret_global.x(), viewport_global.x() + viewport.width() - popup.width()))
        popup.move(x, y)

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
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke-test":
        from smoke_test import run
        run(sys.argv[2])
        sys.exit(0)
    app=QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w=MainWindow(); w.show()
    sys.exit(app.exec())
