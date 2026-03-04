import sqlite3, os
from datetime import datetime

DB_PATH = os.environ.get(
    "DATABASE_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "rates.db")
)

def _conn():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = _conn()
    c.execute("""
        CREATE TABLE IF NOT EXISTS rates (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT    NOT NULL,
            currency  TEXT    NOT NULL,
            buy       REAL    NOT NULL,
            sell      REAL    NOT NULL,
            source    TEXT    NOT NULL DEFAULT 'sp-today'
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx ON rates (currency, timestamp)")
    c.commit(); c.close()
    print(f"✅ DB ready: {DB_PATH}")

def save_rate(currency, buy, sell, source="sp-today"):
    c = _conn()
    c.execute(
        "INSERT INTO rates (timestamp,currency,buy,sell,source) VALUES (?,?,?,?,?)",
        (datetime.utcnow().isoformat(), currency, buy, sell, source)
    )
    c.commit(); c.close()

def get_latest(currency):
    c = _conn()
    row = c.execute(
        "SELECT * FROM rates WHERE currency=? ORDER BY timestamp DESC LIMIT 1",
        (currency,)
    ).fetchone()
    c.close()
    return dict(row) if row else None

def get_available_currencies():
    c = _conn()
    rows = c.execute("SELECT DISTINCT currency FROM rates ORDER BY currency").fetchall()
    c.close()
    return [r["currency"] for r in rows]

def get_history(currency, limit=10000):
    c = _conn()
    rows = c.execute(
        "SELECT timestamp,buy,sell FROM rates WHERE currency=? ORDER BY timestamp DESC LIMIT ?",
        (currency, limit)
    ).fetchall()
    c.close()
    return [dict(r) for r in reversed(rows)]
