"""Сборка нормализованных данных из исходных CSV в Parquet.

Запуск: python build/build_data.py <папка_с_csv> <папка_вывода>
deals_*.csv могут лежать как .csv или .csv.gz (в той же папке или в подпапке _gz).
"""
import sys, os, re, glob
import duckdb

SRC = sys.argv[1] if len(sys.argv) > 1 else '/mnt/user-data/uploads/uzex_spot_data'
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), '..', 'data')
os.makedirs(OUT, exist_ok=True)

deal_files = sorted(glob.glob(f'{SRC}/deals_*.csv')) or sorted(glob.glob(f'{SRC}/_gz/deals_*.csv.gz'))
assert len(deal_files) == 5, deal_files

# ---------- справочник регионов ----------
REGIONS = [
    # code, ru (как в contracts), uz (как в deals), доп. варианты
    ('TSH', 'г. Ташкент', 'Toshkent shahri', 'ташкент город;тошкент шаҳри;toshkent sh;tashkent city;г.ташкент;город ташкент'),
    ('TSV', 'Ташкентская область', 'Toshkent viloyati', 'тошкент вилояти;ташкентская обл;tashkent region'),
    ('AND', 'Андижанская область', 'Andijon viloyati', 'андижон;андижан;andijan'),
    ('BUX', 'Бухарская область', 'Buxoro viloyati', 'бухоро;бухара;bukhara;buxoro'),
    ('FAR', 'Ферганская область', 'Farg‘ona viloyati', "фарғона;фергана;fergana;fargona;farg'ona"),
    ('JIZ', 'Джизакская область', 'Jizzax viloyati', 'жиззах;джизак;jizzakh;jizzax'),
    ('XOR', 'Хорезмская область', 'Xorazm viloyati', 'хоразм;хорезм;khorezm;xorazm'),
    ('NAM', 'Наманганская область', 'Namangan viloyati', 'наманган;namangan'),
    ('NAV', 'Навоийская область', 'Navoiy viloyati', 'навоий;навои;navoi;navoiy'),
    ('QAS', 'Кашкадарьинская область', 'Qashqadaryo viloyati', 'қашқадарё;кашкадарья;kashkadarya;qashqadaryo'),
    ('QQR', 'Республика Каракалпакстан', 'Qoraqalpog‘iston Respublikasi', "қорақалпоғистон;каракалпакстан;karakalpakstan;qoraqalpog'iston;нукус"),
    ('SAM', 'Самаркандская область', 'Samarqand viloyati', 'самарқанд;самарканд;samarkand;samarqand'),
    ('SIR', 'Сырдарьинская область', 'Sirdaryo viloyati', 'сирдарё;сырдарья;syrdarya;sirdaryo'),
    ('SUR', 'Сурхандарьинская область', 'Surxondaryo viloyati', 'сурхондарё;сурхандарья;surkhandarya;surxondaryo'),
]

