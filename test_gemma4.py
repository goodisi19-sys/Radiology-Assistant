import unittest
from gemma4 import discrepancies


class GemmaSafetyTests(unittest.TestCase):
    def test_preserves_limit_and_normalizes_level(self):
        source = 'л4-л5 прот до 4мм'
        self.assertEqual(discrepancies(source, 'Протрузия диска L4-L5 до 4 мм.'), [])
        self.assertTrue(discrepancies(source, 'Протрузия диска L4-L5 4 мм.'))

    def test_changed_level_side_and_unit(self):
        source = 'очаг справа L4-L5 4мм'
        for result in ('Очаг слева L4-L5 4 мм.', 'Очаг справа L5-S1 4 мм.',
                       'Очаг справа L4-L5 4 см.'):
            self.assertTrue(discrepancies(source, result))

    def test_refuses_negation_rewrite_and_contact_escalation(self):
        self.assertTrue(discrepancies('без компр кореш', 'Без компрессии корешков.'))
        self.assertTrue(discrepancies('контакт корешка', 'Компрессия корешка.'))

    def test_detects_findings_and_format(self):
        self.assertTrue(discrepancies('Контуры ровные.', 'Контуры ровные; выпот.'))
        self.assertTrue(discrepancies('Контуры ровные.', 'контуры ровные'))
