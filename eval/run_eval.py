"""Прогон набора тестов. python eval/run_eval.py [--ids 1,2,3] [--url https://...] [--workers 4]
Без --url вызывает агента локально (нужен GEMINI_API_KEY в окружении или в .env)."""
import os, sys, json, re, time, argparse, concurrent.futures as cf
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app.validate import NUM_RE, MULT, _parse, DATE_RE
from app.lookup import norm_company

envp = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(envp):
    for line in open(envp):
        if '=' in line and not line.startswith('#'):
            k, v = line.strip().split('=', 1)
            os.environ.setdefault(k, v.strip().strip('"'))


def nums_in(text):
    text = DATE_RE.sub(' ', text)
    out = []
    for m in NUM_RE.finditer(text):
        v, dec = _parse(m.group(1))
        if v is None:
            continue
        k = 1.0
        if m.group(3):
            ml = m.group(3).lower()
            k = next((val for key, val in MULT.items() if ml.startswith(key)), 1.0)
        out.append((v * k, dec, k))
    return out


def num_match(text, targets):
    for t in targets:
        if t is None:
            continue
        t = float(t)
        for v, dec, k in nums_in(text):
            tol = max(0.5 * 10 ** -dec * k * 1.01, abs(t) * 0.006, 0.006)
            if abs(v - t) <= tol:
                return True
    return False


def name_match(text, names):
    tn = ' ' + norm_company(text) + ' '
    return any((' ' + norm_company(n) + ' ') in tn or norm_company(n) in tn for n in names if n)


def grade(q, res):
    ans = (res.get('answer') or '') + ' ' + (res.get('assumptions') or '')
    if q['kind'] == 'nodata':
        return 'pass' if res.get('no_data') else 'FAIL'
    if res.get('no_data'):
        return 'FAIL'
    if q['kind'] == 'num':
        if num_match(ans, q['expect']):
            return 'pass'
        return 'alt' if num_match(ans, q['alt']) else 'FAIL'
    if q['kind'] == 'name':
        if name_match(ans, q['expect']):
            return 'pass'
        return 'alt' if name_match(ans, q['alt']) else 'FAIL'
    if q['kind'] == 'names':
        if all(name_match(ans, [n]) for n in q['expect']):
            return 'pass'
        return 'alt' if sum(name_match(ans, [n]) for n in q['expect']) >= 2 else 'FAIL'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ids', default='')
    ap.add_argument('--url', default='')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--out', default='')
    a = ap.parse_args()
    qs = json.load(open(os.path.join(os.path.dirname(__file__), 'questions.json'), encoding='utf-8'))
    if a.ids:
        ids = {int(x) for x in a.ids.split(',')}
        qs = [q for q in qs if q['id'] in ids]
    if a.url:
        import urllib.request
        def call(q):
            req = urllib.request.Request(a.url.rstrip('/') + '/api/ask', data=json.dumps({'question': q['question']}).encode(),
                                         headers={'Content-Type': 'application/json'})
            t = time.time()
            r = json.loads(urllib.request.urlopen(req, timeout=120).read())
            r['wall_s'] = round(time.time() - t, 1)
            return r
    else:
        from app.agent import Agent
        ag = Agent()
        def call(q):
            t = time.time()
            r = ag.ask(q['question'])
            r['wall_s'] = round(time.time() - t, 1)
            return r
    results = []
    with cf.ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(call, q): q for q in qs}
        for f in cf.as_completed(futs):
            q = futs[f]
            try:
                res = f.result()
            except Exception as e:
                res = {'answer': f'ERROR {e}', 'no_data': False}
            g = grade(q, res)
            results.append({'id': q['id'], 'grade': g, 'q': q['question'], 'expect': q['expect'][:3], 'alt': q['alt'][:2],
                            'answer': res.get('answer'), 'assumptions': res.get('assumptions'), 'verified': res.get('verified'),
                            'no_data': res.get('no_data'), 'problems': res.get('problems'), 'wall_s': res.get('wall_s'),
                            'sql': [x['sql'] for x in res.get('queries', [])], 'error': res.get('error')})
            print(f"[{g:4s}] #{q['id']:2d} {res.get('wall_s')}s v={res.get('verified')} | {q['question'][:50]} => {(res.get('answer') or '')[:160]!r}", flush=True)
    results.sort(key=lambda r: r['id'])
    n = len(results)
    p = sum(r['grade'] == 'pass' for r in results)
    al = sum(r['grade'] == 'alt' for r in results)
    times = sorted(r['wall_s'] or 0 for r in results)
    print(f"\nPASS {p}/{n}  ALT {al}  FAIL {n - p - al}  | max {times[-1]}s  p50 {times[n // 2]}s")
    out = a.out or os.path.join(os.path.dirname(__file__), f'results_{int(time.time())}.json')
    json.dump(results, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    print('saved', out)


if __name__ == '__main__':
    main()