# ---------- справочник товарных групп по ТН ВЭД ----------
# tnved -> (каноническое имя RU, имя UZ, синонимы через ;)
PRODUCTS = {
    '520100': ('Хлопок-сырец', 'Paxta xomashyosi', 'хлопок сырец;хлопок;paxta;пахта;хом ашё'),
    '110100': ('Мука пшеничная', 'Bug‘doy uni', 'мука;un;ун;bugdoy uni'),
    '252329': ('Портландцемент', 'Portlandsement', 'цемент;цемент портландский;sement;семент'),
    '100199': ('Пшеница', 'Bug‘doy', 'пшеница продовольственная;bugdoy;буғдой'),
    '391721': ('Трубы полиэтиленовые', 'Polietilen quvurlar', 'труба пэ;трубы пэ;quvur;қувур'),
    '151229': ('Масло хлопковое', 'Paxta yog‘i', 'хлопковое масло;paxta yogi;пахта ёғи'),
    '700529': ('Стекло листовое', 'List shisha', 'стекло флоат;стекло;shisha;шиша'),
    '390120': ('Полиэтилен', 'Polietilen', 'полиэтилен гранулированный;pe'),
    '690410': ('Кирпич керамический', 'Keramik g‘isht', 'кирпич;gisht;ғишт'),
    '271012': ('Бензин автомобильный', 'Benzin', 'бензин;бензин аи;benzin'),
    '271019_M': ('Мазут топочный', 'Mazut', 'мазут;mazut'),
    '271019_D': ('Дизельное топливо', 'Dizel yoqilg‘isi', 'дизель;топливо дизельное;дт;dizel;solyarka;солярка'),
    '252020': ('Гипс строительный', 'Gips', 'гипс;gips'),
    '271320': ('Битум нефтяной', 'Bitum', 'битум;bitum'),
    '520512': ('Пряжа хлопчатобумажная', 'Paxta ip-kalavasi', 'пряжа хлопковая;пряжа;ip;kalava;ип калава'),
    '740311': ('Катод медный', 'Mis katod', 'медный катод;медь;mis'),
    '390210': ('Полипропилен', 'Polipropilen', 'pp;пп'),
    '100630': ('Рис шлифованный', 'Guruch', 'рис;guruch;гуруч'),
    '440711': ('Пиломатериалы', 'Yog‘och-taxta', 'пиломатериал обрезной;доска;taxta;yogoch;ёғоч'),
    '721710': ('Проволока арматурная', 'Armatura simi', 'проволока;sim'),
    '320810': ('Эмаль', 'Emal (bo‘yoq)', 'эмаль алкидная;краска;emal;boyoq'),
    '271112': ('Сжиженный газ', 'Suyultirilgan gaz', 'газ сжиженный пропан-бутан;пропан;суг;сжиженный углеводородный газ;gaz;propan'),
    '760421': ('Профиль алюминиевый', 'Alyuminiy profil', 'алюминиевый профиль;profil'),
    '230610': ('Шрот хлопковый', 'Paxta shroti', 'шрот хлопковых семян;шрот;shrot;kunjara;кунжара'),
    '151219': ('Масло подсолнечное', 'Kungaboqar yog‘i', 'подсолнечное масло;kungaboqar'),
    '250100': ('Соль пищевая', 'Osh tuzi', 'соль;соль поваренная;tuz;туз'),
    '310210': ('Карбамид', 'Karbamid', 'мочевина;karbamid;mochevina'),
    '280700': ('Серная кислота', 'Sulfat kislota', 'кислота серная;kislota'),
    '721420': ('Арматура стальная', 'Armatura', 'арматура;armatura'),
    '220190': ('Вода питьевая', 'Ichimlik suvi', 'питьевая вода;вода;suv'),
    '310230': ('Аммиачная селитра', 'Ammiakli selitra', 'селитра аммиачная;селитра;selitra'),
    '170199': ('Сахар белый', 'Oq shakar', 'сахар;сахар-песок;shakar;шакар'),
    '230990': ('Комбикорм (кормосмесь)', 'Omuxta yem', 'кормосмесь;комбикорм;yem;ем'),
    '252210': ('Известь', 'Ohak', 'известь негашеная;известь строительная;ohak;оҳак'),
    '280421': ('Аргон', 'Argon', 'аргон газообразный'),
    '280430': ('Азот', 'Azot', 'azot'),
    '390410': ('Поливинилхлорид (ПВХ)', 'Polivinilxlorid (PVX)', 'пвх;pvc;pvx'),
    '720853': ('Лист стальной горячекатаный', 'Po‘lat list (issiq prokat)', 'лист стальной;стальной лист;list;polat'),
    '848210': ('Подшипник', 'Podshipnik', 'подшипники'),
    '281511': ('Сода каустическая', 'Kaustik soda', 'каустик;soda'),
    '854449': ('Кабель силовой', 'Kuch kabeli', 'кабель;kabel'),
}

con = duckdb.connect()
con.execute("SET threads=4")

def csv(name):
    return f"read_csv('{SRC}/{name}', all_varchar=true, header=true)"

files_sql = '[' + ','.join(f"'{f}'" for f in deal_files) + ']'
con.execute(f"CREATE TABLE raw_deals AS SELECT * FROM read_csv({files_sql}, all_varchar=true, header=true)")
con.execute(f"CREATE TABLE raw_contracts AS SELECT * FROM {csv('contracts.csv')}")
con.execute(f"CREATE TABLE raw_participants AS SELECT * FROM {csv('participants.csv')}")
con.execute(f"CREATE TABLE raw_brokers AS SELECT * FROM {csv('brokers.csv')}")
con.execute(f"CREATE TABLE raw_usd AS SELECT * FROM {csv('usd_rates.csv')}")

