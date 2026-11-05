"""Агент: Gemini + function calling поверх DuckDB, с программной проверкой ответа."""
import os, re, time, json, logging
from google import genai
from google.genai import types
from .db import run_sql, SQLError, get_con
from .lookup import lookup
from .validate import validate

log = logging.getLogger('agent')
MODEL = os.environ.get('GEMINI_MODEL', 'gemini-3.6-flash')
FALLBACK_MODEL = os.environ.get('GEMINI_FALLBACK_MODEL', 'gemini-3.5-flash-lite')
TIME_BUDGET = float(os.environ.get('TIME_BUDGET_S', '70'))
MAX_STEPS = int(os.environ.get('MAX_STEPS', '8'))
THINKING = os.environ.get('GEMINI_THINKING', 'low')  # low | high | off

SYSTEM = open(os.path.join(os.path.dirname(__file__), 'prompt.md'), encoding='utf-8').read()

TOOLS = [types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name='lookup',
        description='Fuzzy-find exact keys for a product, company (name or INN), region or broker (name or code) mentioned by the user, in Russian or Uzbek (Latin/Cyrillic). Returns candidates with product_key / inn / region_code / broker_code.',
        parameters=types.Schema(type='OBJECT', properties={
            'query': types.Schema(type='STRING', description='Name as written by the user'),
            'kind': types.Schema(type='STRING', enum=['product', 'company', 'region', 'broker', 'any']),
        }, required=['query', 'kind'])),
    types.FunctionDeclaration(
        name='run_sql',
        description='Run one read-only DuckDB SELECT over tables deals, contracts, participants, brokers, usd_rates, regions, product_groups. Returns up to 60 rows. Do all arithmetic here.',
        parameters=types.Schema(type='OBJECT', properties={
            'sql': types.Schema(type='STRING'),
            'purpose': types.Schema(type='STRING', description='One short phrase: what this query computes'),
        }, required=['sql'])),
    types.FunctionDeclaration(
        name='submit_answer',
        description='Final answer to the user. Call exactly once at the end.',
        parameters=types.Schema(type='OBJECT', properties={
            'answer': types.Schema(type='STRING', description='Concise answer in the language/script of the question. Every number must come from run_sql results.'),
            'assumptions': types.Schema(type='STRING', description='Filters/period/definitions used (e.g. "без аннулированных сделок, сумма в сумах"), same language as answer'),
            'no_data': types.Schema(type='BOOLEAN', description='true if the data does not contain the answer'),
        }, required=['answer', 'no_data'])),
])]


def detect_lang(q: str) -> str:
    if re.search(r'[ўқғҳЎҚҒҲ]', q):
        return 'uz_cyr'
    lat = len(re.findall(r'[a-zA-Z]', q))
    cyr = len(re.findall(r'[а-яА-ЯёЁ]', q))
    if lat > cyr:
        return 'uz'
    if re.search(r'\b(qancha|nechta|necha|qaysi|bitim|yil|viloyat|savdo|sotuvchi|xaridor)\b', q, re.I):
        return 'uz'
    return 'ru'


MSG = {
    'ru': {'nodata': 'В данных нет ответа на этот вопрос.',
           'unverified': 'Не удалось надёжно подтвердить ответ данными, поэтому показываю только результат запроса к реестру:',
           'timeout': 'Не успел надёжно посчитать ответ за отведённое время. Попробуйте уточнить вопрос.',
           'error': 'Сервис временно не смог обработать вопрос. Попробуйте ещё раз.'},
    'uz': {'nodata': 'Maʼlumotlarda bu savolga javob yoʻq.',
           'unverified': 'Javobni maʼlumotlar bilan ishonchli tasdiqlab boʻlmadi, shuning uchun faqat reyestr soʻrovi natijasini koʻrsataman:',
           'timeout': 'Ajratilgan vaqt ichida javobni ishonchli hisoblay olmadim. Savolni aniqlashtirib koʻring.',
           'error': 'Xizmat savolni vaqtincha qayta ishlay olmadi. Yana urinib koʻring.'},
    'uz_cyr': {'nodata': 'Маълумотларда бу саволга жавоб йўқ.',
               'unverified': 'Жавобни маълумотлар билан ишончли тасдиқлаб бўлмади, шунинг учун фақат реестр сўрови натижасини кўрсатаман:',
               'timeout': 'Ажратилган вақт ичида жавобни ишончли ҳисоблай олмадим. Саволни аниқлаштириб кўринг.',
               'error': 'Хизмат саволни вақтинча қайта ишлай олмади. Яна уриниб кўринг.'},
}


_TECH = r"(?:[a-z]+_[a-z_]+|year|month|quarter|status|unit|currency)"
_PAREN_TECH = re.compile(r"\s*\((?=[^()]*\b" + _TECH + r"\b)[^()]*\)")
_CODE_TICK = re.compile(r"`([^`]*)`")


