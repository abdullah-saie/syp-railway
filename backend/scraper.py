"""
scraper.py — sp-today.com + CoinGecko
Completely rewritten with:
  - Tight price validation per currency (realistic SYP ranges)
  - Proper buy/sell extraction using page structure
  - No mixing USD prices into SYP fields
  - Debug logging to catch bad parses early
"""

import re, httpx
from bs4 import BeautifulSoup
from database import save_rate

BASE      = "https://sp-today.com"
COINGECKO = "https://api.coingecko.com/api/v3"

HEADERS = {
    "User-Agent":      "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
    "Referer":         "https://sp-today.com/en",
}

# ── Currency config ───────────────────────────────────────────────────────
# slug → (symbol, min_syp, max_syp)
# These ranges are the ONLY acceptable SYP values — anything outside is rejected
FX = {
    "us-dollar":       ("USD",  8_000,    25_000),
    "euro":            ("EUR",  9_000,    30_000),
    "turkish-lira":    ("TRY",  100,      1_500),
    "saudi-riyal":     ("SAR",  1_500,    8_000),
    "uae-dirham":      ("AED",  1_500,    8_000),
    "egyptian-pound":  ("EGP",  80,       500),
    "british-pound":   ("GBP", 10_000,    35_000),
    "kuwaiti-dinar":   ("KWD", 25_000,    80_000),
    "jordanian-dinar": ("JOD",  8_000,    30_000),
    "qatari-riyal":    ("QAR",  1_500,    7_000),
    "bahraini-dinar":  ("BHD", 20_000,    65_000),
    "iraqi-dinar":     ("IQD",  1,        20),
}

# Gold gram in SYP (per karat)
GOLD_GRAM = {
    "24k": ("XAU_24K", 1_500_000, 3_500_000),
    "21k": ("XAU_21K", 1_000_000, 3_000_000),
    "18k": ("XAU_18K",   800_000, 2_500_000),
}

# Gold ounce in USD
GOLD_OZ_USD_MIN, GOLD_OZ_USD_MAX = 1_500, 5_000

# Fuel SYP per liter
FUEL = {
    "benzin": ("FUEL_GAS", 3_000, 50_000),
    "diesel": ("FUEL_DSL", 3_000, 50_000),
}


def _clean(text: str) -> str:
    return re.sub(r"[^\d.]", "", text.replace(",", ""))

def _num(text) -> float | None:
    try:
        v = float(_clean(str(text)))
        return v if v > 0 else None
    except:
        return None

def _in_range(v, lo, hi):
    return v is not None and lo <= v <= hi

def _fetch(client, url):
    r = client.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


# ── Core price extractor ──────────────────────────────────────────────────

def _extract_buy_sell(soup: BeautifulSoup, sym: str, lo: float, hi: float):
    """
    Extract buy and sell price from an sp-today page.
    Returns (buy, sell) or (None, None).

    sp-today page structure (observed):
      - Two large numbers shown as buy / sell in a price card
      - Often inside <span> or <div> with classes like:
          'price', 'buy', 'sell', 'value', 'number', 'rate'
      - Sometimes in a <table> with Buy/Sell headers
    We try multiple approaches and validate each number against [lo, hi].
    """

    candidates = []

    # Pass 1 — elements whose class/id hints at price
    PRICE_HINTS = re.compile(
        r'price|rate|value|buy|sell|bid|ask|exchange|number|amount|figure|cours',
        re.I
    )
    for el in soup.find_all(True):
        cls = " ".join(el.get("class", []))
        iid = el.get("id", "")
        if PRICE_HINTS.search(cls) or PRICE_HINTS.search(iid):
            txt = el.get_text(separator=" ", strip=True)
            # Grab all numeric tokens from this element
            for tok in re.findall(r'[\d,]+(?:\.\d+)?', txt):
                v = _num(tok)
                if v and _in_range(v, lo, hi):
                    candidates.append(v)

    # Pass 2 — <td> and <th> cells (tables)
    for el in soup.find_all(['td', 'th']):
        txt = el.get_text(strip=True)
        v = _num(txt)
        if v and _in_range(v, lo, hi):
            candidates.append(v)

    # Pass 3 — large standalone text nodes in <span>/<p>/<div>/<h*>
    for el in soup.find_all(['span', 'p', 'div', 'h1', 'h2', 'h3', 'strong', 'b']):
        # Only look at leaf-ish elements (no deeply nested children)
        if len(el.find_all(True)) > 3:
            continue
        txt = el.get_text(strip=True)
        if len(txt) > 20:
            continue
        v = _num(txt)
        if v and _in_range(v, lo, hi):
            candidates.append(v)

    if not candidates:
        print(f"      ⚠️  {sym}: no candidates in [{lo:,.0f}–{hi:,.0f}]")
        return None, None

    candidates = sorted(set(candidates))

    # If we have exactly 2, those are buy/sell
    if len(candidates) == 2:
        return candidates[0], candidates[1]

    # If one number repeated, buy≈sell (stable rate)
    if len(candidates) == 1:
        return candidates[0], candidates[0]

    # Multiple — find the tightest valid pair (spread < 5%)
    for i in range(len(candidates) - 1):
        a, b = candidates[i], candidates[i+1]
        if b <= a * 1.05:
            return a, b

    # Wider spread up to 15%
    for i in range(len(candidates) - 1):
        a, b = candidates[i], candidates[i+1]
        if b <= a * 1.15:
            return a, b

    # Last resort: first and last
    return candidates[0], candidates[-1]


