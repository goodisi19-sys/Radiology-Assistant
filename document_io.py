"""Atomic document writes; preserve text and character formatting without rewriting it."""
import os
import tempfile
from pathlib import Path
from docx import Document
from docx.shared import Pt
from PySide6.QtGui import QFont


def _atomic(path, writer):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, suffix='.tmp', dir=path.parent)
    os.close(fd)
    try:
        writer(temporary)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def atomic_write_text(path, text):
    _atomic(path, lambda temporary: Path(temporary).write_text(text, encoding='utf-8'))


def write_docx(path, document):
    doc = Document()
    style = doc.styles['Normal']
    style.font.name = 'Times New Roman'
    style.font.size = Pt(12)
    block = document.firstBlock()
    while block.isValid():
        paragraph = doc.add_paragraph()
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid():
                run = paragraph.add_run(fragment.text().replace('\u2028', '\n'))
                fmt = fragment.charFormat()
                run.bold = fmt.fontWeight() >= QFont.Weight.Bold
                run.italic = fmt.fontItalic()
                run.underline = fmt.fontUnderline()
                run.font.name = fmt.font().family() or 'Times New Roman'
                run.font.size = Pt(fmt.fontPointSize() or 12)
            iterator += 1
        block = block.next()
    _atomic(path, doc.save)


def read_docx(path):
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    parts = []
    for item in Document(path).iter_inner_content():
        if isinstance(item, Paragraph): parts.append(item.text.replace('\n', '\u2028'))
        elif isinstance(item, Table):
            parts.extend('\t'.join(cell.text for cell in row.cells) for row in item.rows)
    return '\n'.join(parts)
