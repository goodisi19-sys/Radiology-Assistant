import unittest
from report_format import format_line, format_report

class ReportFormatTests(unittest.TestCase):
    def test_lowercase_and_final_period(self):
        self.assertEqual(format_line("признаки артроза"), "Признаки артроза.")
    def test_multi_sentence(self):
        self.assertEqual(format_line("сигнал сохранен. контуры ровные"), "Сигнал сохранен. Контуры ровные.")
    def test_decimal_and_spine_levels(self):
        self.assertEqual(format_line("- протрузия L4-L5 до 3.5 мм;"), "- Протрузия L4-L5 до 3.5 мм.")
    def test_preserve_heading(self):
        self.assertEqual(format_line("Заключение:"), "Заключение:")
    def test_preserve_exclamations(self):
        self.assertEqual(format_line("норма!"), "Норма!")
    def test_blank_lines(self):
        self.assertEqual(format_report("описание\n\nзаключение"), "Описание.\n\nЗаключение.")
    def test_abbreviation(self):
        self.assertEqual(format_line("измерено в мм. без изменений"), "Измерено в мм. без изменений.")
    def test_compound_abbreviations(self):
        self.assertEqual(format_line("изменений и т.д. не выявлено"), "Изменений и т.д. не выявлено.")
    def test_numeric_measurement_preserves_unit(self):
        self.assertEqual(format_line("3.5 мм без динамики"), "3.5 мм без динамики.")
    def test_indentation(self):
        self.assertEqual(format_line("  - норма; "), "  - Норма. ")

if __name__ == "__main__":
    unittest.main()
