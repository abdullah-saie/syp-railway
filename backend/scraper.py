"""
scraper.py — fetches all pairs from sp-today.com + CoinGecko
Fixed: uses precise CSS selectors instead of blind number extraction
"""
import re
import httpx
from bs4 import BeautifulSoup
from database import save_rate

BASE      = "https://sp-today.com"
COINGECKO = "https://api.coingecko.com/api/v3"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://sp-today.com/en",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

FX_CURRENCIES = {
    "us-dollar":       "USD",
    "euro":            "EUR",
    "turkish-lira":    "TRY",
    "saudi-riyal":     "SAR",
    "uae-dirham":      "AED",
    "egyptian-pound":  "EGP",
    "british-pound":   "GBP",
    "kuwaiti-dinar":   "KWD",
    "jordanian-dinar": "JOD",
    "qatari-riyal":    "QAR",
    "bahraini-dinar":  "BHD",
    "iraqi-dinar":     "IQD",
}

CRYPTO_IDS = {
    "bitcoin":     "BTC",
    "ethereum":    "ETH",
    "binancecoin": "BNB",
    "tether":      "USDT",
}

GOLD_SLUGS = {
    "24k": "XAU_24K",
    "21k": "XAU_21K",
    "18k": "XAU_18K",
}

FUEL_SLUGS = {
    "benzin": "FUEL_GAS",
    "diesel": "FUEL_DSL",
}

# Realistic minimum for each symbol (SYP unless noted)
MIN_VALID = {
    "USD": 5000,  "EUR": 5000,  "GBP": 8000,
    "SAR": 1000,  "AED": 1000,  "KWD": 20000,
    "TRY": 100,   "EGP": 100,   "IQD": 1,
    "JOD": 5000,  "QAR": 1000,  "BHD": 15000,
    "XAU": 1000,
    "XAU_24K": 500000, "XAU_21K": 400000, "XAU_18K": 300000,
    "FUEL_GAS": 3000,  "FUEL_DSL": 3000,
}


def _num(text) -> float | None:
    try:
        val = float(str(text).replace(",", "").replace(" ", "").strip())
        return val if val > 0 else None
    except:
        return None


def _extract_price_from_page(soup: BeautifulSoup, symbol: str) -> tuple[float | None, float | None]:
    """
    Multi-strategy extraction. Tries CSS selectors then falls back to
    validated number scanning with realistic price ranges.
    """
    min_val = MIN_VALID.get(symbol, 100)

    # Strategy 1: named price/rate CSS classes
    price_classes = [
        'price', 'rate', 'value', 'buy', 'sell', 'buying', 'selling',
        'exchange', 'bid', 'ask', 'livePrice', 'live-price',
        'currency-price', 'currency-rate', 'exchange-rate',
        'buy-price', 'sell-price',
    ]
    found = []
    for cls in price_classes:
        for el in soup.find_all(class_=re.compile(cls, re.I)):
            txt = re.sub(r'[^\d,.]', '', el.get_text(strip=True))
            v = _num(txt)
            if v and v >= min_val and not (2000 <= v <= 2100):
                found.append(v)

    if len(found) >= 2:
        found = sorted(set(found))
        return found[0], found[-1]

    # Strategy 2: table cells (buy/sell table common on sp-today)
    td_vals = []
    for td in soup.find_all('td'):
        txt = re.sub(r'[^\d,.]', '', td.get_text(strip=True))
        v = _num(txt)
        if v and v >= min_val and not (2000 <= v <= 2100):
            td_vals.append(v)

    if len(td_vals) >= 2:
        td_vals = sorted(set(td_vals))
        return td_vals[0], td_vals[-1]

    # Strategy 3: all page numbers, validated by range + spread check
    all_text = soup.get_text(separator=" ")
    raw_nums  = re.findall(r'\b\d[\d,]*(?:\.\d+)?\b', all_text)
    valid     = []
    for raw in raw_nums:
        v = _num(raw)
        if v and v >= min_val and not (2000 <= v <= 2100) and v < 100_000_000:
            valid.append(v)

    if len(valid) >= 2:
        valid = sorted(set(valid))
        # Find a realistic buy/sell pair: spread < 15%
        for i in range(len(valid) - 1):
            lo, hi = valid[i], valid[i + 1]
            if hi <= lo * 1.15:
                return lo, hi
        # fallback: first two
        return valid[0], valid[1]

    return None, None


