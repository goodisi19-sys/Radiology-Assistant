"""Conservative MRI report punctuation and sentence-case formatting."""
import re

# Abbreviations whose trailing full stop is not a sentence boundary.
ABBREVIATIONS = {"мм", "см", "мл", "мг", "г", "т", "им", "др", "рис", "стр", "т.д", "т.п", "т.е", "т.к", "т.н", "в.т.ч", "ст", "арт", "макс", "мин"}

def format_line(line: str) -> str:
    if not line.strip():
        return line
    left = len(line) - len(line.lstrip(" \t"))
    right = len(line.rstrip(" \t"))
    prefix, body, suffix = line[:left], line[left:right], line[right:]
    # Remove list dashes, but retain minus signs in numeric measurements.
    body = re.sub(r'^(?:(?:[-–—•*]+[ \t]+)|(?:[–—•*]+(?=[А-Яа-яЁёA-Za-z(«]))|(?:-(?=[А-Яа-яЁёA-Za-z])))+', '', body)
    lead = re.match(r"((?:\d+[.)]\s+)*)", body).group(1)
    content = body[len(lead):]
    if not content:
        return line
    protected = set()
    for match in re.finditer(r"(?<!\w)(?:[А-Яа-яA-Za-z]\.\s*){2,}|\b[А-ЯA-Z]\.(?=\s*[А-ЯA-Z]\.)", content):
        protected.update(range(match.start(), match.end()))
    for match in re.finditer(r'\b[bpr]\s*=\s*\d+(?:[.,]\d+)?', content, re.I):
        protected.update(range(match.start(), match.end()))
    chars = list(content)
    start = True
    for i, ch in enumerate(chars):
        if start and ch.isdigit():
            start = False  # A numeric measurement must not capitalize its unit.
        if start and ch.isalpha():
            if i not in protected: chars[i] = ch.upper()
            start = False
        if ch in ".!?":
            if i in protected: continue
            # A decimal point and a dot in an abbreviation are not sentence stops.
            if ch == "." and i and i + 1 < len(chars) and chars[i-1].isdigit() and chars[i+1].isdigit():
                continue
            before = "".join(chars[:i]).rstrip()
            token = re.search(r"([\w.]+)$", before)
            if ch == "." and token and token.group(1).casefold() in ABBREVIATIONS:
                continue
            # Only a punctuation followed by a space can start another sentence.
            if i+1 < len(chars) and chars[i+1].isspace():
                start = True
    content = "".join(chars)
    # Preserve template headings and all internal semicolons. Only the end of
    # a prose line receives a full stop; no clause is rewritten or reordered.
    heading = content.endswith(':') and len(content) <= 100 and ';' not in content
    # A terminal question mark can encode diagnostic uncertainty.
    if not heading and not content.endswith('?'):
        content = content.rstrip(';,!?:').rstrip()
        if content and not content.endswith('.'): content += '.'
    return prefix + lead + content + suffix

def format_report(text: str) -> str:
    return "".join(format_line(part.rstrip("\r\n")) + part[len(part.rstrip("\r\n")):]
                   for part in text.splitlines(keepends=True))
