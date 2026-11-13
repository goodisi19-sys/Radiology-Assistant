import sqlite3,tempfile,unittest
from pathlib import Path
from adaptive_completion import AdaptiveMemory

SAMPLE='Задняя центральная грыжа диска L5-S1 до 4 мм, с локальной деформацией дурального мешка, сужением латеральных карманов и межпозвонковых отверстий.'
QUERY='Грыжа диска L4-L5 до 5 мм '

class AdaptiveTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.memory=AdaptiveMemory(self.db)
    def tearDown(self):self.db.close()
    def test_learning_and_safe_continuation_for_new_measurements(self):
        self.assertGreater(self.memory.learn(SAMPLE),0)
        options=self.memory.suggest(QUERY)
        self.assertTrue(options)
        self.assertIn('деформацией дурального мешка',options[0]['text'])
        self.assertNotRegex(options[0]['text'],r'\d|L5|S1')
        self.assertFalse(self.memory.suggest('Грыж'))
    def test_same_saved_document_does_not_inflate_frequency(self):
        self.memory.learn(SAMPLE)
        before=self.db.execute('SELECT sum(uses) FROM adaptive_continuations').fetchone()[0]
        self.assertEqual(self.memory.learn(SAMPLE),0)
        self.assertEqual(self.db.execute('SELECT sum(uses) FROM adaptive_continuations').fetchone()[0],before)
    def test_personal_standard_priority(self):
        self.memory.learn(SAMPLE)
        self.db.execute('UPDATE adaptive_continuations SET uses=1000');self.db.commit()
        self.memory.learn('Грыжа диска L5-S1 до 3 мм, с умеренной деформацией дурального мешка.',verified=True)
        result=self.memory.suggest(QUERY)[0]
        self.assertTrue(result['verified']);self.assertIn('умеренной',result['text'])
    def test_metadata_conclusion_and_unfinished_templates_not_learned(self):
        for text in ['Пациент Иванов: '+SAMPLE,'Описание:\nЗаключение: '+SAMPLE,
                     SAMPLE.replace('4 мм','___ мм'),SAMPLE.replace('4 мм','[уточнить размер]')]:
            self.assertEqual(self.memory.learn(text),0,text)
    def test_no_old_values_or_side_in_continuation(self):
        self.memory.learn('Грыжа диска L5-S1, с деформацией дурального мешка справа до 3 мм.')
        for option in self.memory.suggest('Грыжа диска '):
            self.assertNotRegex(option['text'],r'\d|справа')
    def test_negative_and_other_region_not_matched(self):
        self.memory.learn(SAMPLE)
        self.assertFalse(self.memory.suggest('Грыжа диска C5-C6 до 5 мм '))
        for query in ('Грыжа не выявлена ','Грыж нет ','Грыжи отсутствуют '):
            self.assertFalse(self.memory.suggest(query))
    def test_general_sentence_continuation(self):
        self.memory.learn('Суставные поверхности конгруэнтны, хрящевые поверхности ровные и четкие.')
        self.assertTrue(any(x['text'].startswith('конгруэнтны') for x in self.memory.suggest('Суставные поверхности ')))
    def test_clear_preserves_verified(self):
        self.memory.learn(SAMPLE)
        self.memory.learn(SAMPLE,verified=True)
        self.memory.clear_saved()
        self.assertTrue(self.memory.suggest(QUERY))
        self.assertTrue(all(x['verified'] for x in self.memory.suggest(QUERY)))
    def test_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'memory.sqlite'
            db=sqlite3.connect(path);AdaptiveMemory(db).learn(SAMPLE);db.close()
            db=sqlite3.connect(path)
            try:self.assertTrue(AdaptiveMemory(db).suggest(QUERY))
            finally:db.close()
