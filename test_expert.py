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
    def test_chat_context_keeps_complete_turns(self):
        history = [{'role': 'user', 'content': 'x' * 9000}, {'role': 'assistant', 'content': 'y' * 9000},
                   {'role': 'user', 'content': 'Короткий вопрос'}, {'role': 'assistant', 'content': 'Ответ'},
                   {'role': 'user', 'content': 'Уточнение'}]
        context = expert.chat_context(history)
        self.assertEqual([item['role'] for item in context], ['system', 'user', 'assistant', 'user'])
        self.assertEqual(context[-1]['content'], 'Уточнение')
        self.assertEqual(len(history), 5)
        with self.assertRaises(ValueError): expert.chat_context([{'role': 'user', 'content': 'x' * 6001}])

    def test_chat_uses_conversation_prompt(self):
        history = [{'role': 'user', 'content': 'Вопрос'}, {'role': 'assistant', 'content': 'Ответ'},
                   {'role': 'user', 'content': 'Уточни'}]
        with patch.object(expert, 'local_completion', return_value='Уточнение') as completion:
            self.assertEqual(expert.generate_chat('server', 'model', history), 'Уточнение')
        messages = completion.call_args.args[2]
        self.assertEqual(messages[0]['content'], expert.CHAT_PROMPT)
        self.assertEqual(messages[1:], history)
        self.assertEqual(completion.call_args.kwargs['max_tokens'], 2048)

    def test_cancelled_request_closes_engine(self):
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            server, model = Path(tmp)/'server', Path(tmp)/'model.gguf'
            server.touch(); model.touch()
            cancelled = threading.Event(); cancelled.set()
            process = Mock(); process.poll.return_value = None
            with patch.object(expert.subprocess, 'Popen', return_value=process):
                with self.assertRaises(InterruptedError):
                    expert.generate_chat(server, model, [{'role': 'user', 'content': 'Вопрос'}], cancelled)
            process.terminate.assert_called()
            process.wait.assert_called()

    def test_rewrite_retries_an_unchanged_response(self):
        with patch.object(expert, 'local_completion', side_effect=['Исходный текст.', 'Переработанный текст.']) as call:
            self.assertEqual(expert.generate_variant('server', 'model', 'Исходный текст.'), 'Переработанный текст.')
        self.assertEqual(call.call_count, 2)
        self.assertIn('без изменений', call.call_args.args[2][1]['content'])

    def test_rewrite_does_not_present_copy_as_success(self):
        with patch.object(expert, 'local_completion', return_value='Исходный  текст.\n') as call:
            with self.assertRaises(expert.UnchangedResponseError):
                expert.generate_variant('server', 'model', 'Исходный текст.')
        self.assertEqual(call.call_count, 2)

    def test_stoller_card_bypasses_model(self):
        from reference_cards import CARD_PREFIX
        with patch.object(expert, 'local_completion', side_effect=AssertionError('Do not generate a known reference')):
            answer = expert.generate_chat('', '', [{'role': 'user', 'content': 'Дай классификацию разрывов менисков по Stoller'}])
        self.assertTrue(answer.startswith(CARD_PREFIX))
        self.assertIn('3602385', answer)
        self.assertIn('II — линейный', answer)
        self.assertNotIn('III уровень', answer)

    def test_repeated_long_paragraphs_are_flagged(self):
        paragraph = 'Неверный повторяющийся ответ модели. ' * 4
        self.assertTrue(expert.repetitive_answer('\n\n'.join([paragraph] * 3)))
        self.assertFalse(expert.repetitive_answer('Обычный короткий ответ.'))

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
                self.assertEqual(expert.generate_variant(server, model, 'Исходник.', 'Перепиши весь протокол профессионально.'), 'Новый вариант.')
            args = popen.call_args.args[0]
            self.assertIn('127.0.0.1', args)
            self.assertIn('0', args[args.index('-ngl')+1])
            request = opener.open.call_args.args[0]
            self.assertTrue(request.full_url.startswith('http://127.0.0.1:'))
            payload = json.loads(request.data)
            self.assertIn('Перепиши весь протокол профессионально.', payload['messages'][1]['content'])
            self.assertIn('Исходник.', payload['messages'][1]['content'])
            self.assertEqual(payload['max_tokens'], 4096)
            process.terminate.assert_called_once()
            process.wait.assert_called_once()
