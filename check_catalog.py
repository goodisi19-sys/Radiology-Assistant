"""Check source catalog and Windows build prerequisites before packaging."""
from pathlib import Path
from io import BytesIO
import ast, base64, brotli, hashlib, json, re, zipfile
import xml.etree.ElementTree as ET

ast.parse(Path("app.py").read_text(encoding="utf-8"))
core = json.loads(brotli.decompress(base64.b64decode(Path("protocols.json.br.b64").read_text(encoding="ascii"))))
assert len(core) >= 145, f"Unexpected built-in catalog size: {len(core)}"
quick = json.loads(Path("quick_lines.json").read_text(encoding="utf-8"))
assert len(quick["lines"]) >= 20, "Missing quick insert phrases"
extra = json.loads(Path("protocols_extra.json").read_text(encoding="utf-8"))
namespace = {"text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0"}
digests = set()
sources = 0
duplicates = 0
invalid = []
for path in sorted(Path(".").glob("drive_odt_*.json")):
    entries=json.loads(path.read_text(encoding="utf-8"))
    for item in entries:
        sources+=1
        if "мибс" in item["folder"].casefold() or "2006" in item["folder"].casefold():
            invalid.append(f"{path}: excluded source {item['folder']}")
            continue
        try:
            with zipfile.ZipFile(BytesIO(base64.b64decode(item["b64"]))) as doc:
                xml=ET.fromstring(doc.read("content.xml"))
            lines=["".join(p.itertext()).strip() for p in xml.findall(".//text:p",namespace)]
            body="\\n".join(x for x in lines if x)
            if len(body.strip()) < 35:
                invalid.append(f"{path}: empty protocol {item['title']}")
            digest=hashlib.sha256(re.sub(r"\\s+"," ",body).strip().encode("utf-8")).hexdigest()
            if digest in digests: duplicates+=1
            digests.add(digest)
        except Exception as exc:
            invalid.append(f"{path}: {item['title']}: {exc}")
assert sources >= 150, f"Expected imported Drive records, found {sources}"
if invalid:
    raise RuntimeError("Invalid source records:\\n" + "\\n".join(invalid[:30]))
print(f"Core: {len(core)}, Drive ODT records: {sources}, distinct ODT texts: {len(digests)}, exact duplicates: {duplicates}, additional text protocols: {len(extra)}, quick lines: {len(quick['lines'])}")
