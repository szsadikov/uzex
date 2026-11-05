"""Проверка ответа: каждое число и каждая компания/брокер в тексте должны присутствовать в результатах инструментов."""
import re
from functools import lru_cache
from .db import get_con
from .lookup import norm_company

MULT = {
    'тыс': 1e3, 'тысяч': 1e3, 'ming': 1e3,
    'млн': 1e6, 'миллион': 1e6, 'миллиона': 1e6, 'миллионов': 1e6, 'mln': 1e6, 'million': 1e6, 'миллион.': 1e6,
    'млрд': 1e9, 'миллиард': 1e9, 'миллиарда': 1e9, 'миллиардов': 1e9, 'mlrd': 1e9, 'milliard': 1e9,
    'трлн': 1e12, 'триллион': 1e12, 'триллиона': 1e12, 'триллионов': 1e12, 'trln': 1e12, 'trillion': 1e12,
}
SEP = '[   ]'
DATE_RE = re.compile(r'\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b')
ISO_RE = re.compile(r'\b(\d{4})-(\d{2})-(\d{2})\b')
NUM_RE = re.compile(rf'(?<![\w.,])(-?\d{{1,3}}(?:{SEP}\d{{3}})+(?:[.,]\d+)?|-?\d+(?:[.,]\d+)?)(\s*%)?(?:\s*(тыс\w*|млн|миллион\w*|млрд|миллиард\w*|трлн|триллион\w*|ming|mln|million|mlrd|milliard\w*|trln))?', re.I)
CODE_RE = re.compile(r'\b(BK\d{3}|[A-ZА-Я]{1,4}-\d+[\w/,.-]*|Ne\s?\d+/\d+|Ø\s?\d+\w*|\d+[хx]\d+[\w,]*)', re.I)


def _parse(tok: str):
    t = re.sub(SEP, '', tok).replace(',', '.')
    if t.count('.') > 1:
        return None, 0
    try:
        v = float(t)
    except ValueError:
        return None, 0
    dec = len(t.split('.')[1]) if '.' in t else 0
    return v, dec


def _collect(obj, nums: set, strs: list):
    if isinstance(obj, dict):
        for v in obj.values():
            _collect(v, nums, strs)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect(v, nums, strs)
    elif isinstance(obj, bool) or obj is None:
        return
    elif isinstance(obj, (int, float)):
        nums.add(float(obj))
    elif isinstance(obj, str):
        strs.append(obj)
        for d in DATE_RE.findall(obj):
            pass
        for m in re.finditer(r'\d+(?:[.,]\d+)?', obj):
            v, _ = _parse(m.group(0))
            if v is not None:
                nums.add(v)


@lru_cache(maxsize=1)
def _entity_names():
    con = get_con()
    names = {}
    for (n,) in con.execute("SELECT name FROM participants UNION SELECT broker_name FROM brokers").fetchall():
        k = norm_company(n)
        if len(k) >= 6:
            names[k] = n
    return names


def _norm_date(d, m, y):
    return f'{int(d):02d}.{int(m):02d}.{y}'


def validate(answer: str, question: str, tool_results: list):
    nums, strs = set(), []
    _collect(tool_results, nums, strs)
    qnums, qstrs = set(), []
    _collect(question, qnums, qstrs)
    allowed_text = ' '.join(strs + [question])
    allowed_dates = {_norm_date(*m) for m in DATE_RE.findall(allowed_text)} | {'03.01.2022', '30.10.2026', '01.01.2022', '31.10.2026'}
    problems = []

    text = answer
    for m in list(DATE_RE.finditer(text)):
        nd = _norm_date(*m.groups())
        if nd not in allowed_dates:
            problems.append(f'date {m.group(0)}')
    text = DATE_RE.sub(' ', text)
    text = ISO_RE.sub(' ', text)
    text = CODE_RE.sub(lambda m: ' ' if m.group(0) in allowed_text else m.group(0), text)

    pool = nums | qnums
    for m in NUM_RE.finditer(text):
        tok, pct, mult = m.group(1), m.group(2), m.group(3)
        v, dec = _parse(tok)
        if v is None:
            continue
        k = 1.0
        if mult:
            ml = mult.lower()
            k = next((val for key, val in MULT.items() if ml.startswith(key)), 1.0)
        target = v * k
        if k == 1.0 and not pct and float(v).is_integer() and (0 <= v <= 10 or 2022 <= v <= 2026):
            continue  # ранги, номера пунктов, годы периода данных
        tol = max(0.5 * (10 ** -dec) * k, abs(target) * 0.0006, 1e-9)
        ok = any(abs(p - target) <= tol for p in pool)
        if not ok and pct:
            ok = any(abs(p * 100 - target) <= tol for p in pool)
        if not ok and k == 1.0:
            # число могло быть выведено с другим масштабом точности (например 12,3 из 12.345)
            ok = any(abs(p - target) <= max(abs(target) * 0.005, 0.5 * 10 ** -dec) for p in pool if abs(p) >= 1000)
        if not ok:
            problems.append(f'number {m.group(0).strip()}')

    # компании и брокеры
    ans_n = ' ' + norm_company(answer) + ' '
    allowed_n = ' ' + norm_company(allowed_text) + ' '
    for k, orig in _entity_names().items():
        if f' {k} ' in ans_n and f' {k} ' not in allowed_n:
            problems.append(f'entity {orig}')
    return problems