_TNVED = None


def _tnved_codes():
    global _TNVED
    if _TNVED is None:
        _TNVED = {r[0] for r in get_con().execute("SELECT DISTINCT tnved FROM product_groups").fetchall()}
    return _TNVED


def humanize(text: str) -> str:
    """Убирает из текста служебные имена колонок/кодов (только удаление — новых значений не добавляет)."""
    if not text:
        return text
    t = _PAREN_TECH.sub('', text)
    t = _CODE_TICK.sub(lambda m: '' if re.fullmatch(r"[\w\s=<>'.,%-]*", m.group(1)) and re.search(_TECH + r"|^[A-Z]{3}$|^\d{6}(_[MD])?$", m.group(1)) else m.group(1), t)
    t = re.sub(r"\s*\((?:код[^()]*|kodi[^()]*|коди[^()]*|тн вэд[^()]*|tn ved[^()]*)\)", '', t, flags=re.I)
    t = re.sub(r"\s*\((\d{6})(?:_[MD])?\)", lambda m: '' if m.group(1) in _tnved_codes() else m.group(0), t)
    t = re.sub(r"[ \t]+([,.;:])", r"\1", t)
    t = re.sub(r"[ \t]{2,}", ' ', t)
    return t.strip()


def _fmt_cell(v):
    if isinstance(v, float):
        if v.is_integer():
            return f'{int(v):,}'.replace(',', ' ')
        return f'{v:,.2f}'.replace(',', ' ')
    if isinstance(v, int) and abs(v) >= 10000 and not (100000000 <= v <= 999999999):
        return f'{v:,}'.replace(',', ' ')
    return str(v)


def table_text(res, max_rows=10):
    cols = res['columns']
    lines = [' | '.join(cols)]
    for r in res['rows'][:max_rows]:
        lines.append(' | '.join(_fmt_cell(v) for v in r))
    return '\n'.join(lines)


