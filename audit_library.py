"""Build gate: verify that MRI reports are actually loaded into fresh SQLite."""
import json
import tempfile
from collections import Counter
from pathlib import Path

import app

with tempfile.TemporaryDirectory(prefix="radiology-catalog-audit-") as tmp:
    app.app_data_dir = lambda: Path(tmp)
    library = None
    try:
        library = app.PhraseLibrary()
        rows = library.db.execute(
            "SELECT t.title,t.category,t.source,COALESCE(f.folder_path,'') "
            "FROM templates t LEFT JOIN template_folders f ON t.id=f.template_id"
        ).fetchall()
        count = len(rows)
        sources = Counter(
            "base" if source == "Встроенная библиотека МРТ"
            else "drive" if source.startswith("Google Drive:")
            else "other" for _, _, source, _ in rows
        )
        categories = Counter(category for _, category, _, _ in rows)
        print("ACTUAL SQLite protocols:", count, flush=True)
        print("Loaded sources:", json.dumps(dict(sources), ensure_ascii=True), flush=True)
        # Escape Cyrillic labels so Windows cp1252 consoles cannot crash the audit.
        print("Anatomical categories:", json.dumps(dict(categories), ensure_ascii=True), flush=True)
        print("Stored source-folder paths:", sum(bool(folder) for *_, folder in rows), flush=True)
        assert sources["base"] >= 145, "Built-in MRI catalogue was not loaded"
        assert sources["drive"] >= 100, (
            "Additional ODT/DOC MRI protocols were not loaded into SQLite; "
            f"only {sources['drive']} imported"
        )
        assert count >= 245, f"Only {count} protocols in the actual SQLite library"
        expected = {"ГМ", "ОМТ", "Позвоночник", "Суставы"}
        missing = expected.difference(categories)
        assert not missing, "Missing anatomical categories: " + json.dumps(
            sorted(missing), ensure_ascii=True
        )
        assert any(folder for _, _, source, folder in rows if source.startswith("Google Drive:")), (
            "Drive source folders were not preserved"
        )
    finally:
        if library is not None:
            library.db.close()

print("PASS: MRI catalogue loaded and categorized in a fresh database")
