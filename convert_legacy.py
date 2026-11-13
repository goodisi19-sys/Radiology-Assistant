"""Convert bundled legacy DOC templates to text during GitHub Actions Linux job."""
from pathlib import Path
from tempfile import TemporaryDirectory
import base64, json, re, subprocess
from template_layout import docbook_text
from collections import Counter

protocols=[]
seen=set()
errors=[]
with TemporaryDirectory() as tmp:
    target=Path(tmp)/"input.doc"
    for path in sorted(Path(".").glob("drive_doc_*.json")):
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            print(f"WARN {path}: empty DOC source batch; no templates available")
            continue
        try:
            records = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid DOC batch {path}: {exc}") from exc
        if not isinstance(records, list):
            raise RuntimeError(f"Invalid DOC batch {path}: expected an array")
        for rec in records:
            if any(k in (rec["folder"]+"/"+rec["title"]).casefold() for k in ("мибс","2006")):
                continue
            try:
                target.write_bytes(base64.b64decode(rec["b64"]))
                result=subprocess.run(["antiword","-m","UTF-8.txt",str(target)],
                    text=True,encoding="utf-8",errors="replace",capture_output=True,timeout=30)
                content=result.stdout.strip()
                if len(content)<35:
                    errors.append(rec["title"]+": empty or unconvertible")
                    continue
                content=re.sub(r"\r\n?", "\n", content)
                structured=subprocess.run(["antiword", "-x", "db", str(target)],
                    text=True, encoding="utf-8", capture_output=True, timeout=30)
                layout=docbook_text(structured.stdout)
                if len(layout) < 35: raise RuntimeError('No paragraph layout in original DOC')
                words=lambda value: Counter(re.findall(r'[^\W\d_]+', value.casefold()))
                if words(content) != words(layout):
                    raise RuntimeError('Paragraph extraction changed words; manual source review required')
                key=re.sub(r"\s+"," ",content).strip()
                if key in seen: continue
                seen.add(key)
                protocols.append({"title":Path(rec["title"]).stem,
                    "folder":rec["folder"],"source_id":rec["id"],"content":content,"layout_content":layout,
                    "layout_source":"original-doc-paragraphs-v1"})
            except Exception as exc:
                errors.append(rec["title"]+": "+str(exc))
Path("protocols_legacy.json").write_text(json.dumps(protocols,ensure_ascii=False),encoding="utf-8")
print(f"Converted legacy DOC protocols: {len(protocols)}; skipped: {len(errors)}")
for error in errors[:20]: print("WARN",error)

# A reduced conversion result must never silently produce a successful release.
assert len(protocols) == 128, f"Expected 128 legacy protocols; got {len(protocols)}"
assert len(errors) == 7, f"Legacy conversion failures changed: {errors}"