con.execute("CREATE MACRO num(x) AS TRY_CAST(replace(replace(replace(x, ' ', ''), chr(160), ''), chr(8239), '') AS DOUBLE)")
con.execute("CREATE MACRO dt(x) AS TRY_CAST(strptime(x, '%d.%m.%Y') AS DATE)")

con.execute("CREATE TABLE regions(region_code VARCHAR, region_ru VARCHAR, region_uz VARCHAR, aliases VARCHAR)")
con.executemany("INSERT INTO regions VALUES (?,?,?,?)", REGIONS)

con.execute("CREATE TABLE product_groups(product_key VARCHAR, tnved VARCHAR, product_group VARCHAR, product_group_uz VARCHAR, aliases VARCHAR)")
con.executemany("INSERT INTO product_groups VALUES (?,?,?,?,?)",
                [(k, k.split('_')[0], v[0], v[1], v[2]) for k, v in PRODUCTS.items()])

con.execute("""CREATE TABLE usd_rates AS
SELECT dt("Дата") AS rate_date, num("Курс") AS usd_rate FROM raw_usd""")

con.execute("""CREATE TABLE brokers AS
SELECT "Код брокера" AS broker_code, "Наименование" AS broker_name, "ИНН" AS broker_inn,
       r.region_code, r.region_ru, r.region_uz
FROM raw_brokers b LEFT JOIN regions r ON r.region_uz = b."Регион" """)

con.execute("""CREATE TABLE participants AS
SELECT "ИНН" AS inn, "Наименование" AS name, r.region_code, r.region_ru, r.region_uz,
       "Вид деятельности" AS activity, "Роль" AS role, ("Плательщик НДС" = 'Да') AS vat_payer
FROM raw_participants p LEFT JOIN regions r ON r.region_uz = p."Регион" """)

# нормализация сорта и класса из полного наименования
def grade_of(s: str):
    s = (s or '').lower().replace('ё', 'е')
    if re.search(r'высш|в/с', s):
        return 'высший'
    m = re.search(r'(?<![\w/])(1|i|перв\w*|2|ii|втор\w*|3|iii|трет\w*)[\s-]*сорт', s)
    if not m:
        return None
    t = m.group(1)
    if t in ('1', 'i') or t.startswith('перв'): return '1'
    if t in ('2', 'ii') or t.startswith('втор'): return '2'
    return '3'

def class_of(s: str):
    s = (s or '').lower()
    m = re.search(r'(?<![\w/])(1|2|3|4|i|ii|iii|iv)[\s-]*класс', s)
    if not m: return None
    return {'i': '1', 'ii': '2', 'iii': '3', 'iv': '4'}.get(m.group(1), m.group(1))

def norm_name(s: str):
    s = (s or '').lower().replace('ё', 'е')
    s = re.sub(r'\b(марка|размер|сорт|тип|класс)\b(?=\s)', lambda m: m.group(1), s)
    s = re.sub(r'(\d),(\d)\s+н\b', r'\1,\2н', s)          # 32,5 н -> 32,5н
    s = re.sub(r'(\d)\s+(мм|л|кг)\b', r'\1\2', s)          # 63 мм -> 63мм
    s = re.sub(r'\s+', ' ', s).strip()
    return s

con.create_function('grade_of', grade_of, ['VARCHAR'], 'VARCHAR', null_handling='special')
con.create_function('class_of', class_of, ['VARCHAR'], 'VARCHAR', null_handling='special')
con.create_function('norm_name', norm_name, ['VARCHAR'], 'VARCHAR', null_handling='special')

