import unittest
from template_layout import ParagraphEvidence, docbook_text, odt_paragraphs, inline_breaks
from report_format import format_report, format_line
import xml.etree.ElementTree as ET


class LayoutTests(unittest.TestCase):
    def test_docbook_paragraphs_and_table_rows(self):
        source = '<book><bookinfo><date>2001</date></bookinfo><chapter><title>Metadata not body text</title><para>Обычной формы,\n с ровными контурами.</para><para/><para>Заключение: без изменений.</para><informaltable><row><entry>Размер</entry><entry>3.5 мм</entry></row></informaltable></chapter></book>'
        self.assertEqual(docbook_text(source), 'Обычной формы, с ровными контурами.\n\nЗаключение: без изменений.\nРазмер\t3.5 мм')
    def test_source_confirmed_wrap_does_not_add_period(self):
        full = 'Передние мозговые артерии обычной формы, с чёткими, ровными контурами.'
        old = 'Передние мозговые артерии обычной\nформы, с чёткими,\nровными контурами.'
        restored, count = ParagraphEvidence([full]).unwrap(old)
        self.assertEqual(restored, full)
        self.assertEqual(count, 2)
        self.assertNotIn('обычной.', format_report(restored))
    def test_no_guessing_or_joining_real_list_and_blank_paragraphs(self):
        evidence = ParagraphEvidence(['Описание без изменений. Заключение без изменений.'])
        source = 'Печень не увеличена\nКонтуры ровные\n\nЗаключение:\n- без изменений;\n- очагов нет.'
        self.assertEqual(evidence.unwrap(source), (source, 0))
    def test_word_soft_break_continues_phrase(self):
        self.assertEqual(format_report('обычной\u2028формы; контуры ровные;'), 'Обычной формы; контуры ровные.')
        self.assertEqual(format_line('обычной\u2028формы'), 'Обычной формы.')
        self.assertEqual(format_report('в мм.\u2028без изменений'), 'В мм. без изменений.')
        self.assertEqual(inline_breaks('Сигнал сохранён.\u2028Заключение:\u2028Без изменений.'), 'Сигнал сохранён.\nЗаключение:\nБез изменений.')
    def test_odt_space_and_line_break_markers(self):
        root = ET.fromstring('<root xmlns:t="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><t:p>Сигнал<t:s/>сохранён.<t:line-break/>Заключение:<t:line-break/>Без изменений.</t:p></root>')
        self.assertEqual(odt_paragraphs(root), 'Сигнал сохранён.\nЗаключение:\nБез изменений.')
    def test_colon_heading_longer_than_visual_line(self):
        source = 'На МРТ-артериограммах визуализированы магистральные артерии головного мозга и шеи в пределах зоны исследования:'
        self.assertEqual(format_report(source), source)

if __name__ == '__main__': unittest.main()
