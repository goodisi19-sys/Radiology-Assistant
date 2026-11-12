"""Conservative MRI report punctuation and sentence-case formatting."""
import re

# Abbreviations whose trailing full stop is not a sentence boundary.
ABBREVIATIONS = {"мм", "см", "мл", "мг", "г", "т", "им", "др", "рис", "стр", "т.д", "т.п"}

def format_line(line: str) -> str:
    if not line.strip():
        return line
    left = len(line) - len(line.lstrip(" \t"))
    right = len(line.rstrip(" \t"))
    prefix, body, suffix = line[:left], line[left:right], line[right:]
    # Keep indentation, bullet characters, and numbering unchanged.
    lead = re.match(r"((?:(?:[-–—•*]|\d+[.)])\s+)*)", body).group(1)
    content = body[len(lead):]
    if not content:
        return line
    chars = list(content)
    start = True
    for i, ch in enumerate(chars):
        if start and ch.isalpha():
            chars[i] = ch.upper()
            start = False
        if ch in ".!?":
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
    if content.endswith(";"):
        content = content[:-1].rstrip() + "."
    elif not content.endswith((".", "!", "?", ":")):
        content += "."
    return prefix + lead + content + suffix

def format_report(text: str) -> str:
    return "".join(format_line(part.rstrip("\r\n")) + part[len(part.rstrip("\r\n")):]
                   for part in text.splitlines(keepends=True))
