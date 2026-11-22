import unittest
from report_format import format_line, format_report

class ReportFormatTests(unittest.TestCase):
    def test_dimension_separator_and_method_unchanged(self):
        self.assertEqual(format_line('Размеры 30 × 21 х 36 мм'), 'Размеры 30x21x36 мм.')
        method='На серии МР томограмм T1W, T2W без контраста:'
        self.assertEqual(format_line(method),method)
    def test_lowercase_and_final_period(self):
        self.assertEqual(format_line("признаки артроза"), "Признаки артроза.")
    def test_multi_sentence(self):
        self.assertEqual(format_line("сигнал сохранен. контуры ровные"), "Сигнал сохранен. Контуры ровные.")
    def test_decimal_and_spine_levels(self):
        self.assertEqual(format_line("- протрузия L4-L5 до 3.5 мм;"), "Протрузия L4-L5 до 3.5 мм.")
    def test_preserve_heading(self):
        self.assertEqual(format_line("Заключение:"), "Заключение:")
    def test_preserve_exclamations(self):
        self.assertEqual(format_line("норма!"), "Норма.")
    def test_blank_lines(self):
        self.assertEqual(format_report("описание\n\nзаключение"), "Описание.\n\nЗаключение.")
    def test_abbreviation(self):
        self.assertEqual(format_line("измерено в мм. без изменений"), "Измерено в мм. без изменений.")
    def test_compound_abbreviations(self):
        self.assertEqual(format_line("изменений и т.д. не выявлено"), "Изменений и т.д. не выявлено.")
    def test_numeric_measurement_preserves_unit(self):
        self.assertEqual(format_line("3.5 мм без динамики"), "3.5 мм без динамики.")
    def test_semicolon_clauses_are_preserved(self):
        self.assertEqual(format_line('- контуры ровные; структура однородная;'), 'Контуры ровные; структура однородная.')
    def test_dash_without_space_and_numbered_item(self):
        self.assertEqual(format_line('—мениски сохранены;'), 'Мениски сохранены.')
        self.assertEqual(format_line('- 1. сигнал сохранён;'), '1. Сигнал сохранён.')
    def test_numeric_minus_and_b_value(self):
        self.assertEqual(format_line('-3.5 мм;'), '-3.5 мм.')
        self.assertEqual(format_line('b=1000; сигнал сохранён;'), 'b=1000; сигнал сохранён.')
    def test_idempotent_and_line_endings(self):
        source = '- сигнал T2 сохранён; размеры 3,5 мм;\r\n\r\n—контуры ровные;'
        result = format_report(source)
        self.assertEqual(result, 'Сигнал T2 сохранён; размеры 3,5 мм.\r\n\r\nКонтуры ровные.')
        self.assertEqual(format_report(result), result)

    def test_diagnostic_uncertainty_is_not_removed(self):
        self.assertEqual(format_line('- гемангиома?'), 'Гемангиома?')

    def test_indentation(self):
        self.assertEqual(format_line("  - норма; "), "  Норма. ")

if __name__ == "__main__":
    unittest.main()