con.execute("""CREATE TABLE contracts AS
SELECT
  TRY_CAST("Номер контракта" AS INTEGER) AS contract_id,
  "Наименование продукта" AS product_name_raw,
  CASE WHEN "Код ТН ВЭД"='271019' AND lower("Наименование продукта") LIKE '%мазут%' THEN '271019_M'
       WHEN "Код ТН ВЭД"='271019' THEN '271019_D' ELSE "Код ТН ВЭД" END AS product_key,
  "Код ТН ВЭД" AS tnved,
  "Марка товара" AS brand, "Размер товара" AS size, "Сорт товара" AS grade_raw,
  "Тип товара" AS kind, "Класс товара" AS class_raw,
  "Группа товара" AS liquidity_group, "Категория товара" AS category, "Отрасль промышленности" AS industry,
  "Единица измерения" AS unit, num("Лот") AS lot,
  CASE WHEN "Валюта"='Доллар США' THEN 'USD' ELSE 'UZS' END AS currency,
  num("Базисная цена") AS base_price,
  num(replace("Сумма залога", '%', '')) AS deposit_pct,
  "Базис поставки" AS delivery_basis, r.region_code, r.region_ru, r.region_uz,
  "Адрес склада" AS warehouse_address, "Тип торгов" AS trade_type,
  "Тип контракта" AS contract_type, "Форма контракта" AS contract_form,
  TRY_CAST("Срок оплаты" AS INTEGER) AS pay_term_days,
  TRY_CAST("Срок поставки" AS INTEGER) AS delivery_term_days,
  "Упаковка" AS packaging, "ИНН продавца" AS seller_inn,
  dt("Дата регистрации") AS registered_date, dt("Действует до") AS valid_until
FROM raw_contracts c LEFT JOIN regions r ON r.region_ru = c."Регион" """)
con.execute("""ALTER TABLE contracts ADD COLUMN product_group VARCHAR;
ALTER TABLE contracts ADD COLUMN product_group_uz VARCHAR;
UPDATE contracts SET product_group = p.product_group, product_group_uz = p.product_group_uz
FROM product_groups p WHERE p.product_key = contracts.product_key;""")

con.execute("""CREATE TABLE deals AS
WITH d AS (
  SELECT
    TRY_CAST("Номер сделки" AS BIGINT) AS deal_id,
    dt("Дата сделки") AS deal_date,
    "Время сделки" AS deal_time,
    "Тип торгов" AS trade_type,
    num("Количество") AS qty_lots,
    num("Сумма сделки") AS amount,
    num("Стартовая цена") AS start_price,
    TRY_CAST("Номер контракта" AS INTEGER) AS contract_id,
    "Наименование товара" AS product_name,
    num("Лот") AS lot,
    "Единица измерения" AS unit,
    "Регион" AS region_src,
    "Тип контракта" AS contract_type,
    "Форма контракта" AS contract_form,
    "Состояние сделки" AS status,
    "ИНН продавца" AS seller_inn, "ИНН покупателя" AS buyer_inn,
    "Брокер продавца" AS seller_broker, "Брокер покупателя" AS buyer_broker,
    dt("Дата оплаты") AS pay_date, dt("Дата поставки") AS delivery_date,
    num("Поставлено") AS delivered_lots
  FROM raw_deals)
SELECT
  d.deal_id, d.deal_date, d.deal_time,
  year(d.deal_date) AS year, month(d.deal_date) AS month, quarter(d.deal_date) AS quarter,
  d.trade_type, d.contract_type, d.contract_form, d.status,
  (d.status <> 'Аннулирован(Не оплачен)') AS not_cancelled,
  (d.status IN ('Оплачен','Исполнен','Исполнен(Частично)')) AS is_paid,
  (d.status IN ('Исполнен','Исполнен(Частично)')) AS is_executed,
  d.contract_id, d.product_name, norm_name(d.product_name) AS product_name_norm,
  c.product_key, c.tnved, c.product_group, c.product_group_uz,
  grade_of(d.product_name) AS grade, class_of(d.product_name) AS class,
  c.category, c.industry, c.liquidity_group,
  d.unit, d.lot, d.qty_lots,
  d.qty_lots * d.lot AS volume,
  c.currency, d.amount, d.start_price,
  d.amount / NULLIF(d.qty_lots * d.lot, 0) AS unit_price,
  u.usd_rate,
  CASE WHEN c.currency='USD' THEN d.amount * u.usd_rate ELSE d.amount END AS amount_uzs,
  CASE WHEN c.currency='USD' THEN d.amount ELSE d.amount / u.usd_rate END AS amount_usd,
  CASE WHEN c.currency='USD' THEN d.amount / NULLIF(d.qty_lots * d.lot, 0) * u.usd_rate
       ELSE d.amount / NULLIF(d.qty_lots * d.lot, 0) END AS unit_price_uzs,
  r.region_code, r.region_ru, r.region_uz,
  d.seller_inn, ps.name AS seller_name, ps.region_ru AS seller_region_ru, ps.activity AS seller_activity,
  d.buyer_inn, pb.name AS buyer_name, pb.region_ru AS buyer_region_ru, pb.activity AS buyer_activity,
  d.seller_broker, bs.broker_name AS seller_broker_name,
  d.buyer_broker, bb.broker_name AS buyer_broker_name,
  d.pay_date, d.delivery_date, d.delivered_lots,
  d.delivered_lots * d.lot AS delivered_volume,
  c.pay_term_days, c.delivery_term_days,
  d.deal_date + c.pay_term_days AS pay_due_date,
  d.pay_date + c.delivery_term_days AS delivery_due_date,
  date_diff('day', d.deal_date, d.pay_date) AS days_to_pay,
  date_diff('day', d.pay_date, d.delivery_date) AS days_to_deliver,
  c.delivery_basis, c.packaging, c.deposit_pct, c.base_price,
  c.brand, c.size, c.kind
FROM d
LEFT JOIN contracts c ON c.contract_id = d.contract_id
LEFT JOIN usd_rates u ON u.rate_date = d.deal_date
LEFT JOIN regions r ON r.region_uz = d.region_src
LEFT JOIN participants ps ON ps.inn = d.seller_inn
LEFT JOIN participants pb ON pb.inn = d.buyer_inn
LEFT JOIN brokers bs ON bs.broker_code = d.seller_broker
LEFT JOIN brokers bb ON bb.broker_code = d.buyer_broker
ORDER BY d.deal_id""")

