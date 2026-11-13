import unittest
from shorthand import expand_note

class ShorthandTests(unittest.TestCase):
    def test_complete_note(self):
        text,_=expand_note('зад цент прот L5-S1 до 4 мм с лок деформ дура мешка')
        self.assertEqual(expand_note('зад цент прот l5-s1 до 4 мм слок деформ дура мешка')[0],text)
        self.assertEqual(text,'Задняя центральная протрузия диска L5–S1 до 4 мм, с локальной деформацией дурального мешка.')
    def test_no_new_finding_and_decimal_preserved(self):
        self.assertEqual(expand_note('зад цент грыжа c5-c6 до 3,5 мм')[0],'Задняя центральная грыжа диска C5–C6 до 3,5 мм.')
    def test_ambiguity_and_unknown_qualifiers_are_not_dropped(self):
        for text in ['зад цент прот ь5-с1 дл 4 мм слок деформ дура мешка','зад цент прот l5-s1 до 4 мм не деформирует мешок',
                     'зад цент прот l5-s1 до 4 мм слева','зад цент прот l5-s2 до 4 мм','зад цент прот l5-s1 до мм','']:
            self.assertIsNone(expand_note(text)[0],text)
    def test_personal_mapping_takes_priority(self):
        self.assertEqual(expand_note(' Моя   запись ',{'моя запись':'Проверенный вариант.'})[0],'Проверенный вариант.')
