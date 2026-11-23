import unittest
from slot_phrases import slots_from_source,safe_slot_suffix,SLOT_RE

class SlotTests(unittest.TestCase):
 def test_protected_fields_not_copied(self):
  phrase=slots_from_source(' L4-L5 определяется грыжа справа размерами 12x14x10 мм.','На уровне')
  for slot in ('[уровень]','[находка]','[сторона]','[размер]'):self.assertIn(slot,phrase)
  self.assertTrue(safe_slot_suffix(phrase))
  self.assertNotIn('12x14x10',phrase)
 def test_normal_prose_preserved(self):
  self.assertEqual(slots_from_source(' не смещены.','Срединные структуры'),' не смещены.')
 def test_reject_unknown_template_markers(self):
  for phrase in (' ____ мм.',' ...',' [ФИО]'):self.assertIsNone(slots_from_source(phrase,'На уровне'))
 def test_t2w_untouched_and_values_masked(self):
  phrase=slots_from_source(' в T2W справа 3 очага по 6 мм.','На серии')
  self.assertIn('T2W',phrase)
  for slot in ('[сторона]','[значение]','[находка]','[размер]'):self.assertIn(slot,phrase)
 def test_unfilled_measurement_rejected(self):
  self.assertFalse(safe_slot_suffix(' до мм.'))