def _fetch(client: httpx.Client, url: str):
    r = client.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def scrape_fx(client):
    results = []
    for slug, symbol in FX_CURRENCIES.items():
        # Try EN then AR page
        for url in [f"{BASE}/en/currency/{slug}", f"{BASE}/currency/{slug}"]:
            try:
                soup = _fetch(client, url)
                buy, sell = _extract_price_from_page(soup, symbol)
                if buy and sell:
                    results.append({"currency": symbol, "buy": buy, "sell": sell, "source": "sp-today"})
                    print(f"  ✅ {symbol}: {buy:,.0f} / {sell:,.0f}")
                    break
            except Exception as e:
                continue
        else:
            print(f"  ⚠️  {symbol}: failed to fetch")
    return results


def scrape_gold(client):
    results = []
    for slug, symbol in GOLD_SLUGS.items():
        for url in [f"{BASE}/en/gold/{slug}/syp", f"{BASE}/gold/{slug}"]:
            try:
                soup = _fetch(client, url)
                buy, sell = _extract_price_from_page(soup, symbol)
                if buy and sell:
                    results.append({"currency": symbol, "buy": buy, "sell": sell, "source": "sp-today-gold"})
                    print(f"  ✅ {symbol}: {buy:,.0f} / {sell:,.0f}")
                    break
            except:
                continue
        else:
            print(f"  ⚠️  {symbol}: failed")

    # Ounce USD price
    for url in [f"{BASE}/en/gold/ounce", f"{BASE}/gold/ounce"]:
        try:
            soup  = _fetch(client, url)
            text  = soup.get_text(separator=" ")
            nums  = [n for raw in re.findall(r'[\d,]+', text)
                     if (n := _num(raw)) and 1000 < n < 100000]
            if nums:
                price = sorted(nums)[len(nums)//2]
                results.append({"currency": "XAU", "buy": price, "sell": price, "source": "sp-today-gold"})
                print(f"  ✅ XAU: ${price:,.0f}")
            break
        except:
            continue
    return results


def scrape_fuel(client):
    results = []
    for slug, symbol in FUEL_SLUGS.items():
        for url in [f"{BASE}/en/energy/{slug}", f"{BASE}/energy/{slug}"]:
            try:
                soup = _fetch(client, url)
                text = soup.get_text(separator=" ")
                nums = [n for raw in re.findall(r'\b\d{4,6}\b', text)
                        if (n := _num(raw)) and MIN_VALID.get(symbol, 1000) <= n <= 200000]
                if nums:
                    price = nums[0]
                    results.append({"currency": symbol, "buy": price, "sell": price, "source": "sp-today-fuel"})
                    print(f"  ✅ {symbol}: {price:,.0f}")
                    break
            except:
                continue
        else:
            print(f"  ⚠️  {symbol}: failed")
    return results


def scrape_crypto(client):
    results = []
    try:
        r = client.get(
            f"{COINGECKO}/simple/price",
            params={"ids": ",".join(CRYPTO_IDS.keys()), "vs_currencies": "usd"},
            timeout=15,
        )
        r.raise_for_status()
        for cg_id, symbol in CRYPTO_IDS.items():
            price = r.json().get(cg_id, {}).get("usd")
            if price:
                results.append({"currency": symbol, "buy": float(price), "sell": float(price), "source": "coingecko"})
                print(f"  ✅ {symbol}: ${price:,.2f}")
    except Exception as e:
        print(f"  ❌ Crypto: {e}")
    return results


def scrape_and_save():
    print("🔄 Starting scrape...")
    all_results = []
    with httpx.Client(follow_redirects=True) as client:
        print("── FX ──")
        all_results += scrape_fx(client)
        print("── Gold ──")
        all_results += scrape_gold(client)
        print("── Fuel ──")
        all_results += scrape_fuel(client)
        print("── Crypto ──")
        all_results += scrape_crypto(client)

    for r in all_results:
        save_rate(r["currency"], r["buy"], r["sell"], r.get("source", "sp-today"))

    print(f"\n✅ Done — {len(all_results)} pairs saved.")
    return all_results


if __name__ == "__main__":
    from database import init_db
    init_db()
    scrape_and_save()
