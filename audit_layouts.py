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
                legacy = next(record for record in lib._layout_sources if record['source'] == source and record['title'] == title)
                assert words(original) == words(legacy['legacy_body']), key
                assert not words(original) - words(displayed), key
                assert displayed == lib.complete_originals[source.removeprefix('Google Drive: ')]['content'], key
            if kind == 'base-restored':
                assert displayed == lib.complete_originals[audit[key]['recovered_from']]['content'], key
            records.append(dict(audit[key], title=title, category=category,
                                original_lines=len(original.splitlines()), displayed_paragraphs=len(displayed.splitlines()),
                                first_paragraph=next((line for line in displayed.splitlines() if line.strip()), '')))
        after = [(key, hashlib.sha256(content.encode()).hexdigest()) for key, content in lib.db.execute('SELECT id,content FROM templates ORDER BY id')]
        assert before == after
        target = lib.db.execute("SELECT id FROM templates WHERE source='Google Drive: 1p6-C-2cJcZoFxBoHBaaXKx6H__yXWKcG'").fetchone()[0]
        fixed = format_report(lib.get_template(target)[1])
        for fragment in ('обычной формы', 'клинико-лабораторными данными', 'предшествующих МР или РКТ'):
            assert fragment in fixed
        for title in ('Колено норма МЕГИ', 'Плечев суст норма МЕГИ'):
            for key, in lib.db.execute('SELECT id FROM templates WHERE title=?', (title,)):
                text = format_report(lib.get_template(key)[1])
                first = text.splitlines()[0]
                assert first.startswith('На серии') and first.endswith(':') and 'Т1W' in first, key
                assert 'хрящи  не.' not in text and 'суставе  не.' not in text, key
        report = {'protocols': len(rows), 'audited': len(audit),
                  'changed_layouts': sum(row['changed'] for row in records),
                  'confirmed_base_wraps_joined': sum(row['joined_boundaries'] for row in records),
                  'restored_base_protocols': sum(row['kind'] == 'base-restored' for row in records),
                  'needs_source_review': sum(row['needs_source_review'] for row in records),
                  'kinds': dict(Counter(row['kind'] for row in records)), 'original_records_unchanged': True,
                  'records': records}
        Path('layout-audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({key: value for key, value in report.items() if key != 'records'}, ensure_ascii=True))
    finally: lib.db.close()
