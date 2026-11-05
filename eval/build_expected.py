"""Эталонные ответы: считаются SQL-ом напрямую, независимо от агента. Выход: eval/questions.json"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app.db import run_sql


def one(sql):
    return run_sql(sql)['rows'][0]


def col(sql, i=0):
    return [r[i] for r in run_sql(sql)['rows']]


Q = []


def add(lang, q, kind, expect=None, alt=None, note=''):
    Q.append({'id': len(Q) + 1, 'lang': lang, 'question': q, 'kind': kind, 'expect': expect or [], 'alt': alt or [], 'note': note})


# ---------- RU ----------
n_all, n_nc = one("SELECT COUNT(*), COUNT(*) FILTER (WHERE not_cancelled) FROM deals WHERE year=2023")
add('ru', 'Сколько всего сделок было заключено в 2023 году?', 'num', [n_all], [n_nc])
s_nc, s_all = one("SELECT SUM(amount_uzs) FILTER (WHERE not_cancelled), SUM(amount_uzs) FROM deals WHERE year=2025")
add('ru', 'Какой общий объём торгов в сумах за 2025 год?', 'num', [s_nc], [s_all])
add('ru', 'Сколько сделок было аннулировано в 2024 году?', 'num', [one("SELECT COUNT(*) FROM deals WHERE year=2024 AND status='Аннулирован(Не оплачен)'")[0]])
add('ru', 'Какой был курс доллара 15.03.2024?', 'num', [one("SELECT usd_rate FROM usd_rates WHERE rate_date=DATE '2024-03-15'")[0]])
add('ru', 'Какая компания является продавцом по контракту № 100002?', 'name', [one("SELECT p.name FROM contracts c JOIN participants p ON p.inn=c.seller_inn WHERE contract_id=100002")[0]])
add('ru', 'Назови топ-3 покупателей карбамида по сумме сделок за 2025 год', 'names',
    col("SELECT buyer_name FROM deals WHERE product_key='310210' AND year=2025 AND not_cancelled GROUP BY 1 ORDER BY SUM(amount_uzs) DESC LIMIT 3"),
    col("SELECT buyer_name FROM deals WHERE product_key='310210' AND year=2025 GROUP BY 1 ORDER BY SUM(amount_uzs) DESC LIMIT 3"))
add('ru', 'Какая средневзвешенная цена за литр бензина АИ-92 в сентябре 2026 года?', 'num',
    [one("SELECT SUM(amount_uzs)/SUM(volume) FROM deals WHERE product_key='271012' AND product_name_norm ILIKE '%аи-92%' AND unit='литр' AND year=2026 AND month=9 AND not_cancelled")[0]],
    [one("SELECT SUM(amount_uzs)/SUM(volume) FROM deals WHERE product_key='271012' AND product_name_norm ILIKE '%аи-92%' AND unit='литр' AND year=2026 AND month=9")[0]],
    note='бензин бывает в тоннах и литрах')
add('ru', 'В каком регионе было больше всего сделок в 2026 году?', 'name', ['Toshkent shahri'], ['г. Ташкент', 'Ташкент'])
add('ru', 'Какова сумма экспортных сделок в долларах за 2025 год?', 'num',
    [one("SELECT SUM(amount_usd) FROM deals WHERE contract_type='Экспортный' AND year=2025 AND not_cancelled")[0]],
    [one("SELECT SUM(amount_usd) FROM deals WHERE contract_type='Экспортный' AND year=2025")[0]])
add('ru', 'Какой брокер участвовал в наибольшем количестве сделок за всё время?', 'name',
    col("SELECT name FROM (SELECT seller_broker_name name FROM deals UNION ALL SELECT buyer_broker_name FROM deals) GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 1"),
    col("SELECT seller_broker_name FROM deals GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 1") + col("SELECT buyer_broker_name FROM deals GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 1"))
add('ru', 'Сколько тонн портландцемента продано в Самаркандской области в 2024 году?', 'num',
    [one("SELECT SUM(volume) FROM deals WHERE product_key='252329' AND region_code='SAM' AND year=2024 AND not_cancelled")[0]],
    [one("SELECT SUM(volume) FROM deals WHERE product_key='252329' AND region_code='SAM' AND year=2024")[0],
     one("SELECT SUM(delivered_volume) FROM deals WHERE product_key='252329' AND region_code='SAM' AND year=2024")[0]])
add('ru', 'Сколько сделок по хлопку-сырцу 1 сорта было в 2023 году?', 'num',
    [one("SELECT COUNT(*) FROM deals WHERE product_key='520100' AND grade='1' AND year=2023")[0]],
    [one("SELECT COUNT(*) FROM deals WHERE product_key='520100' AND grade='1' AND year=2023 AND not_cancelled")[0]])
add('ru', 'Какая доля частично исполненных сделок в 2025 году в процентах?', 'num',
    [one("SELECT 100.0*COUNT(*) FILTER (WHERE status='Исполнен(Частично)')/COUNT(*) FROM deals WHERE year=2025")[0]],
    [one("SELECT 100.0*COUNT(*) FILTER (WHERE status='Исполнен(Частично)')/COUNT(*) FILTER (WHERE not_cancelled) FROM deals WHERE year=2025")[0],
     one("SELECT 100.0*COUNT(*) FILTER (WHERE status='Исполнен(Частично)')/COUNT(*) FILTER (WHERE is_executed) FROM deals WHERE year=2025")[0]])
add('ru', 'Сколько компаний-покупателей есть в реестре участников?', 'num', [one("SELECT COUNT(*) FROM participants WHERE role='Покупатель'")[0]])
d = run_sql("SELECT deal_id, amount_uzs, product_group FROM deals WHERE year=2022 ORDER BY amount_uzs DESC LIMIT 1")['rows'][0]
add('ru', 'Какая самая крупная сделка по сумме в 2022 году?', 'num', [d[0]], note=f'сумма {d[1]}')
d = run_sql("SELECT product_name, amount, buyer_name, status FROM deals WHERE deal_id=300000")['rows'][0]
add('ru', 'Расскажи о сделке № 300000: какой товар, на какую сумму и кто покупатель?', 'num', [d[1]], note=json.dumps(d, ensure_ascii=False))
add('ru', 'Сколько в среднем дней проходит от сделки до оплаты в 2025 году?', 'num',
    [one("SELECT AVG(days_to_pay) FROM deals WHERE year=2025 AND pay_date IS NOT NULL")[0]])
add('ru', 'Сколько сделок в 2024 году были поставлены с нарушением срока поставки?', 'num',
    [one("SELECT COUNT(*) FROM deals WHERE year=2024 AND delivery_date > delivery_due_date")[0]])
add('ru', 'Какой товар принёс наибольший оборот за всё время?', 'name',
    col("SELECT product_group FROM deals WHERE not_cancelled GROUP BY 1 ORDER BY SUM(amount_uzs) DESC LIMIT 1"))
add('ru', 'Сколько сделок провёл продавец с ИНН 999222902 в октябре 2026 года?', 'num',
    [one("SELECT COUNT(*) FROM deals WHERE seller_inn='999222902' AND year=2026 AND month=10")[0]],
    [one("SELECT COUNT(*) FROM deals WHERE seller_inn='999222902' AND year=2026 AND month=10 AND not_cancelled")[0]])
# ---------- no data ----------
add('ru', 'Какой оборот биржи в ноябре 2026 года?', 'nodata')
add('ru', 'Сколько айфонов продано на бирже?', 'nodata')
add('ru', 'Сколько сделок было в 2021 году?', 'nodata')
add('ru', 'Какой объём покупок у компании с ИНН 123456789?', 'nodata')
add('ru', 'Кто директор компании "Pudexiz Plast"?', 'nodata')
# ---------- UZ latin ----------
n_all, n_nc = one("SELECT COUNT(*), COUNT(*) FILTER (WHERE not_cancelled) FROM deals WHERE year=2025")
add('uz', '2025-yilda nechta bitim tuzilgan?', 'num', [n_all], [n_nc])
add('uz', '2024-yilda Farg‘ona viloyatida savdo hajmi so‘mda qancha bo‘lgan?', 'num',
    [one("SELECT SUM(amount_uzs) FROM deals WHERE region_code='FAR' AND year=2024 AND not_cancelled")[0]],
    [one("SELECT SUM(amount_uzs) FROM deals WHERE region_code='FAR' AND year=2024")[0]])
add('uz', '2026-yil 1-yanvar holatiga dollar kursi qancha edi?', 'num', [one("SELECT usd_rate FROM usd_rates WHERE rate_date=DATE '2026-01-01'")[0]])
add('uz', 'Eng ko‘p bitim tuzgan sotuvchi kompaniya qaysi?', 'name',
    col("SELECT seller_name FROM deals GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 1"))
add('uz', '2023-yilda nechta bitim bekor qilingan?', 'num', [one("SELECT COUNT(*) FROM deals WHERE year=2023 AND NOT not_cancelled")[0]])
add('uz', 'Paxta xomashyosi bo‘yicha 2025-yilda jami necha kilogramm sotilgan?', 'num',
    [one("SELECT SUM(volume) FROM deals WHERE product_key='520100' AND year=2025 AND not_cancelled")[0]],
    [one("SELECT SUM(volume) FROM deals WHERE product_key='520100' AND year=2025")[0]])
add('uz', '2030-yilda nechta bitim bo‘ladi?', 'nodata')
# ---------- UZ cyrillic ----------
add('uz_cyr', '2024 йилда экспорт битимлари сони нечта?', 'num',
    [one("SELECT COUNT(*) FROM deals WHERE contract_type='Экспортный' AND year=2024")[0]],
    [one("SELECT COUNT(*) FROM deals WHERE contract_type='Экспортный' AND year=2024 AND not_cancelled")[0]])
add('uz_cyr', 'Тошкент вилоятида 2026 йилда энг кўп сумма бўйича сотилган товар қайси?', 'name',
    col("SELECT product_group FROM deals WHERE region_code='TSV' AND year=2026 AND not_cancelled GROUP BY 1 ORDER BY SUM(amount_uzs) DESC LIMIT 1"),
    col("SELECT product_group_uz FROM deals WHERE region_code='TSV' AND year=2026 AND not_cancelled GROUP BY 1 ORDER BY SUM(amount_uzs) DESC LIMIT 1"))
add('uz_cyr', 'Қайси брокер 2025 йилда энг кўп битимда қатнашган?', 'name',
    col("SELECT name FROM (SELECT seller_broker_name name FROM deals WHERE year=2025 UNION ALL SELECT buyer_broker_name FROM deals WHERE year=2025) GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 1"))
add('uz_cyr', 'Буғдой уни 2026 йилда ўртача неча сўмдан сотилган (1 кг учун)?', 'num',
    [one("SELECT SUM(amount_uzs)/SUM(volume) FROM deals WHERE product_key='110100' AND year=2026 AND not_cancelled")[0]],
    [one("SELECT AVG(unit_price_uzs) FROM deals WHERE product_key='110100' AND year=2026 AND not_cancelled")[0],
     one("SELECT SUM(amount_uzs)/SUM(volume) FROM deals WHERE product_key='110100' AND year=2026")[0]])

out = os.path.join(os.path.dirname(__file__), 'questions.json')
json.dump(Q, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
for q in Q:
    print(q['id'], q['kind'], q['question'][:60], q['expect'][:3], q['alt'][:2])
