import sqlite3
import os
from datetime import datetime

# Railway: mount a volume at /data for persistence
# Local: uses ./data/rates.db
DB_PATH = os.environ.get(
    "DATABASE_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "rates.db")
)

def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rates (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT    NOT NULL,
            currency  TEXT    NOT NULL,
            buy       REAL,
            sell      REAL,
            source    TEXT    NOT NULL DEFAULT 'sp-today'
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_rates_currency_time
        ON rates (currency, timestamp)
    """)
    conn.commit()
    conn.close()
    print(f"✅ Database ready: {DB_PATH}")

def save_rate(currency: str, buy: float, sell: float, source: str = "sp-today"):
    conn = get_connection()
    conn.execute(
        "INSERT INTO rates (timestamp, currency, buy, sell, source) VALUES (?, ?, ?, ?, ?)",
        (datetime.utcnow().isoformat(), currency, buy, sell, source),
    )
    conn.commit()
    conn.close()

def get_latest(currency: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM rates WHERE currency=? ORDER BY timestamp DESC LIMIT 1",
        (currency,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def get_available_currencies() -> list[str]:
    conn  = get_connection()
    rows  = conn.execute("SELECT DISTINCT currency FROM rates ORDER BY currency").fetchall()
    conn.close()
    return [r["currency"] for r in rows]

def get_history(currency: str, limit: int = 10000):
    conn = get_connection()
    rows = conn.execute(
        "SELECT timestamp, buy, sell FROM rates WHERE currency=? ORDER BY timestamp DESC LIMIT ?",
        (currency, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]
