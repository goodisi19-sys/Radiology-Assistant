import unittest
from spell_check import find_typos, suggest, qt_offset


class SpellCheckTests(unittest.TestCase):
    def test_typo_and_correct_russian_inflections(self):
        text = 'Контуры ровные; размеры сохранены. Контруы ровные.'
        issues = find_typos(text)
        self.assertEqual([issue.word for issue in issues], ['Контруы'])
        self.assertEqual(text[issues[0].start:issues[0].end], 'Контруы')
        self.assertIn('Контуры', suggest('Контруы'))
        self.assertEqual([issue.word for issue in find_typos('КОНТРУЫ')], ['КОНТРУЫ'])
    def test_medical_terms_units_and_sequences(self):
        self.assertFalse(find_typos('Гиперинтенсивный сигнал. Протрузия L4-L5 до 3.5 мм. МРТ T2 FLAIR ADC b=1000.'))
    def test_personal_words_and_unicode_offsets(self):
        text = '🩺 Нейротерминтест.\nКонтруы ровные.'
        issues = find_typos(text, ['нейротерминтест'])
        self.assertEqual([issue.word for issue in issues], ['Контруы'])
        self.assertEqual(issues[0].line, 2)
        self.assertEqual(qt_offset(text, issues[0].start), issues[0].start + 1)

if __name__ == '__main__': unittest.main()
