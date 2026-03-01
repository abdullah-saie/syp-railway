"""
api.py — FastAPI backend + static frontend serving
Railway-ready: reads PORT from env, serves frontend/index.html at /
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

import database
import scraper

scheduler = AsyncIOScheduler()

# ── Pair metadata ─────────────────────────────────────────────────────────
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


def aggregate_candles(rows, tf):
    step    = TF_SECONDS.get(tf, 3600)
    buckets = {}
    for row in rows:
        ts   = int(datetime.fromisoformat(row["timestamp"]).replace(tzinfo=timezone.utc).timestamp())
        slot = (ts // step) * step
        buckets.setdefault(slot, []).append({"buy": row["buy"], "sell": row["sell"]})
    candles = []
    for slot in sorted(buckets):
        pts = buckets[slot]
        buys, sells = [p["buy"] for p in pts], [p["sell"] for p in pts]
        candles.append({
            "time":  slot,
            "open":  buys[0],   "high": max(sells),
            "low":   min(buys), "close": sells[-1],
            "buy":   buys[-1],  "sell": sells[-1],
        })
    return candles


def scheduled_scrape():
    try:
        scraper.scrape_and_save()
    except Exception as e:
        print(f"Scheduler error: {e}")


@asynccontextmanager
async def lifespan(app):
    database.init_db()
    try:
        scraper.scrape_and_save()
    except Exception as e:
        print(f"Initial scrape error (non-fatal): {e}")
    scheduler.add_job(scheduled_scrape, "interval", minutes=5)
    scheduler.start()
    print("🚀 SYP Markets running")
    yield
    scheduler.shutdown()


# ── App ───────────────────────────────────────────────────────────────────
app = FastAPI(title="SYP Markets API", version="3.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static frontend files
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ── Routes ────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def serve_frontend():
    """Serve the frontend HTML app."""
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"message": "SYP Markets API", "docs": "/docs", "health": "/health"}


@app.get("/api/pairs")
def list_pairs():
    available = database.get_available_currencies()
    result = []
    for sym in available:
        meta   = PAIR_META.get(sym, {"name":sym,"group":"other","icon":"💱","unit":"SYP"})
        latest = database.get_latest(sym)
        result.append({
            "symbol": sym, "name": meta["name"], "group": meta["group"],
            "icon": meta["icon"], "unit": meta["unit"],
            "buy":  latest["buy"]  if latest else None,
            "sell": latest["sell"] if latest else None,
        })
    group_order = {"fx":0,"crypto":1,"gold":2,"fuel":3,"other":4}
    result.sort(key=lambda x: (group_order.get(x["group"],99), x["symbol"]))
    return result


@app.get("/api/latest")
def latest_rate(currency: str = Query(default="USD")):
    row = database.get_latest(currency.upper())
    if not row:
        raise HTTPException(404, f"No data for {currency}")
    return row


@app.get("/api/history")
def history(
    currency: str = Query(default="USD"),
    tf:       str = Query(default="1H"),
    limit:    int = Query(default=10000, ge=1, le=50000),
):
    currency = currency.upper()
    if tf not in TF_SECONDS:
        raise HTTPException(400, f"Invalid TF. Use: {list(TF_SECONDS.keys())}")
    rows = database.get_history(currency, limit=limit)
    if not rows:
        raise HTTPException(404, f"No data for {currency} yet — still collecting.")
    candles = aggregate_candles(rows, tf)
    return {"currency": currency, "tf": tf, "count": len(candles), "real_ticks": len(rows), "data": candles}


@app.post("/api/scrape")
def manual_scrape():
    try:
        scraper.scrape_and_save()
        return {"status": "ok", "pairs": database.get_available_currencies()}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/health")
def health():
    return {"status": "ok", "pairs": database.get_available_currencies(), "time": datetime.utcnow().isoformat()}
