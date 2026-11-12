import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import expert_assistant as expert


class ExpertTests(unittest.TestCase):
    def test_protected_medical_values(self):
        self.assertFalse(expert.review_issues('Очаг 3.5 мм, T2 FLAIR.', 'На T2 FLAIR очаг 3.5 мм.'))
        for changed in ['Очаг 4.5 мм, T2 FLAIR.', 'Очаг 3.5 мм, T1 FLAIR.', 'Очаг 3.5 мм, T2 DWI.', 'Очаг 3.5 см, T2 FLAIR.']:
            self.assertTrue(expert.review_issues('Очаг 3.5 мм, T2 FLAIR.', changed))
        self.assertTrue(expert.review_issues('Очаг слева.', 'Очаг справа.'))
        self.assertTrue(expert.review_issues('Гипоинтенсивный на Т1ВИ.', 'Гиперинтенсивный на Т1ВИ.'))
    def test_missing_local_engine(self):
        with self.assertRaisesRegex(ValueError, 'llama-server'):
            expert.generate_variant('/no/server', '/no/model.gguf', 'Текст')
    def test_local_request_and_process_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, model = Path(tmp)/'llama-server.exe', Path(tmp)/'model.gguf'
            server.touch(); model.touch()
            process = Mock(); process.poll.return_value = None
            health = Mock(); health.status = 200
            context = Mock(); context.__enter__ = Mock(return_value=health); context.__exit__ = Mock(return_value=False)
            opener = Mock(); opener.open.side_effect = [context, io.BytesIO(json.dumps({'choices':[{'message':{'content':'Новый вариант.'}, 'finish_reason':'stop'}]}).encode())]
            with patch.object(expert.subprocess, 'Popen', return_value=process) as popen, patch.object(expert.urllib.request, 'build_opener', return_value=opener):
                self.assertEqual(expert.generate_variant(server, model, 'Исходник.'), 'Новый вариант.')
            args = popen.call_args.args[0]
            self.assertIn('127.0.0.1', args)
            self.assertIn('0', args[args.index('-ngl')+1])
            request = opener.open.call_args.args[0]
            self.assertTrue(request.full_url.startswith('http://127.0.0.1:'))
            process.terminate.assert_called_once()
            process.wait.assert_called_once()
