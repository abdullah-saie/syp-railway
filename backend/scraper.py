"""
scraper.py — fetches all pairs from sp-today.com + CoinGecko
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


def _num(text) -> float | None:
    try:
        return float(str(text).replace(",", "").strip())
    except:
        return None


def _extract_buy_sell(soup):
    text    = soup.get_text(separator=" ")
    numbers = re.findall(r"[\d,]{3,}", text)
    cleaned = sorted(set(
        n for raw in numbers if (n := _num(raw)) and n > 100
    ))
    if len(cleaned) >= 2:
        return cleaned[0], cleaned[1]
    return None, None


def scrape_fx(client):
    results = []
    for slug, symbol in FX_CURRENCIES.items():
        try:
            r = client.get(f"{BASE}/en/currency/{slug}", headers=HEADERS, timeout=12)
            r.raise_for_status()
            buy, sell = _extract_buy_sell(BeautifulSoup(r.text, "html.parser"))
            if buy and sell:
                results.append({"currency": symbol, "buy": buy, "sell": sell, "source": "sp-today"})
                print(f"  ✅ {symbol}: {buy}/{sell}")
            else:
                print(f"  ⚠️  {symbol}: parse failed")
        except Exception as e:
            print(f"  ❌ {symbol}: {e}")
    return results


def scrape_gold(client):
    results = []
    for slug, symbol in GOLD_SLUGS.items():
        try:
            r = client.get(f"{BASE}/en/gold/{slug}/syp", headers=HEADERS, timeout=12)
            r.raise_for_status()
            buy, sell = _extract_buy_sell(BeautifulSoup(r.text, "html.parser"))
            if buy and sell:
                results.append({"currency": symbol, "buy": buy, "sell": sell, "source": "sp-today-gold"})
                print(f"  ✅ {symbol}: {buy}/{sell}")
        except Exception as e:
            print(f"  ❌ {symbol}: {e}")
    # Gold ounce
    try:
        r = client.get(f"{BASE}/en/gold/ounce", headers=HEADERS, timeout=12)
        r.raise_for_status()
        text  = BeautifulSoup(r.text, "html.parser").get_text(separator=" ")
        nums  = re.findall(r"[\d,]+\.?\d*", text)
        clean = [n for raw in nums if (n := _num(raw)) and 1000 < n < 100000]
        if clean:
            results.append({"currency": "XAU", "buy": clean[0], "sell": clean[0], "source": "sp-today-gold"})
            print(f"  ✅ XAU: ${clean[0]}")
    except Exception as e:
        print(f"  ❌ XAU: {e}")
    return results


def scrape_fuel(client):
    results = []
    for slug, symbol in FUEL_SLUGS.items():
        try:
            r = client.get(f"{BASE}/en/energy/{slug}", headers=HEADERS, timeout=12)
            r.raise_for_status()
            text    = BeautifulSoup(r.text, "html.parser").get_text(separator=" ")
            numbers = re.findall(r"[\d,]{3,}", text)
            cleaned = [n for raw in numbers if (n := _num(raw)) and n > 1000]
            if cleaned:
                results.append({"currency": symbol, "buy": cleaned[0], "sell": cleaned[0], "source": "sp-today-fuel"})
                print(f"  ✅ {symbol}: {cleaned[0]}")
        except Exception as e:
            print(f"  ❌ {symbol}: {e}")
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
                print(f"  ✅ {symbol}: ${price}")
    except Exception as e:
        print(f"  ❌ Crypto: {e}")
    return results


def scrape_and_save():
    print("🔄 Scraping...")
    all_results = []
    with httpx.Client(follow_redirects=True) as client:
        all_results += scrape_fx(client)
        all_results += scrape_gold(client)
        all_results += scrape_fuel(client)
        all_results += scrape_crypto(client)

    for r in all_results:
        save_rate(r["currency"], r["buy"], r["sell"], r.get("source", "sp-today"))

    print(f"✅ Scrape done — {len(all_results)} pairs saved.")
    return all_results


if __name__ == "__main__":
    from database import init_db
    init_db()
    scrape_and_save()
