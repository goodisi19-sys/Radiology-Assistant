"""Audit every displayed protocol layout while preserving original SQLite rows."""
import hashlib
import json
import re
import tempfile
from collections import Counter
from pathlib import Path
import app
from report_format import format_report

with tempfile.TemporaryDirectory(prefix='radiology-layout-audit-') as tmp:
    app.app_data_dir = lambda: Path(tmp)
    lib = app.PhraseLibrary()
    try:
        rows = lib.db.execute('SELECT id,title,category,content,source FROM templates ORDER BY id').fetchall()
        before = [(key, hashlib.sha256(content.encode()).hexdigest()) for key, _, _, content, _ in rows]
        records = []
        audit = {record['id']: record for record in lib.layout_audit}
        assert len(rows) == len(audit) == 497
        for key, title, category, original, source in rows:
            displayed = lib.get_template(key)[1]
            formatted = format_report(displayed)
            assert formatted == format_report(formatted), key
            kind = audit[key]['kind']
            if kind == 'base-evidence':
                assert re.sub(r'\s+', ' ', original).strip() == re.sub(r'\s+', ' ', displayed).strip(), key
            if kind == 'doc-original':
                words = lambda text: Counter(re.findall(r'[^\W\d_]+', text.casefold()))
                assert words(original) == words(displayed), key
            records.append(dict(audit[key], title=title, category=category,
                                original_lines=len(original.splitlines()), displayed_paragraphs=len(displayed.splitlines())))
        after = [(key, hashlib.sha256(content.encode()).hexdigest()) for key, content in lib.db.execute('SELECT id,content FROM templates ORDER BY id')]
        assert before == after
        target = lib.db.execute("SELECT id FROM templates WHERE source='Google Drive: 1p6-C-2cJcZoFxBoHBaaXKx6H__yXWKcG'").fetchone()[0]
        fixed = format_report(lib.get_template(target)[1])
        for fragment in ('обычной формы', 'клинико-лабораторными данными', 'предшествующих МР или РКТ'):
            assert fragment in fixed
        report = {'protocols': len(rows), 'audited': len(audit),
                  'changed_layouts': sum(row['changed'] for row in records),
                  'confirmed_base_wraps_joined': sum(row['joined_boundaries'] for row in records),
                  'kinds': dict(Counter(row['kind'] for row in records)), 'original_records_unchanged': True,
                  'records': records}
        Path('layout-audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({key: value for key, value in report.items() if key != 'records'}, ensure_ascii=True))
    finally: lib.db.close()
