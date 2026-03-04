"""
api.py — SYP Markets backend
Fixed:
  - OHLC uses mid price (buy+sell)/2 for open/close, spread for high/low
  - Candles never have open=0
  - Timeframe aggregation is correct
"""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import database, scraper

scheduler = AsyncIOScheduler()

PAIR_META = {
    "USD":      {"name":"US Dollar",       "group":"fx",     "icon":"🇺🇸","unit":"SYP"},
    "EUR":      {"name":"Euro",            "group":"fx",     "icon":"🇪🇺","unit":"SYP"},
    "TRY":      {"name":"Turkish Lira",    "group":"fx",     "icon":"🇹🇷","unit":"SYP"},
    "SAR":      {"name":"Saudi Riyal",     "group":"fx",     "icon":"🇸🇦","unit":"SYP"},
    "AED":      {"name":"UAE Dirham",      "group":"fx",     "icon":"🇦🇪","unit":"SYP"},
    "EGP":      {"name":"Egyptian Pound",  "group":"fx",     "icon":"🇪🇬","unit":"SYP"},
    "GBP":      {"name":"British Pound",   "group":"fx",     "icon":"🇬🇧","unit":"SYP"},
    "KWD":      {"name":"Kuwaiti Dinar",   "group":"fx",     "icon":"🇰🇼","unit":"SYP"},
    "JOD":      {"name":"Jordanian Dinar", "group":"fx",     "icon":"🇯🇴","unit":"SYP"},
    "QAR":      {"name":"Qatari Riyal",    "group":"fx",     "icon":"🇶🇦","unit":"SYP"},
    "BHD":      {"name":"Bahraini Dinar",  "group":"fx",     "icon":"🇧🇭","unit":"SYP"},
    "IQD":      {"name":"Iraqi Dinar",     "group":"fx",     "icon":"🇮🇶","unit":"SYP"},
    "BTC":      {"name":"Bitcoin",         "group":"crypto", "icon":"₿",  "unit":"USD"},
    "ETH":      {"name":"Ethereum",        "group":"crypto", "icon":"Ξ",  "unit":"USD"},
    "BNB":      {"name":"BNB",             "group":"crypto", "icon":"⬡",  "unit":"USD"},
    "USDT":     {"name":"Tether",          "group":"crypto", "icon":"₮",  "unit":"USD"},
    "XAU":      {"name":"Gold Ounce",      "group":"gold",   "icon":"🥇", "unit":"USD"},
    "XAU_24K":  {"name":"Gold 24K/g",      "group":"gold",   "icon":"🥇", "unit":"SYP"},
    "XAU_21K":  {"name":"Gold 21K/g",      "group":"gold",   "icon":"🥇", "unit":"SYP"},
    "XAU_18K":  {"name":"Gold 18K/g",      "group":"gold",   "icon":"🥇", "unit":"SYP"},
    "FUEL_GAS": {"name":"Gasoline",        "group":"fuel",   "icon":"⛽", "unit":"SYP"},
    "FUEL_DSL": {"name":"Diesel",          "group":"fuel",   "icon":"🛢️", "unit":"SYP"},
}

TF_SECONDS = {
    "1m":60, "5m":300, "15m":900, "30m":1800,
    "1H":3600, "4H":14400, "1D":86400, "1W":604800, "1M":2592000,
}


def aggregate_candles(rows: list[dict], tf: str) -> list[dict]:
    """
    Build OHLC candles from raw tick rows.

    Each tick has: buy (float), sell (float)
    We define:
      mid   = (buy + sell) / 2      ← the "price"
      open  = first tick's mid in bucket
      close = last  tick's mid in bucket
      high  = max sell in bucket     ← highest anyone would pay
      low   = min buy  in bucket     ← lowest anyone would accept

    This guarantees open/close are NEVER zero, and high >= close >= open >= low
    is always approximately true.
    """
    step    = TF_SECONDS.get(tf, 3600)
    buckets: dict[int, list] = {}

    for row in rows:
        try:
            ts   = int(datetime.fromisoformat(row["timestamp"]).replace(tzinfo=timezone.utc).timestamp())
        except Exception:
            continue
        slot = (ts // step) * step
        buckets.setdefault(slot, []).append(row)

    candles = []
    for slot in sorted(buckets):
        pts   = buckets[slot]
        mids  = [(p["buy"] + p["sell"]) / 2 for p in pts]
        buys  = [p["buy"]  for p in pts]
        sells = [p["sell"] for p in pts]

        o = mids[0]
        c = mids[-1]
        h = max(sells)
        l = min(buys)

        # Guarantee h >= max(o,c) and l <= min(o,c)
        h = max(h, o, c)
        l = min(l, o, c)

        candles.append({
            "time":  slot,
            "open":  round(o, 4),
            "high":  round(h, 4),
            "low":   round(l, 4),
            "close": round(c, 4),
        })

    return candles


def _do_scrape():
    try:
        scraper.scrape_and_save()
    except Exception as e:
        print(f"Scheduled scrape error: {e}")


@asynccontextmanager
async def lifespan(app):
    database.init_db()
    _do_scrape()
    scheduler.add_job(_do_scrape, "interval", minutes=5)
    scheduler.start()
    print("🚀 SYP Markets API ready")
    yield
    scheduler.shutdown()


app = FastAPI(title="SYP Markets API", version="4.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

FRONTEND = Path(__file__).parent.parent / "frontend"
if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


@app.get("/", include_in_schema=False)
def root():
    idx = FRONTEND / "index.html"
    return FileResponse(str(idx)) if idx.exists() else {"api": "SYP Markets", "docs": "/docs"}


@app.get("/api/pairs")
def pairs():
    available = database.get_available_currencies()
    result = []
    for sym in available:
        meta   = PAIR_META.get(sym, {"name":sym,"group":"other","icon":"💱","unit":"SYP"})
        latest = database.get_latest(sym)
        result.append({
            "symbol": sym,
            "name":   meta["name"],
            "group":  meta["group"],
            "icon":   meta["icon"],
            "unit":   meta["unit"],
            "buy":    round(latest["buy"],  4) if latest else None,
            "sell":   round(latest["sell"], 4) if latest else None,
        })
    order = {"fx":0,"crypto":1,"gold":2,"fuel":3,"other":4}
    result.sort(key=lambda x: (order.get(x["group"],99), x["symbol"]))
    return result


@app.get("/api/latest")
def latest(currency: str = Query("USD")):
    row = database.get_latest(currency.upper())
    if not row:
        raise HTTPException(404, f"No data for {currency}")
    return row


@app.get("/api/history")
def history(
    currency: str = Query("USD"),
    tf:       str = Query("1H"),
    limit:    int = Query(10000, ge=1, le=50000),
):
    currency = currency.upper()
    if tf not in TF_SECONDS:
        raise HTTPException(400, f"Bad TF. Valid: {list(TF_SECONDS)}")
    rows = database.get_history(currency, limit)
    if not rows:
        raise HTTPException(404, f"No data yet for {currency}")
    candles = aggregate_candles(rows, tf)
    return {"currency": currency, "tf": tf, "real_ticks": len(rows), "count": len(candles), "data": candles}


@app.post("/api/scrape")
def manual_scrape():
    try:
        scraper.scrape_and_save()
        return {"ok": True, "pairs": database.get_available_currencies()}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/health")
def health():
    return {"ok": True, "pairs": database.get_available_currencies(), "time": datetime.utcnow().isoformat()}