# справочник конкретных наименований товаров (для поиска)
con.execute("""CREATE TABLE product_names AS
SELECT product_name, any_value(product_name_norm) AS product_name_norm, product_key, any_value(product_group) AS product_group,
       any_value(grade) AS grade, any_value(class) AS class, any_value(unit) AS unit, count(*) AS deals
FROM deals GROUP BY product_name, product_key""")

# контроль качества
checks = {
  'deals': "SELECT count(*) FROM deals",
  'null_date': "SELECT count(*) FROM deals WHERE deal_date IS NULL",
  'null_amount': "SELECT count(*) FROM deals WHERE amount IS NULL",
  'null_region': "SELECT count(*) FROM deals WHERE region_code IS NULL",
  'null_group': "SELECT count(*) FROM deals WHERE product_group IS NULL",
  'null_rate': "SELECT count(*) FROM deals WHERE usd_rate IS NULL",
  'null_seller': "SELECT count(*) FROM deals WHERE seller_name IS NULL",
  'null_buyer': "SELECT count(*) FROM deals WHERE buyer_name IS NULL",
  'null_brokers': "SELECT count(*) FROM deals WHERE seller_broker_name IS NULL OR buyer_broker_name IS NULL",
  'contracts_null_region': "SELECT count(*) FROM contracts WHERE region_code IS NULL",
  'participants_null_region': "SELECT count(*) FROM participants WHERE region_code IS NULL",
  'currency_mismatch': "SELECT count(*) FROM deals WHERE (contract_type='Экспортный') <> (currency='USD')",
  'lot_mismatch': "SELECT count(*) FROM deals d JOIN contracts c USING(contract_id) WHERE d.lot <> c.lot",
}
for k, q in checks.items():
    print(f'{k:28s}', con.execute(q).fetchone()[0])

for y in range(2022, 2027):
    con.execute(f"COPY (SELECT * FROM deals WHERE year={y}) TO '{OUT}/deals_{y}.parquet' (FORMAT parquet, COMPRESSION zstd)")
for t in ['contracts', 'participants', 'brokers', 'usd_rates', 'regions', 'product_groups', 'product_names']:
    con.execute(f"COPY {t} TO '{OUT}/{t}.parquet' (FORMAT parquet, COMPRESSION zstd)")
print('written to', os.path.abspath(OUT))
