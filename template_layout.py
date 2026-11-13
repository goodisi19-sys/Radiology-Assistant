"""Recover document paragraphs without interpreting or rewriting clinical text."""
import re
import xml.etree.ElementTree as ET

ABBREVIATIONS = {"мм", "см", "мл", "мг", "г", "т", "им", "др", "рис", "стр", "т.д", "т.п", "т.е", "т.к", "т.н", "в.т.ч", "ст", "арт", "макс", "мин", "зав"}


def ends_sentence(text):
    value = text.rstrip()
    if value.endswith(('!', '?')): return True
    if not value.endswith('.'): return False
    token = re.search(r'([\w.]+)\.$', value)
    if token and token.group(1).casefold() in ABBREVIATIONS: return False
    return True


TEXT_NS = 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'
TOKENS = re.compile(r'[\w]+(?:[.,]\d+)?', re.UNICODE)
BULLET = re.compile(r'^\s*(?:[-–—•*]|\d+[.)]\s)')
HEADING = re.compile(r'^\s*(?:Описание|Заключение|Рекомендации|Методика|Врач)\s*:?\s*$', re.I)


def inline_breaks(text):
    """A Word/ODT manual line break is not automatically a sentence boundary."""
    parts = re.split('[\u2028\v]', text)
    result = parts[0]
    for following in parts[1:]:
        # Preserve a deliberate break after a sentence/heading; continue a phrase.
        separator = '\n' if ends_sentence(result) or result.rstrip().endswith((';', ':')) or HEADING.match(following) else ' '
        result = result.rstrip() + separator + following.lstrip()
    return result


def docbook_text(xml):
    root = ET.fromstring(xml)
    lines = []
    def visit(node, parent=""):
        tag = node.tag.rsplit('}', 1)[-1]
        if tag == 'bookinfo' or (tag == 'title' and parent in ('book', 'chapter', 'bookinfo')): return
        if tag in ('para', 'title', 'literallayout'):
            text = re.sub(r'\s+', ' ', ''.join(node.itertext())).strip()
            if tag != 'title' or text: lines.append(text)
            return
        if tag == 'row':
            lines.append('\t'.join(re.sub(r'\s+', ' ', ''.join(cell.itertext())).strip() for cell in node))
            return
        for child in node: visit(child, tag)
    visit(root)
    return '\n'.join(lines).strip()


def odt_paragraphs(root):
    def text(node):
        result = node.text or ''
        for child in node:
            tag = child.tag
            if tag == '{' + TEXT_NS + '}s': result += ' ' * int(child.get('{' + TEXT_NS + '}c', '1'))
            elif tag == '{' + TEXT_NS + '}tab': result += '\t'
            elif tag == '{' + TEXT_NS + '}line-break': result += '\u2028'
            else: result += text(child)
            result += child.tail or ''
        return result
    return '\n'.join(inline_breaks(text(node).strip()) for node in root.iter()
                     if node.tag in ('{' + TEXT_NS + '}p', '{' + TEXT_NS + '}h')).strip()


class ParagraphEvidence:
    """Join an old boundary only when surrounding words occur in a source paragraph.

    No language-model guess, no arbitrary lower-case-line merging, no changes
    to letters, numbers, punctuation, blank paragraphs, or list item boundaries.
    """
    def __init__(self, documents):
        self.phrases = {size: set() for size in range(4, 9)}
        for document in documents:
            for paragraph in document.split('\n'):
                words = [m.group().casefold() for m in TOKENS.finditer(paragraph)]
                for size, index in self.phrases.items():
                    index.update(tuple(words[i:i + size]) for i in range(len(words) - size + 1))

    def boundary_confirmed(self, left, right):
        if not left.strip() or not right.strip() or ends_sentence(left) or left.rstrip().endswith((';', ':')): return False
        if BULLET.match(right) or HEADING.match(left) or HEADING.match(right): return False
        before = [m.group().casefold() for m in TOKENS.finditer(left)][-4:]
        after = [m.group().casefold() for m in TOKENS.finditer(right)][:4]
        size = len(before) + len(after)
        return 4 <= size <= 8 and tuple(before + after) in self.phrases[size]

    def unwrap(self, text):
        lines = text.split('\n')
        output = []
        joined = 0
        for line in lines:
            if output and self.boundary_confirmed(output[-1], line):
                output[-1] = output[-1].rstrip() + ' ' + line.lstrip()
                joined += 1
            else: output.append(line)
        return '\n'.join(output), joined
