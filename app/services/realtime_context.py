"""
即時市場狀態 — 統一提供給所有分析模組使用
避免每個模組各自呼叫即時 API 造成重複請求
"""
from app.services.realtime import fetch_realtime_price


def get_realtime_context(stock_id: str) -> dict:
    """
    取得即時市場狀態，供所有模組共用

    Returns:
        dict:
        - change_pct: 即時漲跌幅 (%)
        - is_crashing: 是否崩跌 (跌 > 3%)
        - is_dropping: 是否明顯下跌 (跌 > 1.5%)
        - is_weak: 是否偏弱 (跌 > 0.5%)
        - is_surging: 是否急漲 (漲 > 3%)
        - is_strong: 是否偏強 (漲 > 1%)
        - vol_ratio_rt: 即時量比
        - price: 即時價格
        - open: 今日開盤價
        - high: 今日最高
        - low: 今日最低
        - limit_up: 漲停價
        - limit_down: 跌停價
    """
    try:
        rt = fetch_realtime_price(stock_id)
        if rt.get("price", 0) <= 0:
            return _default_context()

        change_pct = rt.get("change_pct", 0)

        return {
            "change_pct": change_pct,
            "is_crashing": change_pct < -3,
            "is_dropping": change_pct < -1.5,
            "is_weak": change_pct < -0.5,
            "is_surging": change_pct > 3,
            "is_strong": change_pct > 1,
            "is_flat": -0.5 <= change_pct <= 0.5,
            "price": rt.get("price", 0),
            "open": rt.get("open", 0),
            "high": rt.get("high", 0),
            "low": rt.get("low", 0),
            "volume": rt.get("volume", 0),
            "limit_up": rt.get("limit_up", 0),
            "limit_down": rt.get("limit_down", 0),
            "yesterday_close": rt.get("yesterday_close", 0),
        }
    except Exception:
        return _default_context()


def _default_context() -> dict:
    return {
        "change_pct": 0,
        "is_crashing": False,
        "is_dropping": False,
        "is_weak": False,
        "is_surging": False,
        "is_strong": False,
        "is_flat": True,
        "price": 0,
        "open": 0,
        "high": 0,
        "low": 0,
        "volume": 0,
        "limit_up": 0,
        "limit_down": 0,
        "yesterday_close": 0,
    }
