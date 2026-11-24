"""Opt-in CPU-only Gemma experiment using the GGUF chat template in llama-server."""
import json
from pathlib import Path
import re
import socket
import subprocess
import threading
import time
import urllib.request

SYSTEM = (
    'Редактируй телеграфную запись МРТ/КТ на русском. Верни только текст протокола. '
    'Не добавляй и не удаляй факты, отрицания, находки, степени, уровни, стороны, '
    'единицы, числа и квалификаторы вроде «до». Контакт не означает компрессию. '
    'При неоднозначности оставь сокращение. Методика неизменна. '
    'Начинай строки с большой буквы, разделяй фразы точкой с запятой, '
    'завершай строки точкой. Размеры записывай через латинскую x.'
)


class GemmaSession:
    def __init__(self, engine, model, threads=2, context=2048):
        self.engine = Path(engine).resolve()
        self.model = Path(model).resolve()
        self.threads = min(4, max(1, threads))
        if context not in (2048, 4096):
            raise ValueError('Контекст должен быть 2048 или 4096.')
        self.context = context
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.process = None
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def stop(self):
        self.cancelled.set()
        with self.lock:
            if self.process and self.process.poll() is None:
                self.process.kill()

    def load(self):
        if not self.engine.is_file() or not self.model.is_file():
            raise ValueError('Укажите локальные llama-server и GGUF.')
        with self.model.open('rb') as file:
            if file.read(4) != b'GGUF':
                raise ValueError('Файл не является GGUF.')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        self.endpoint = f'http://127.0.0.1:{port}'
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0)
        start = time.monotonic()
        with self.lock:
            if self.cancelled.is_set():
                raise RuntimeError('Отменено.')
            self.process = subprocess.Popen(
                [str(self.engine), '-m', str(self.model), '--host', '127.0.0.1',
                 '--port', str(port), '-ngl', '0', '-t', str(self.threads),
                 '-tb', str(self.threads), '-c', str(self.context), '-np', '1',
                 '--no-webui', '--log-disable', '--jinja', '--reasoning', 'off'],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=flags,
            )
        while not self.cancelled.wait(.2) and time.monotonic()-start < 90:
            if self.process.poll() is not None:
                raise RuntimeError('llama-server завершился при загрузке. Проверьте совместимость GGUF и версию движка.')
            try:
                with self.http.open(self.endpoint+'/health', timeout=1) as response:
                    if response.status == 200:
                        return time.monotonic()-start
            except OSError:
                continue
        self.stop()
        raise RuntimeError('Загрузка отменена или истёк лимит 90 с.')

    def generate(self, source, context='', examples=()):
        if self.cancelled.is_set():
            raise RuntimeError('Отменено.')
        body = {'temperature': 0, 'max_tokens': 220, 'stream': True,
                'messages': [{'role': 'system', 'content': SYSTEM},
                             {'role': 'user', 'content': json.dumps(
                                 {'контекст': context[:240], 'примеры стиля': list(examples)[:3],
                                  'исходник': source[:1200]}, ensure_ascii=False)}]}
        request = urllib.request.Request(self.endpoint+'/v1/chat/completions',
                                         json.dumps(body).encode(), {'Content-Type': 'application/json'})
        start = time.monotonic()
        first = None
        parts = []
        timings = {}
        finish = None
        with self.http.open(request, timeout=120) as response:
            for line in response:
                if self.cancelled.is_set() or time.monotonic()-start > 120:
                    raise RuntimeError('Генерация отменена или истёк лимит 120 с.')
                if not line.startswith(b'data: '):
                    continue
                raw = line[6:].strip()
                if raw == b'[DONE]':
                    break
                item = json.loads(raw)
                timings.update(item.get('timings') or {})
                for choice in item.get('choices', []):
                    value = choice.get('delta', {}).get('content')
                    if value:
                        first = first if first is not None else time.monotonic()-start
                        parts.append(value)
                    finish = choice.get('finish_reason') or finish
        if finish != 'stop' or not parts:
            raise RuntimeError('Модель не вернула завершённое предложение.')
        return ''.join(parts).strip(), {'seconds': time.monotonic()-start, 'first_token_s': first, **timings}


def discrepancies(source, result):
    """Conservative checks. A clean result still requires physician review."""
    from hybrid_safety import facts
    def canonical(value):
        value = value.casefold().replace('ё', 'е')
        value = re.sub(r'(?<=\d)(?=мм|см|мл)', ' ', value)
        value = re.sub(r'\bпрот(?:руз\w*)?\b', 'протрузия', value)
        value = re.sub(r'(?<!\w)([лст])(?=\d)', lambda m: {'л':'l','с':'s','т':'t'}[m[0]], value)
        return re.sub(r'(?<=\d)\s*[xх×]\s*(?=\d)', 'x', value)

    from slot_phrases import FINDING, LEVEL, SIDE
    original_result = result
    source, result = map(canonical, (source, result))
    errors = []
    for pattern, label in [(LEVEL, 'уровни'), (SIDE, 'стороны'), (FINDING, 'находки')]:
        def tokens(text):
            return sorted(re.sub(r'\s+', '', match[0]).replace('–', '-')
                          for match in pattern.finditer(text))
        if tokens(source) != tokens(result):
            errors.append(f'Изменились {label}.')
    # The checker does not infer negation scope across a rewrite. Require review
    # outside the apply button rather than accepting an unverified polarity change.
    if source != result and re.search(r'\b(?:не|нет|без|отсутств\w*)\b', source+' '+result):
        errors.append('Вариант с отрицанием требует ручной сверки области действия.')
    if re.search(r'(?<=\d)\s*[х×]\s*(?=\d)', original_result):
        errors.append('Для размеров используйте латинскую x.')
    if facts(source) != facts(result):
        removed, added = facts(source)-facts(result), facts(result)-facts(source)
        errors.append(f'Защищённые термины: убраны {dict(removed)}, добавлены {dict(added)}.')
    measures = r'(?<!\w)(?:до\s+)?\d+(?:[.,]\d+)?(?:x\d+(?:[.,]\d+)?)*\s*(?:мм|см|мл)\b'
    extract = lambda text: sorted(re.sub(r'\s+', '', m[0]).replace(',', '.') for m in re.finditer(measures, text))
    if extract(source) != extract(result):
        errors.append('Изменились размеры, единицы или квалификатор «до».')
    for pattern, label in [(r'\bкомпр\w*', 'компрессия'), (r'\bконтакт\w*', 'контакт'),
                           (r'\bдеформ\w*', 'деформация'), (r'\bогранич\w*', 'ограничение')]:
        if bool(re.search(pattern, source)) != bool(re.search(pattern, result)):
            errors.append(f'Изменился признак «{label}».')
    if not result or any(not re.fullmatch(r'[А-ЯЁA-Z].*\.', line.strip())
                         for line in original_result.splitlines() if line.strip()):
        errors.append('Ожидаются законченные строки протокола.')
    return errors
