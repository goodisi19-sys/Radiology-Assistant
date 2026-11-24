"""Run experimental modes on synthetic notes. Writes JSON to stdout."""
import argparse
import json
from pathlib import Path
import platform
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psutil
from gemma4 import GemmaSession, discrepancies
from shorthand import expand_note

BASE_CASES = [
    ('л4-л5 дорз прот 4мм деформ дур меш', 'МРТ позвоночника'),
    ('л5-с1 медиан грыжа 6мм без компр кореш', 'МРТ позвоночника'),
    ('в бел вещ лоб дол справа очаг т2 гипер 8x6мм без рест дифф', 'МРТ ГМ'),
    ('мениск медиал зад рог гориз поврежд 2ст', 'МРТ суставов'),
    ('л4-л5 прот до 4мм', 'МРТ позвоночника'),
]
FAMILIES = [
    ('зад цент прот L4-L5 до {n} мм лок деформ дурального мешка', 'МРТ позвоночника'),
    ('прот C5-C6 до {n} мм без компрессии справа', 'МРТ позвоночника'),
    ('очаг в мозге слева {n}x6 мм без отёка', 'МРТ ГМ'),
    ('гипер т2 очаг справа {n} мм без рест дифф', 'МРТ ГМ'),
    ('киста почки справа {n} мм без расширения члс', 'КТ брюшной полости'),
    ('киста печени слева до {n} мм без кальцинатов', 'КТ брюшной полости'),
    ('выпот кол суст слева до {n} мм без перелома', 'МРТ суставов'),
    ('мениск справа гориз поврежд; выпот {n} мм', 'МРТ суставов'),
    ('ОМТ эндометрий {n} мм без очагов; пм?', 'МРТ ОМТ'),
    ('КТ лёгких узел справа до {n} мм без выпота', 'КТ грудной клетки'),
]
CASES = BASE_CASES + [(text.format(n=n), area) for text, area in FAMILIES for n in (3, 4, 6, 8, 12)]


def run(args):
    from hybrid_safety import facts, language_example
    rows = []
    session = None
    metadata = {'platform': platform.platform(), 'cpu': platform.processor(),
                'cores': psutil.cpu_count(), 'threads': args.threads, 'context': args.context}
    mode_set = 'ABCD' if args.engine else 'A'
    try:
        if args.engine:
            session = GemmaSession(args.engine, args.model, args.threads, args.context)
            metadata['load_s'] = session.load()
            process = psutil.Process(session.process.pid)
            process.cpu_percent()
            metadata['rss_loaded_bytes'] = process.memory_info().rss
            peak = [metadata['rss_loaded_bytes']]
            stop_sample = threading.Event()

            def sample():
                while not stop_sample.wait(.05):
                    peak[0] = max(peak[0], process.memory_info().rss)

            threading.Thread(target=sample, daemon=True).start()
        for source, area in CASES:
            started = time.monotonic()
            local, _ = expand_note(source)
            local_seconds = time.monotonic()-started
            for mode in mode_set:
                metrics = {'seconds': local_seconds}
                error = None
                if mode == 'A' or (mode == 'D' and local and not discrepancies(source, local)):
                    result = local
                else:
                    examples = [line for line in args.examples if language_example(line)] if mode in 'CD' else []
                    try:
                        result, metrics = session.generate(source, area, examples)
                    except (OSError, RuntimeError, ValueError) as exc:
                        result, error = None, str(exc)
                violations = discrepancies(source, result) if result else []
                rows.append({'mode': mode, 'source': source, 'area': area,
                             'expected_protected_tokens': dict(facts(source)),
                             'text': result, 'violations': violations, 'error': error, **metrics})
        if session:
            metadata['cpu_percent'] = process.cpu_percent()
            stop_sample.set()
            metadata['rss_peak_generation_bytes'] = peak[0]
    finally:
        if session:
            session.stop()
    return {'environment': metadata, 'cases': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine')
    parser.add_argument('--model')
    parser.add_argument('--threads', type=int, default=2)
    parser.add_argument('--context', type=int, choices=(2048, 4096), default=2048)
    parser.add_argument('--examples', nargs='*', default=[])
    args = parser.parse_args()
    if bool(args.engine) != bool(args.model):
        parser.error('Specify both --engine and --model for model modes.')
    print(json.dumps(run(args), ensure_ascii=False, indent=2))
