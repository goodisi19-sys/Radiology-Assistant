"""Frozen EXE probe of default-browser handoff. Does not launch a real browser."""
import json
from pathlib import Path

def run(target):
    from google_dispatch import open_review
    from privacy_review import make_prompt
    from PySide6.QtCore import QUrlQuery,QUrl
    calls=[];copies=[]
    short=make_prompt('Контруы ровные; размер L4-L5 до 4 мм. Т1+C; A&B; 100%.')
    result=open_review(short,lambda url:calls.append(url) or True,copies.append)
    assert result.opened and not result.copied and not copies
    assert QUrlQuery(calls[-1]).queryItemValue('q',QUrl.ComponentFormattingOption.FullyDecoded)==short
    from urllib.parse import urlsplit,parse_qs
    assert parse_qs(urlsplit(bytes(calls[-1].toEncoded()).decode()).query)['q']==[short]
    assert calls[-1].host()=='www.google.com'
    long=make_prompt('Длинный обезличенный протокол.\n'*1000)
    result=open_review(long,lambda url:calls.append(url) or True,copies.append)
    assert result.opened and result.copied and copies==[long]
    assert not QUrlQuery(calls[-1]).hasQueryItem('q')
    import sys
    assert not any(name.startswith('PySide6.QtWebEngine') for name in sys.modules)
    Path(target).write_text(json.dumps({'default_browser_dispatch':'ok','short_query':'ok','long_query_clipboard':'ok','embedded_webengine_loaded':False,'actual_browser_launch':'not tested on target PC; dispatcher boundary intercepted'},ensure_ascii=False,indent=2))