# ── FX ────────────────────────────────────────────────────────────────────

def scrape_fx(client) -> list[dict]:
    results = []
    for slug, (sym, lo, hi) in FX.items():
        bought = False
        for url in [f"{BASE}/en/currency/{slug}", f"{BASE}/currency/{slug}"]:
            try:
                soup = _fetch(client, url)
                buy, sell = _extract_buy_sell(soup, sym, lo, hi)
                if buy and sell:
                    results.append({"currency": sym, "buy": buy, "sell": sell, "source": "sp-today"})
                    print(f"  ✅ {sym}: buy={buy:,.2f}  sell={sell:,.2f}")
                    bought = True
                    break
            except Exception as e:
                print(f"      fetch err {sym} {url}: {e}")
        if not bought:
            print(f"  ❌ {sym}: skipped (no valid price found)")
    return results


# ── Gold grams (SYP) ──────────────────────────────────────────────────────

def scrape_gold_grams(client) -> list[dict]:
    results = []
    for slug, (sym, lo, hi) in GOLD_GRAM.items():
        for url in [f"{BASE}/en/gold/{slug}/syp", f"{BASE}/gold/{slug}"]:
            try:
                soup = _fetch(client, url)
                buy, sell = _extract_buy_sell(soup, sym, lo, hi)
                if buy and sell:
                    results.append({"currency": sym, "buy": buy, "sell": sell, "source": "sp-today-gold"})
                    print(f"  ✅ {sym}: buy={buy:,.0f}  sell={sell:,.0f}")
                    break
            except Exception as e:
                continue
        else:
            print(f"  ❌ {sym}: skipped")
    return results


# ── Gold ounce (USD) ──────────────────────────────────────────────────────

def scrape_gold_ounce(client) -> list[dict]:
    for url in [f"{BASE}/en/gold/ounce", f"{BASE}/gold/ounce"]:
        try:
            soup  = _fetch(client, url)
            # Look for USD amount in realistic range
            text  = soup.get_text(separator=" ")
            nums  = [n for raw in re.findall(r'[\d,]+(?:\.\d+)?', text)
                     if (n := _num(raw)) and _in_range(n, GOLD_OZ_USD_MIN, GOLD_OZ_USD_MAX)]
            if nums:
                price = sorted(nums)[0]
                print(f"  ✅ XAU: ${price:,.2f}")
                return [{"currency": "XAU", "buy": price, "sell": price, "source": "sp-today-gold"}]
        except Exception as e:
            continue
    print("  ❌ XAU: skipped")
    return []


# ── Fuel (SYP/liter) ──────────────────────────────────────────────────────

def scrape_fuel(client) -> list[dict]:
    results = []
    for slug, (sym, lo, hi) in FUEL.items():
        for url in [f"{BASE}/en/energy/{slug}", f"{BASE}/energy/{slug}"]:
            try:
                soup = _fetch(client, url)
                buy, sell = _extract_buy_sell(soup, sym, lo, hi)
                if buy:
                    price = buy
                    results.append({"currency": sym, "buy": price, "sell": price, "source": "sp-today-fuel"})
                    print(f"  ✅ {sym}: {price:,.0f} SYP")
                    break
            except Exception as e:
                continue
        else:
            print(f"  ❌ {sym}: skipped")
    return results


# ── Crypto (USD prices via CoinGecko) ─────────────────────────────────────
# Stored as USD — frontend knows to show "USD" unit for crypto

CRYPTO_IDS = {
    "bitcoin":     "BTC",
    "ethereum":    "ETH",
    "binancecoin": "BNB",
    "tether":      "USDT",
}

def scrape_crypto(client) -> list[dict]:
    results = []
    try:
        r = client.get(
            f"{COINGECKO}/simple/price",
            params={"ids": ",".join(CRYPTO_IDS), "vs_currencies": "usd"},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        for cg_id, sym in CRYPTO_IDS.items():
            price = data.get(cg_id, {}).get("usd")
            if price and price > 0:
                results.append({"currency": sym, "buy": float(price), "sell": float(price), "source": "coingecko"})
                print(f"  ✅ {sym}: ${price:,.2f}")
    except Exception as e:
        print(f"  ❌ Crypto: {e}")
    return results


# ── Entry point ───────────────────────────────────────────────────────────

def scrape_and_save():
    print("🔄 Scraping all pairs...")
    all_results = []

    with httpx.Client(follow_redirects=True) as client:
        print("── FX ──")
        all_results += scrape_fx(client)
        print("── Gold grams ──")
        all_results += scrape_gold_grams(client)
        print("── Gold ounce ──")
        all_results += scrape_gold_ounce(client)
        print("── Fuel ──")
        all_results += scrape_fuel(client)
        print("── Crypto ──")
        all_results += scrape_crypto(client)

    saved = 0
    for r in all_results:
        save_rate(r["currency"], r["buy"], r["sell"], r.get("source", "sp-today"))
        saved += 1

    print(f"\n✅ Scrape complete — {saved}/{len(all_results)} saved.")
    return all_results


if __name__ == "__main__":
    from database import init_db
    init_db()
    scrape_and_save()
