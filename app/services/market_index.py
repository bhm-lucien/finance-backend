"""
大盤指標服務 — 台指期 + 美股三大指數
使用 Yahoo Finance REST API（不依賴 yfinance 套件，避免雲端被擋）
"""
import time
import requests

# 快取（60 秒）
_market_cache: dict[str, dict] = {}
CACHE_TTL = 60

# 指數代碼對應
MARKET_SYMBOLS = {
    "taiex_futures": {"symbol": "^TWII", "name": "台指期", "display": "台指期"},
    "dow_jones": {"symbol": "^DJI", "name": "道瓊工業", "display": "道瓊"},
    "sp500": {"symbol": "^GSPC", "name": "S&P 500", "display": "S&P500"},
    "nasdaq": {"symbol": "^IXIC", "name": "那斯達克", "display": "那斯達克"},
    "sox": {"symbol": "^SOX", "name": "費半指數", "display": "費半"},
}


def fetch_market_indices() -> list:
    """
    取得所有大盤指標的最新報價

    Returns:
        list of dict，每個包含 name, price, change, change_pct
    """
    cache_key = "market_indices"
    if cache_key in _market_cache:
        entry = _market_cache[cache_key]
        if time.time() - entry["time"] < CACHE_TTL:
            return entry["data"]

    results = []

    for key, info in MARKET_SYMBOLS.items():
        try:
            data = _fetch_quote_direct(info["symbol"])
            results.append({
                "key": key,
                "name": info["display"],
                "full_name": info["name"],
                "price": data.get("price", 0),
                "change": data.get("change", 0),
                "change_pct": data.get("change_pct", 0),
            })
        except Exception as e:
            results.append({
                "key": key,
                "name": info["display"],
                "full_name": info["name"],
                "price": 0,
                "change": 0,
                "change_pct": 0,
            })

    _market_cache[cache_key] = {"data": results, "time": time.time()}
    return results


def _fetch_quote_direct(symbol: str) -> dict:
    """
    直接用 Yahoo Finance v8 chart API 取報價
    不依賴 yfinance 套件，避免雲端 IP 被封鎖
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code != 200:
            return {"price": 0, "change": 0, "change_pct": 0}

        data = response.json()
        chart = data.get("chart", {}).get("result", [])
        if not chart:
            return {"price": 0, "change": 0, "change_pct": 0}

        meta = chart[0].get("meta", {})
        price = float(meta.get("regularMarketPrice", 0))
        prev_close = float(
            meta.get("chartPreviousClose", 0) or meta.get("previousClose", 0)
        )

        if price == 0:
            return {"price": 0, "change": 0, "change_pct": 0}

        change = round(price - prev_close, 2) if prev_close > 0 else 0
        change_pct = round(change / prev_close * 100, 2) if prev_close > 0 else 0

        return {
            "price": round(price, 2),
            "change": change,
            "change_pct": change_pct,
        }

    except Exception:
        return {"price": 0, "change": 0, "change_pct": 0}