class Agent:
    def __init__(self, api_key=None):
        self.client = genai.Client(api_key=api_key or os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY'),
                                   http_options=types.HttpOptions(timeout=int(os.environ.get('LLM_TIMEOUT_MS', '25000'))))
        get_con()

    def _config(self, force_final=False, timeout_ms=25000):
        kw = dict(system_instruction=SYSTEM, tools=TOOLS, temperature=0,
                  http_options=types.HttpOptions(timeout=int(timeout_ms)),
                  automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                  tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(
                      mode='ANY', allowed_function_names=['submit_answer'] if force_final else None)))
        if THINKING != 'off':
            kw['thinking_config'] = types.ThinkingConfig(thinking_level=THINKING)
        return types.GenerateContentConfig(**kw)

    def _generate(self, contents, force_final, trace, deadline):
        last = None
        for model in (MODEL, FALLBACK_MODEL):
            for attempt in range(2):
                t = time.time()
                remaining = deadline - t
                if remaining < 4:
                    raise TimeoutError('time budget exhausted')
                try:
                    r = self.client.models.generate_content(model=model, contents=contents,
                                                            config=self._config(force_final, min(25000, remaining * 1000 - 2000)))
                    u = getattr(r, 'usage_metadata', None)
                    trace.append({'model': model, 's': round(time.time() - t, 2), 'ok': True,
                                  'calls': [fc.name for fc in (r.function_calls or [])],
                                  'in': getattr(u, 'prompt_token_count', None), 'out': getattr(u, 'candidates_token_count', None),
                                  'think': getattr(u, 'thoughts_token_count', None)})
                    return r, model
                except Exception as e:  # сеть, 5xx, 429
                    last = e
                    msg = str(e)[:200]
                    trace.append({'model': model, 's': round(time.time() - t, 2), 'ok': False, 'err': msg})
                    log.warning('LLM error %s %s: %s', model, attempt, msg)
                    if '404' in msg or 'not found' in msg.lower() or '400' in msg:
                        break  # модель недоступна / неверный запрос — сразу к запасной
                    time.sleep(0.5)
        raise last

    def ask(self, question: str):
        t0 = time.time()
        lang = detect_lang(question)
        m = MSG[lang]
        contents = [types.Content(role='user', parts=[types.Part(text=question)])]
        queries, tool_log, trace = [], [], []
        validation_retry_used = False
        model_used = MODEL
        result = None
        try:
            for step in range(MAX_STEPS):
                elapsed = time.time() - t0
                force = step >= MAX_STEPS - 1 or elapsed > TIME_BUDGET * 0.7
                if elapsed > TIME_BUDGET:
                    break
                resp, model_used = self._generate(contents, force, trace, t0 + TIME_BUDGET)
                cand = resp.candidates[0].content if resp.candidates else None
                calls = resp.function_calls or []
                if cand is None or not calls:
                    text = (resp.text or '').strip() if cand else ''
                    if text:
                        calls = [types.FunctionCall(name='submit_answer', args={'answer': text, 'no_data': False})]
                    else:
                        contents.append(types.Content(role='user', parts=[types.Part(text='Call submit_answer now.')]))
                        continue
                else:
                    contents.append(cand)
                parts = []
                final = None
                for fc in calls:
                    args = dict(fc.args or {})
                    if fc.name == 'lookup':
                        out = lookup(args.get('query', ''), args.get('kind', 'any'))
                        tool_log.append({'tool': 'lookup', 'args': args, 'result': out})
                    elif fc.name == 'run_sql':
                        try:
                            out = run_sql(args.get('sql', ''))
                            if out['row_count'] == 0:
                                out['note'] = 'Query returned 0 rows: there is no such data (unless the filter is wrong).'
                            elif all(v is None for r in out['rows'] for v in r):
                                out['note'] = 'Only NULLs returned: there is no such data (unless the filter is wrong).'
                            queries.append({'sql': args.get('sql', ''), 'purpose': args.get('purpose', ''), **out})
                        except SQLError as e:
                            out = {'error': str(e)}
                        tool_log.append({'tool': 'run_sql', 'args': args, 'result': out})
                    elif fc.name == 'submit_answer':
                        final = args
                        out = {'status': 'received'}
                    else:
                        out = {'error': 'unknown tool'}
                    parts.append(types.Part.from_function_response(name=fc.name, response={'result': out} if not isinstance(out, dict) else out))
                if final is not None:
                    answer = (final.get('answer') or '').strip()
                    no_data = bool(final.get('no_data'))
                    problems = validate(answer + ' ' + (final.get('assumptions') or ''), question, [t['result'] for t in tool_log])
                    if not problems:
                        result = {'answer': humanize(answer), 'assumptions': humanize(final.get('assumptions') or ''), 'no_data': no_data, 'verified': True}
                        break
                    log.warning('validation failed: %s', problems)
                    if not validation_retry_used and time.time() - t0 < TIME_BUDGET * 0.75:
                        validation_retry_used = True
                        contents.append(types.Content(role='user', parts=parts))
                        contents.append(types.Content(role='user', parts=[types.Part(text=(
                            'VALIDATION FAILED. These values in your answer are not present in any tool result: '
                            + '; '.join(problems[:10]) +
                            '. Do not invent or compute in your head. Either run_sql to obtain them exactly, or remove them. Then call submit_answer again.'))]))
                        continue
                    result = self._fallback(m, queries, problems)
                    break
                contents.append(types.Content(role='user', parts=parts))
            if result is None:
                result = self._fallback(m, queries, ['timeout'], timeout=True)
        except TimeoutError:
            result = self._fallback(m, queries, ['timeout'], timeout=True)
        except Exception as e:
            log.exception('agent error')
            result = {'answer': m['error'], 'assumptions': '', 'no_data': True, 'verified': False, 'error': str(e)[:300]}
        result.update({
            'lang': lang, 'model': model_used, 'elapsed_s': round(time.time() - t0, 1),
            'queries': [{k: q[k] for k in ('sql', 'purpose', 'columns', 'rows', 'row_count', 'truncated')} for q in queries],
            'lookups': [t['args'] for t in tool_log if t['tool'] == 'lookup'],
            'trace': trace,
        })
        return result

    def _fallback(self, m, queries, problems, timeout=False):
        good = [q for q in queries if q.get('row_count')]
        if good:
            q = good[-1]
            ans = m['unverified'] + '\n\n' + table_text(q)
            return {'answer': ans, 'assumptions': q.get('purpose', ''), 'no_data': False, 'verified': False, 'problems': problems}
        return {'answer': m['timeout'] if timeout else m['nodata'], 'assumptions': '', 'no_data': True, 'verified': False, 'problems': problems}


def diag(api_key=None):
    """Быстрая проверка доступности моделей."""
    client = genai.Client(api_key=api_key or os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY'))
    out = {'key_set': bool(os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY'))}
    for model in (MODEL, FALLBACK_MODEL):
        for th in (THINKING, 'off'):
            t = time.time()
            try:
                kw = dict(http_options=types.HttpOptions(timeout=15000), temperature=0)
                if th != 'off':
                    kw['thinking_config'] = types.ThinkingConfig(thinking_level=th)
                r = client.models.generate_content(model=model, contents='Reply with the single word OK',
                                                   config=types.GenerateContentConfig(**kw))
                out[f'{model}|{th}'] = {'s': round(time.time() - t, 2), 'text': (r.text or '')[:20]}
            except Exception as e:
                out[f'{model}|{th}'] = {'s': round(time.time() - t, 2), 'err': str(e)[:300]}
    return out
