"""Нечёткий поиск сущностей: товары, компании, регионы, брокеры. RU / UZ-латиница / UZ-кириллица."""
import re
from functools import lru_cache
from rapidfuzz import process, fuzz
from .db import get_con

CYR2LAT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo', 'ж': 'j', 'з': 'z', 'и': 'i', 'й': 'y',
    'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f',
    'х': 'x', 'ц': 's', 'ч': 'ch', 'ш': 'sh', 'щ': 'sh', 'ъ': "'", 'ы': 'i', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    'ў': "o'", 'қ': 'q', 'ғ': "g'", 'ҳ': 'h',
}
APOS = re.compile(r"[‘’ʻʼ`´]")
ORG = re.compile(r"\b(mchj|mas'uliyati cheklangan jamiyati|masuliyati cheklangan jamiyati|ooo|ооо|мчж|ok|aj|xk|qk|chp|ук|ао|ип|xususiy korxonasi|oilaviy korxona|unitar korxona|broker|брокер)\b")


def translit(s: str) -> str:
    return ''.join(CYR2LAT.get(ch, ch) for ch in s)


def norm(s: str) -> str:
    s = (s or '').lower().replace('ё', 'е')
    s = APOS.sub("'", s)
    s = re.sub(r'["«»“”]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def norm_company(s: str) -> str:
    s = translit(norm(s))
    s = ORG.sub(' ', s)
    s = re.sub(r"[^a-z0-9' ]", ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


@lru_cache(maxsize=1)
def _index():
    con = get_con()
    idx = {}
    # товары: группы + синонимы + конкретные наименования
    prod = []
    for key, grp, grp_uz, aliases in con.execute("SELECT product_key, product_group, product_group_uz, aliases FROM product_groups").fetchall():
        for a in [grp, grp_uz] + aliases.split(';'):
            prod.append((norm(a), translit(norm(a)), ('group', key, grp, grp_uz)))
    for name, key, grp, n in con.execute("SELECT product_name, product_key, product_group, deals FROM product_names").fetchall():
        prod.append((norm(name), translit(norm(name)), ('name', key, grp, name, n)))
    idx['product'] = prod
    # регионы
    reg = []
    for code, ru, uz, aliases in con.execute("SELECT region_code, region_ru, region_uz, aliases FROM regions").fetchall():
        for a in [ru, uz] + aliases.split(';'):
            reg.append((norm(a), translit(norm(a)), (code, ru, uz)))
    idx['region'] = reg
    # компании
    comp = con.execute("SELECT inn, name, role, region_ru, activity FROM participants").fetchall()
    idx['company'] = [(norm_company(r[1]), r) for r in comp]
    idx['company_inn'] = {r[0]: r for r in comp}
    br = con.execute("SELECT broker_code, broker_name, broker_inn, region_ru FROM brokers").fetchall()
    idx['broker'] = [(norm_company(r[1]), r) for r in br]
    idx['broker_code'] = {r[0].lower(): r for r in br}
    return idx


def _fuzzy(query_variants, choices, limit, cutoff):
    best = {}
    for q in query_variants:
        for _, score, i in process.extract(q, choices, scorer=fuzz.WRatio, limit=limit * 3, score_cutoff=cutoff):
            best[i] = max(best.get(i, 0), score)
    return sorted(best.items(), key=lambda x: -x[1])


def lookup(query: str, kind: str = 'any', limit: int = 8):
    idx = _index()
    q = norm(query)
    variants = list({q, translit(q)})
    out = {}
    if kind in ('product', 'any'):
        choices = [p[0] for p in idx['product']] + [p[1] for p in idx['product']]
        hits = _fuzzy(variants, choices, limit, 70)
        groups, names = {}, []
        for i, sc in hits:
            meta = idx['product'][i % len(idx['product'])][2]
            if meta[0] == 'group':
                groups.setdefault(meta[1], {'product_key': meta[1], 'product_group': meta[2], 'product_group_uz': meta[3], 'score': round(sc)})
            else:
                if all(n['product_name'] != meta[3] for n in names):
                    names.append({'product_name': meta[3], 'product_key': meta[1], 'product_group': meta[2], 'deals': meta[4], 'score': round(sc)})
        out['product_groups'] = list(groups.values())[:5]
        out['product_names'] = names[:limit]
    if kind in ('region', 'any'):
        choices = [r[0] for r in idx['region']] + [r[1] for r in idx['region']]
        hits = _fuzzy(variants, choices, 3, 80)
        seen = {}
        for i, sc in hits:
            code, ru, uz = idx['region'][i % len(idx['region'])][2]
            seen.setdefault(code, {'region_code': code, 'region_ru': ru, 'region_uz': uz, 'score': round(sc)})
        out['regions'] = list(seen.values())[:3]
    if kind in ('company', 'any'):
        res = []
        digits = re.sub(r'\D', '', query)
        if len(digits) == 9 and digits in idx['company_inn']:
            r = idx['company_inn'][digits]
            res.append({'inn': r[0], 'name': r[1], 'role': r[2], 'region_ru': r[3], 'activity': r[4], 'score': 100})
        else:
            cq = norm_company(query)
            if len(cq) >= 3:
                for _, score, i in process.extract(cq, [c[0] for c in idx['company']], scorer=fuzz.WRatio, limit=limit, score_cutoff=80):
                    r = idx['company'][i][1]
                    res.append({'inn': r[0], 'name': r[1], 'role': r[2], 'region_ru': r[3], 'activity': r[4], 'score': round(score)})
        out['companies'] = res
    if kind in ('broker', 'any'):
        res = []
        if query.strip().lower() in idx['broker_code']:
            r = idx['broker_code'][query.strip().lower()]
            res.append({'broker_code': r[0], 'broker_name': r[1], 'broker_inn': r[2], 'region_ru': r[3], 'score': 100})
        else:
            cq = norm_company(query)
            if len(cq) >= 3:
                for _, score, i in process.extract(cq, [c[0] for c in idx['broker']], scorer=fuzz.WRatio, limit=5, score_cutoff=80):
                    r = idx['broker'][i][1]
                    res.append({'broker_code': r[0], 'broker_name': r[1], 'broker_inn': r[2], 'region_ru': r[3], 'score': round(score)})
        out['brokers'] = res
    found = any(out.get(k) for k in out)
    out['found'] = found
    if not found:
        out['note'] = 'Nothing similar in the data. Do NOT invent; tell the user this entity is not in the data.'
    return out
