"""DuckDB в памяти: загружает Parquet один раз на процесс, выполняет только SELECT с таймаутом."""
import os, re, threading, datetime, decimal
import duckdb

DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(__file__), '..', 'data'))
TABLES = ['deals', 'contracts', 'participants', 'brokers', 'usd_rates', 'regions', 'product_groups', 'product_names']

_con = None
_lock = threading.Lock()


def get_con():
    global _con
    if _con is None:
        with _lock:
            if _con is None:
                con = duckdb.connect(':memory:')
                con.execute("SET threads=2")
                con.execute("SET enable_progress_bar=false")
                for t in TABLES:
                    src = f'{DATA_DIR}/deals_*.parquet' if t == 'deals' else f'{DATA_DIR}/{t}.parquet'
                    con.execute(f"CREATE TABLE {t} AS SELECT * FROM read_parquet('{src}') ORDER BY deal_id" if t == 'deals' else
                                f"CREATE TABLE {t} AS SELECT * FROM read_parquet('{src}')")
                con.execute("SET enable_external_access=false")
                con.execute("SET lock_configuration=true")
                _con = con
    return _con


FORBIDDEN = re.compile(r'\b(insert|update|delete|drop|create|alter|attach|detach|copy|export|import|install|load|pragma|set|call|checkpoint|vacuum)\b', re.I)


class SQLError(Exception):
    pass


def _clean(v):
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.strftime('%d.%m.%Y')
    return v


def run_sql(sql: str, max_rows: int = 60, timeout_s: float = 8.0):
    s = sql.strip().rstrip(';')
    if ';' in s:
        raise SQLError('Only one statement allowed')
    if not re.match(r'^\s*(with|select|from)\b', s, re.I):
        raise SQLError('Only SELECT queries are allowed')
    if FORBIDDEN.search(re.sub(r"'[^']*'", "''", s)):
        raise SQLError('Only read-only SELECT queries are allowed')
    cur = get_con().cursor()
    timer = threading.Timer(timeout_s, cur.interrupt)
    timer.start()
    try:
        rel = cur.execute(s)
        cols = [d[0] for d in rel.description]
        rows = rel.fetchmany(max_rows + 1)
    except duckdb.InterruptException:
        raise SQLError(f'Query timed out after {timeout_s}s — simplify it')
    except duckdb.Error as e:
        raise SQLError(str(e).split('\n')[0][:400])
    finally:
        timer.cancel()
        cur.close()
    truncated = len(rows) > max_rows
    rows = [[_clean(v) for v in r] for r in rows[:max_rows]]
    return {'columns': cols, 'rows': rows, 'row_count': len(rows), 'truncated': truncated}
