"""Read report text from original OOXML parts, including clinical headers."""
import re
import zipfile
import xml.etree.ElementTree as ET
from template_layout import inline_breaks

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


def word_blocks(root):
    def paragraph(node):
        fields = []
        def inline(item):
            tag = item.tag
            if tag == W + 'fldChar':
                kind = item.get(W + 'fldCharType')
                if kind == 'begin': fields.append(False)
                elif kind == 'end' and fields: fields.pop()
                return ''
            if tag == W + 'instrText':
                if fields and re.search(r'\b(?:PAGE|NUMPAGES|SECTIONPAGES)\b', item.text or ''): fields[-1] = True
                return ''
            if tag == W + 'fldSimple' and re.search(r'\b(?:PAGE|NUMPAGES|SECTIONPAGES)\b', item.get(W + 'instr', '')): return ''
            if tag == W + 't': return '' if any(fields) else (item.text or '')
            if tag == W + 'tab': return '\t'
            if tag in (W + 'br', W + 'cr'): return '\u2028'
            if tag == W + 'p': return '\n' + paragraph(item) + '\n'
            return ''.join(inline(child) for child in item)
        return ''.join(inline(child) for child in node)
    def visit(node):
        if node.tag == W + 'p': return [inline_breaks(paragraph(node))]
        if node.tag == W + 'tr':
            return ['\t'.join('\n'.join(visit(cell)).strip() for cell in node if cell.tag == W + 'tc')]
        return [line for child in node for line in visit(child)]
    return '\n'.join(visit(root)).strip()


def read_word_source(path):
    """Return body and every referenced header/footer once; no document metadata."""
    with zipfile.ZipFile(path) as archive:
        document = ET.fromstring(archive.read('word/document.xml'))
        relations = ET.fromstring(archive.read('word/_rels/document.xml.rels'))
        targets = {item.get('Id'): item.get('Target') for item in relations if item.get('TargetMode') != 'External'}
        def parts(kind):
            result = []
            for node in document.iter(W + kind + 'Reference'):
                target = targets.get(node.get(R + 'id'), '')
                name = target.lstrip('/') if target.startswith('/') else 'word/' + target
                if name not in archive.namelist(): raise ValueError('Missing Word part: ' + name)
                value = word_blocks(ET.fromstring(archive.read(name))).strip()
                if value and value not in result: result.append(value)
            return result
        headers, footers = parts('header'), parts('footer')
        body = word_blocks(document.find(W + 'body'))
    return {'body': body, 'headers': headers, 'footers': footers,
            'content': '\n\n'.join(headers + [body] + footers).strip()}
