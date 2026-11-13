import io
import unittest
import zipfile
import xml.etree.ElementTree as ET
from source_documents import word_blocks, read_word_source, W, R


class CompleteSourceTests(unittest.TestCase):
    def test_clinical_header_and_footer_are_kept_once(self):
        archive = io.BytesIO()
        document = f'<w:document xmlns:w="{W[1:-1]}" xmlns:r="{R[1:-1]}"><w:body><w:p><w:r><w:t>Контуры ровные.</w:t></w:r></w:p><w:sectPr><w:headerReference r:id="h"/><w:headerReference r:id="h"/><w:footerReference r:id="f"/></w:sectPr></w:body></w:document>'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('word/document.xml', document)
            z.writestr('word/_rels/document.xml.rels', '<Relationships><Relationship Id="h" Target="header1.xml"/><Relationship Id="f" Target="footer1.xml"/></Relationships>')
            z.writestr('word/header1.xml', f'<w:hdr xmlns:w="{W[1:-1]}"><w:p><w:r><w:t>Методика исследования: Т1W и Т2W.</w:t></w:r></w:p></w:hdr>')
            z.writestr('word/footer1.xml', f'<w:ftr xmlns:w="{W[1:-1]}"><w:p><w:r><w:t>Сравнение с предыдущим исследованием.</w:t></w:r></w:p></w:ftr>')
        result = read_word_source(archive)
        self.assertEqual(result['content'], 'Методика исследования: Т1W и Т2W.\n\nКонтуры ровные.\n\nСравнение с предыдущим исследованием.')

    def test_textbox_is_not_dropped_or_repeated(self):
        root = ET.fromstring(f'<w:body xmlns:w="{W[1:-1]}"><w:p><w:r><w:t>Описание:</w:t><w:pict><w:txbxContent><w:p><w:r><w:t>Хрящи не изменены.</w:t></w:r></w:p></w:txbxContent></w:pict></w:r></w:p></w:body>')
        text = word_blocks(root)
        self.assertEqual(text.count('Хрящи не изменены.'), 1)
        self.assertEqual(text, 'Описание:\nХрящи не изменены.')

    def test_page_number_field_is_not_medical_text(self):
        root = ET.fromstring(f'<w:body xmlns:w="{W[1:-1]}"><w:p><w:r><w:t>Размер 12 мм.</w:t></w:r><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> PAGE </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>3</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:body>')
        self.assertEqual(word_blocks(root), 'Размер 12 мм.')
