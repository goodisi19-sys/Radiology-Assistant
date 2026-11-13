"""Small source-linked reference cards, separate from unverified model output.

This is one checked topic, not a validated medical knowledge base.
"""
import re

CARD_PREFIX = '[Справочная карточка по источникам; не генерация ИИ]'
STOLLER_CARD = CARD_PREFIX + '''

Stoller: МР-оценка внутрименискового сигнала (стандартная шкала 0–III)

0 — однородный низкий сигнал, нормальный мениск.
I — очаговый повышенный сигнал внутри мениска без выхода на суставную поверхность.
II — линейный повышенный сигнал без выхода на суставную поверхность.
III — повышенный сигнал достигает хотя бы одной суставной поверхности мениска; МР-признак разрыва.

I–II сами по себе не доказывают разрыв. Оценка связи сигнала с поверхностью на нескольких изображениях повышает уверенность; учитывают морфологию и контекст исследования. Эта шкала не классифицирует повреждения связок. Уровни IV–V из приведённого ответа ИИ не относятся к стандартной шкале 0–III.

Источники:
Stoller DW et al. Radiology. 1987;163:731–735. DOI: 10.1148/radiology.163.3.3575724.
https://pubmed.ncbi.nlm.nih.gov/3575724/
Crues JV et al. Radiology. 1987;164:445–448. DOI: 10.1148/radiology.164.2.3602385.
https://pubmed.ncbi.nlm.nih.gov/3602385/
Correlation of Histological Examination of Meniscus with MR Images (2013): определения степеней I–III.
https://pmc.ncbi.nlm.nih.gov/articles/PMC3835642/

Карточка относится к стандартной шкале, не заменяет оценку конкретного исследования и не описывает все её модификации.'''


def reference_answer(history):
    question = history[-1]['content'].casefold() if history else ''
    named = re.search(r'\b(?:stoller|штоллер\w*|столлер\w*)\b', question)
    followup = (len(history) >= 2 and history[-2]['role'] == 'assistant'
                and history[-2]['content'].startswith(CARD_PREFIX)
                and re.search(r'степен|поверхност|сигнал|классификац', question))
    return STOLLER_CARD if named or followup else None
