"""
大盤指標服務 — 台指期 + 美股三大指數
使用 yfinance 取得最新報價
"""
import time
import yfinance as yf

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
            ticker = yf.Ticker(info["symbol"])
            # 取得最新報價
            fast_info = ticker.fast_info

            price = float(fast_info.get("lastPrice", 0) or fast_info.get("last_price", 0))
            prev_close = float(fast_info.get("previousClose", 0) or fast_info.get("previous_close", 0))

            if price == 0:
                # 備用：從 history 取
                hist = ticker.history(period="2d")
                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])
                    if len(hist) > 1:
                        prev_close = float(hist["Close"].iloc[-2])

            change = round(price - prev_close, 2) if prev_close > 0 else 0
            change_pct = round(change / prev_close * 100, 2) if prev_close > 0 else 0

            results.append({
                "key": key,
                "name": info["display"],
                "full_name": info["name"],
                "price": round(price, 2),
                "change": change,
                "change_pct": change_pct,
            })
        except Exception as e:
            results.append({
                "key": key,
                "name": info["display"],
                "full_name": info["name"],
                "price": 0,
                "change": 0,
                "change_pct": 0,
                "error": str(e),
            })

    _market_cache[cache_key] = {"data": results, "time": time.time()}
    return results
