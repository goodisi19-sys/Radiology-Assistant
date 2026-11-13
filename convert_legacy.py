"""Convert original DOCs on Linux, retaining raw identity and complete source text."""
from pathlib import Path
from tempfile import TemporaryDirectory
from collections import Counter
import base64, hashlib, json, re, subprocess
from template_layout import docbook_text
from source_documents import read_word_source

protocols, errors, sources = [], [], []
seen = set()
records = []
for path in sorted(Path('.').glob('drive_doc_*.json')):
    raw = path.read_text(encoding='utf-8').strip()
    if not raw:
        print(f'WARN {path}: empty DOC source batch; no templates available')
        continue
    batch = json.loads(raw)
    if not isinstance(batch, list): raise RuntimeError(f'Invalid DOC batch {path}')
    records.extend(rec for rec in batch if not any(k in (rec['folder']+'/'+rec['title']).casefold() for k in ('мибс', '2006')))

with TemporaryDirectory() as tmp:
    folder = Path(tmp)
    original, converted = folder/'original', folder/'converted'
    original.mkdir(); converted.mkdir()
    unique = {rec['id']: rec for rec in records}
    for key, rec in unique.items(): (original/(key+'.doc')).write_bytes(base64.b64decode(rec['b64']))
    result = subprocess.run(['soffice', '-env:UserInstallation='+ (folder/'profile').as_uri(), '--headless',
        '--convert-to', 'docx', '--outdir', str(converted)] + [str(path) for path in sorted(original.glob('*.doc'))],
        text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=300)
    if result.returncode: raise RuntimeError('LibreOffice source conversion failed: '+result.stderr[-2000:])
    complete = {}
    for key, rec in unique.items():
        path = converted/(key+'.docx')
        if not path.exists(): raise RuntimeError('Complete original DOC could not be read: '+rec['title'])
        data = read_word_source(path)
        if len(data['content']) < 35: raise RuntimeError('Empty complete DOC: '+rec['title'])
        complete[key] = data
        sources.append({'source_id': key, 'title': rec['title'], 'folder': rec['folder'],
                        'binary_sha256': hashlib.sha256(base64.b64decode(rec['b64'])).hexdigest(), **data})
    for rec in records:
        target = original/(rec['id']+'.doc')
        result = subprocess.run(['antiword', '-m', 'UTF-8.txt', str(target)],
            text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=30)
        content = re.sub(r'\r\n?', '\n', result.stdout.strip())
        if len(content) < 35:
            errors.append(rec['title']+': empty or unconvertible by legacy reader')
            continue
        structured = subprocess.run(['antiword', '-x', 'db', str(target)],
            text=True, encoding='utf-8', capture_output=True, timeout=30)
        body_layout = docbook_text(structured.stdout)
        words = lambda value: Counter(re.findall(r'[^\W\d_]+', value.casefold()))
        if words(content) != words(body_layout): raise RuntimeError('Legacy paragraph extraction changed words: '+rec['title'])
        # The complete reader may recover headers/text boxes, but must not lose body words.
        if words(content) - words(complete[rec['id']]['content']):
            raise RuntimeError('Complete extraction lost original body words: '+rec['title'])
        key = re.sub(r'\s+', ' ', content).strip()
        if key in seen: continue
        seen.add(key)
        protocols.append({'title': Path(rec['title']).stem, 'folder': rec['folder'], 'source_id': rec['id'],
            'content': content, 'body_layout': body_layout, 'layout_content': complete[rec['id']]['content'],
            'layout_source': 'original-doc-complete-v2'})

assert len(protocols) == 128, f'Expected 128 legacy protocols; got {len(protocols)}'
assert len(errors) == 7, f'Legacy conversion failures changed: {errors}'
assert len(sources) == 180, f'Expected 180 complete original DOC sources; got {len(sources)}'
Path('protocols_legacy.json').write_text(json.dumps(protocols, ensure_ascii=False), encoding='utf-8')
Path('protocol_sources.json').write_text(json.dumps(sources, ensure_ascii=False), encoding='utf-8')
print(f'Converted legacy DOC protocols: {len(protocols)}; legacy skipped: {len(errors)}; complete source documents: {len(sources)}')
for error in errors: print('WARN', error)
