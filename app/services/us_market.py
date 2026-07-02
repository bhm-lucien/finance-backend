"""
美股市場資料服務
取得四大指數 + 主要科技股的即時/收盤資料
"""
import time
import requests


_us_cache: dict[str, dict] = {}
CACHE_TTL = 120  # 2 分鐘快取

# 追蹤的美股標的
US_INDICES = {
    "^DJI": "道瓊工業",
    "^GSPC": "S&P 500",
    "^IXIC": "那斯達克",
    "^SOX": "費城半導體",
}

US_TECH_STOCKS = {
    "NVDA": "輝達",
    "AAPL": "蘋果",
    "MSFT": "微軟",
    "GOOGL": "Google",
    "AMZN": "亞馬遜",
    "TSM": "台積電ADR",
    "META": "Meta",
    "AVGO": "博通",
}

# 費城半導體指數主要成分股
SOX_COMPONENTS = {
    "NVDA": "輝達",
    "AMD": "超微",
    "AVGO": "博通",
    "QCOM": "高通",
    "TXN": "德儀",
    "INTC": "英特爾",
    "MU": "美光",
    "LRCX": "科磊",
    "AMAT": "應材",
    "KLAC": "科磊",
    "MRVL": "Marvell",
    "TSM": "台積電ADR",
    "ASML": "艾司摩爾",
    "ARM": "安謀",
    "ON": "安森美",
}


def fetch_us_market_summary() -> dict:
    """
    取得完整美股市場摘要

    Returns:
        {
            "indices": [{"symbol": "^DJI", "name": "道瓊", "price": 44000, "change_pct": 0.5}, ...],
            "tech_stocks": [{"symbol": "NVDA", "name": "輝達", "price": 140, "change_pct": 2.1}, ...],
            "summary": "美股四大指數全面上漲，費半漲幅最大...",
            "update_time": "2024-01-01 05:00",
        }
    """
    cache_key = "us_market"
    if cache_key in _us_cache:
        entry = _us_cache[cache_key]
        if time.time() - entry["time"] < CACHE_TTL:
            return entry["data"]

    indices = []
    tech_stocks = []

    # 取得指數
    for symbol, name in US_INDICES.items():
        data = _fetch_quote(symbol)
        if data:
            data["name"] = name
            indices.append(data)

    # 取得科技股
    for symbol, name in US_TECH_STOCKS.items():
        data = _fetch_quote(symbol)
        if data:
            data["name"] = name
            tech_stocks.append(data)

    # 取得費半成分股漲幅前三名
    sox_top3 = _fetch_sox_top3()

    # 產生摘要
    summary = _generate_summary(indices, tech_stocks)

    from datetime import datetime
    result = {
        "indices": indices,
        "tech_stocks": tech_stocks,
        "sox_top3": sox_top3,
        "summary": summary,
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    _us_cache[cache_key] = {"data": result, "time": time.time()}
    return result


def _fetch_sox_top3() -> list[dict]:
    """取得費半成分股漲幅前三名"""
    all_stocks = []
    for symbol, name in SOX_COMPONENTS.items():
        data = _fetch_quote(symbol)
        if data:
            data["name"] = name
            all_stocks.append(data)

    # 按漲幅排序取前三
    all_stocks.sort(key=lambda x: x["change_pct"], reverse=True)
    return all_stocks[:3]


def _fetch_quote(symbol: str) -> dict | None:
    """從 Yahoo Finance 取得單一標的報價"""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code != 200:
            return None

        data = response.json()
        chart = data.get("chart", {}).get("result", [])
        if not chart:
            return None

        meta = chart[0].get("meta", {})
        price = float(meta.get("regularMarketPrice", 0))
        prev_close = float(meta.get("chartPreviousClose", 0) or meta.get("previousClose", 0))

        if price == 0:
            return None

        change = round(price - prev_close, 2) if prev_close > 0 else 0
        change_pct = round(change / prev_close * 100, 2) if prev_close > 0 else 0

        return {
            "symbol": symbol,
            "price": price,
            "change": change,
            "change_pct": change_pct,
        }
    except Exception:
        return None


def _generate_summary(indices: list, tech_stocks: list) -> str:
    """產生美股摘要文字"""
    if not indices:
        return "美股資料暫時無法取得"

    # 指數方向
    up_count = sum(1 for i in indices if i["change_pct"] > 0)
    down_count = sum(1 for i in indices if i["change_pct"] < 0)

    if up_count == len(indices):
        direction = "全面上漲"
    elif down_count == len(indices):
        direction = "全面下跌"
    elif up_count > down_count:
        direction = "漲跌互見，偏多"
    else:
        direction = "漲跌互見，偏空"

    # 找漲幅最大的指數
    best = max(indices, key=lambda x: x["change_pct"])
    worst = min(indices, key=lambda x: x["change_pct"])

    parts = [f"美股{direction}"]
    if best["change_pct"] > 0:
        parts.append(f"{best['name']}漲{best['change_pct']:.1f}%最強")
    if worst["change_pct"] < 0:
        parts.append(f"{worst['name']}跌{abs(worst['change_pct']):.1f}%最弱")

    # 科技股重點
    if tech_stocks:
        tsm = next((s for s in tech_stocks if s["symbol"] == "TSM"), None)
        if tsm:
            arrow = "漲" if tsm["change_pct"] > 0 else "跌"
            parts.append(f"台積電ADR{arrow}{abs(tsm['change_pct']):.1f}%")

    return "，".join(parts)
