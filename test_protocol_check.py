import unittest
from protocol_check import check_protocol

class ProtocolCheckTests(unittest.TestCase):
    def test_unselected_side_forms(self):
        for text in ['правый/левый сустав','правого (левого) коленного сустава','левой / правой почки', 'левого правого коленного сустава', 'правый или левый сустав']:
            self.assertTrue(any('вариант' in x.message for x in check_protocol(text)),text)
    def test_missing_fields(self):
        for text in ['Размер ___ мм','До … мм','12 × … мм','до мм','размерами см','[сторона]','12 х мм', 'Размеры:', '-   ']:
            self.assertTrue(check_protocol(text),text)
    def test_normal_measurements_and_abbreviations(self):
        self.assertFalse(check_protocol('Размер 12 × 8 мм, до 3.5 мм. Т1ВИ, Т2ВИ.'))
    def test_same_organ_opposite_side(self):
        findings=check_protocol('Описание: правого коленного сустава.\nЗаключение: артроз левого коленного сустава.')
        self.assertEqual(len(findings),1); self.assertTrue(findings[0].possible)
        self.assertEqual(len(findings[0].related),2)
    def test_same_side(self):
        self.assertFalse(check_protocol('Правый плечевой сустав.\nЗаключение: правый плечевой сустав.'))
    def test_different_organs(self):
        self.assertFalse(check_protocol('Правый коленный сустав.\nЗаключение: левый плечевой сустав.'))
    def test_bilateral(self):
        for body in ['Правый коленный сустав и левый коленный сустав.', 'Двустороннее исследование. Правый коленный сустав.']:
            self.assertFalse(any(x.possible for x in check_protocol(body+'\nЗаключение: левый коленный сустав.')))
    def test_no_conclusion_no_inference(self):
        self.assertFalse(check_protocol('Правый коленный сустав. Левый коленный сустав.'))
    def test_no_cross_clause_association(self):
        self.assertFalse(check_protocol('Правый. Коленный сустав.\nЗаключение: левый коленный сустав.'))
    def test_alternatives_are_not_used_as_evidence(self):
        results=check_protocol('Правый/левый коленный сустав.\nЗаключение: левый коленный сустав.')
        self.assertFalse(any(x.possible for x in results))
    def test_no_text_modification(self):
        text='Правый коленный сустав.\nЗаключение: левый коленный сустав. Размер ___ мм.'
        for result in check_protocol(text): self.assertTrue(text[result.start:result.end])

    def test_non_heading_does_not_split_description(self):
        self.assertFalse(check_protocol('Правый коленный сустав.\nЗаключением врача отмечен левый коленный сустав.'))
