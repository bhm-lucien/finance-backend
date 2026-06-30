"""
台指期夜盤資料服務
從期交所或 Yahoo Finance 取得台指期即時/收盤資料
"""
import time
import requests


_futures_cache: dict[str, dict] = {}
CACHE_TTL = 60  # 60 秒快取


def fetch_taiwan_futures() -> dict:
    """
    取得台指期資料（含夜盤）

    Returns:
        {
            "price": 22500,
            "change": 150,
            "change_pct": 0.67,
            "high": 22600,
            "low": 22300,
            "volume": 85000,
            "session": "夜盤" / "日盤" / "收盤",
            "time": "05:00:00",
        }
    """
    cache_key = "tw_futures"
    if cache_key in _futures_cache:
        entry = _futures_cache[cache_key]
        if time.time() - entry["time"] < CACHE_TTL:
            return entry["data"]

    result = _fetch_from_taifex()
    if result["price"] == 0:
        result = _fetch_from_yahoo_futures()

    _futures_cache[cache_key] = {"data": result, "time": time.time()}
    return result


def _fetch_from_taifex() -> dict:
    """從期交所取得台指期資料"""
    try:
        # 期交所即時行情 API
        url = "https://mis.taifex.com.tw/futures/api/getQuoteList"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json",
        }
        payload = {"MarketType": "0", "SymbolType": "F", "KindID": "1", "CID": "TXF"}

        response = requests.post(url, json=payload, headers=headers, timeout=10)
        data = response.json()

        if data.get("RtData") and data["RtData"].get("QuoteList"):
            quote = data["RtData"]["QuoteList"][0]
            price = float(quote.get("CLastPrice", 0) or 0)
            change = float(quote.get("CDiff", 0) or 0)
            change_pct = float(quote.get("CDiffRate", 0) or 0)
            high = float(quote.get("CHighPrice", 0) or 0)
            low = float(quote.get("CLowPrice", 0) or 0)
            volume = int(quote.get("CTotalVolume", 0) or 0)

            # 判斷盤別
            from datetime import datetime
            now = datetime.now()
            hour = now.hour
            if 15 <= hour or hour < 5:
                session = "夜盤"
            elif 8 <= hour < 14:
                session = "日盤"
            else:
                session = "收盤"

            if price > 0:
                return {
                    "price": price,
                    "change": change,
                    "change_pct": change_pct,
                    "high": high,
                    "low": low,
                    "volume": volume,
                    "session": session,
                    "time": quote.get("CTime", "--:--:--"),
                }

    except Exception:
        pass

    return {"price": 0, "change": 0, "change_pct": 0, "high": 0, "low": 0, "volume": 0, "session": "未知", "time": ""}


def _fetch_from_yahoo_futures() -> dict:
    """備援：從 Yahoo Finance 取得台指期"""
    try:
        import yfinance as yf
        ticker = yf.Ticker("^TWII")
        info = ticker.fast_info
        price = float(info.get("lastPrice", 0) or 0)
        prev = float(info.get("previousClose", 0) or 0)

        if price > 0 and prev > 0:
            return {
                "price": price,
                "change": round(price - prev, 2),
                "change_pct": round((price - prev) / prev * 100, 2),
                "high": float(info.get("dayHigh", 0) or 0),
                "low": float(info.get("dayLow", 0) or 0),
                "volume": 0,
                "session": "收盤",
                "time": "",
            }
    except Exception:
        pass

    return {"price": 0, "change": 0, "change_pct": 0, "high": 0, "low": 0, "volume": 0, "session": "未知", "time": ""}
