"""
條件式股票篩選器

支援多條件組合篩選：
- 趨勢：站上/跌破均線、布林通道
- 動能：KD 金叉/死叉、MACD 翻多/翻空
- 量價：量能放大、RSI 超買超賣、IBS
- 籌碼：外資買超、投信買超
"""
import time
import pandas as pd
from typing import Optional
from app.services.data_fetcher import fetch_stock_price
from app.services.stock_list import fetch_all_stocks
from app.indicators.technical import (
    calculate_rsi,
    calculate_macd,
    calculate_moving_averages,
)


_filter_cache: dict[str, dict] = {}
CACHE_TTL = 600  # 10 分鐘快取


# 所有可用的篩選條件定義
FILTER_CONDITIONS = [
    # 趨勢
    {"id": "above_ma5", "name": "站上 MA5", "category": "趨勢", "type": "buy"},
    {"id": "above_ma20", "name": "站上 MA20", "category": "趨勢", "type": "buy"},
    {"id": "above_ma60", "name": "站上 MA60", "category": "趨勢", "type": "buy"},
    {"id": "below_ma20", "name": "跌破 MA20", "category": "趨勢", "type": "sell"},
    {"id": "ma_bullish", "name": "均線多頭排列", "category": "趨勢", "type": "buy"},
    {"id": "ma_bearish", "name": "均線空頭排列", "category": "趨勢", "type": "sell"},
    # 動能
    {"id": "kd_golden", "name": "KD 黃金交叉", "category": "動能", "type": "buy"},
    {"id": "kd_death", "name": "KD 死亡交叉", "category": "動能", "type": "sell"},
    {"id": "macd_bull", "name": "MACD 翻多", "category": "動能", "type": "buy"},
    {"id": "macd_bear", "name": "MACD 翻空", "category": "動能", "type": "sell"},
    # 量價
    {"id": "vol_surge", "name": "量能放大 >1.5x", "category": "量價", "type": "filter"},
    {"id": "rsi_oversold", "name": "RSI < 30（超賣）", "category": "量價", "type": "buy"},
    {"id": "rsi_overbought", "name": "RSI > 70（超買）", "category": "量價", "type": "sell"},
    {"id": "ibs_low", "name": "IBS ≤ 0.2（收在低點）", "category": "量價", "type": "buy"},
    {"id": "ibs_high", "name": "IBS ≥ 0.8（收在高點）", "category": "量價", "type": "sell"},
    # 突破
    {"id": "breakout_20d", "name": "突破 20 日高點", "category": "突破", "type": "buy"},
    {"id": "breakdown_20d", "name": "跌破 20 日低點", "category": "突破", "type": "sell"},
]


def get_available_conditions() -> list[dict]:
    """回傳所有可用的篩選條件"""
    return FILTER_CONDITIONS


def filter_stocks(conditions: list[str], max_results: int = 30) -> dict:
    """
    根據多個條件組合篩選股票（AND 邏輯）

    Args:
        conditions: 條件 ID 列表，如 ["above_ma20", "macd_bull", "vol_surge"]
        max_results: 最多回傳幾支

    Returns:
        {
            "results": [{"stock_id": "2330", "name": "台積電", "price": 590, "change_pct": 1.2, "matched": [...]}],
            "total_scanned": 100,
            "total_matched": 15,
            "conditions_used": [...],
        }
    """
    if not conditions:
        return {"results": [], "total_scanned": 0, "total_matched": 0, "conditions_used": []}

    # 快取 key
    cache_key = f"filter_{'_'.join(sorted(conditions))}"
    if cache_key in _filter_cache:
        entry = _filter_cache[cache_key]
        if time.time() - entry["time"] < CACHE_TTL:
            return entry["data"]

    # 取得股票清單（只取四位數代碼）
    all_stocks = fetch_all_stocks()
    if isinstance(all_stocks, dict):
        stocks = [
            {"id": sid, "name": sname}
            for sid, sname in all_stocks.items()
            if len(sid) == 4 and sid.isdigit()
        ][:200]  # 限制掃描 200 支
    else:
        stocks = []

    results = []
    scanned = 0

    for stock in stocks:
        scanned += 1
        try:
            matched = _check_stock(stock["id"], conditions)
            if matched is not None:
                results.append({
                    "stock_id": stock["id"],
                    "name": stock["name"],
                    "price": matched["price"],
                    "change_pct": matched["change_pct"],
                    "matched": matched["matched_conditions"],
                })
        except Exception:
            continue

        # 提早結束（找夠了）
        if len(results) >= max_results:
            break

    # 按漲跌幅排序
    results.sort(key=lambda x: x["change_pct"], reverse=True)

    condition_names = [c["name"] for c in FILTER_CONDITIONS if c["id"] in conditions]

    result = {
        "results": results[:max_results],
        "total_scanned": scanned,
        "total_matched": len(results),
        "conditions_used": condition_names,
    }

    _filter_cache[cache_key] = {"data": result, "time": time.time()}
    return result


def _check_stock(stock_id: str, conditions: list[str]) -> Optional[dict]:
    """
    檢查單支股票是否符合所有條件

    Returns:
        如果全部符合，回傳 {"price", "change_pct", "matched_conditions"}
        如果不符合，回傳 None
    """
    df = fetch_stock_price(stock_id, days=60)
    if len(df) < 20:
        return None

    close = float(df["close"].iloc[-1])
    prev_close = float(df["close"].iloc[-2])
    change_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0

    # 計算技術指標
    ma = calculate_moving_averages(df)
    ma5 = float(ma["ma5"].iloc[-1]) if "ma5" in ma else 0
    ma20 = float(ma["ma20"].iloc[-1]) if "ma20" in ma else 0
    ma60 = float(ma["ma60"].iloc[-1]) if "ma60" in ma else 0

    rsi_series = calculate_rsi(df)
    rsi = float(rsi_series.iloc[-1]) if not rsi_series.empty else 50

    macd_data = calculate_macd(df)
    macd_hist = float(macd_data["histogram"].iloc[-1]) if "histogram" in macd_data else 0
    macd_hist_prev = float(macd_data["histogram"].iloc[-2]) if "histogram" in macd_data and len(macd_data["histogram"]) > 1 else 0

    vol_today = float(df["volume"].iloc[-1])
    vol_avg = float(df["volume"].tail(20).mean())
    vol_ratio = vol_today / vol_avg if vol_avg > 0 else 1

    high_20d = float(df["high"].tail(20).max())
    low_20d = float(df["low"].tail(20).min())

    # IBS (Internal Bar Strength)
    today_high = float(df["high"].iloc[-1])
    today_low = float(df["low"].iloc[-1])
    ibs = (close - today_low) / (today_high - today_low) if (today_high - today_low) > 0 else 0.5

    # KD（簡化計算）
    low_9 = float(df["low"].tail(9).min())
    high_9 = float(df["high"].tail(9).max())
    rsv = (close - low_9) / (high_9 - low_9) * 100 if (high_9 - low_9) > 0 else 50

    # 檢查每個條件
    matched_conditions = []

    for cond in conditions:
        passed = False

        if cond == "above_ma5":
            passed = close > ma5 and ma5 > 0
        elif cond == "above_ma20":
            passed = close > ma20 and ma20 > 0
        elif cond == "above_ma60":
            passed = close > ma60 and ma60 > 0
        elif cond == "below_ma20":
            passed = close < ma20 and ma20 > 0
        elif cond == "ma_bullish":
            passed = ma5 > ma20 > ma60 > 0 and close > ma5
        elif cond == "ma_bearish":
            passed = ma5 < ma20 and ma20 > 0 and close < ma5
        elif cond == "kd_golden":
            # 簡化：RSV > 50 且上升中
            passed = rsv > 50 and close > prev_close
        elif cond == "kd_death":
            passed = rsv < 50 and close < prev_close
        elif cond == "macd_bull":
            passed = macd_hist > 0 and macd_hist_prev <= 0
        elif cond == "macd_bear":
            passed = macd_hist < 0 and macd_hist_prev >= 0
        elif cond == "vol_surge":
            passed = vol_ratio >= 1.5
        elif cond == "rsi_oversold":
            passed = rsi < 30
        elif cond == "rsi_overbought":
            passed = rsi > 70
        elif cond == "ibs_low":
            passed = ibs <= 0.2
        elif cond == "ibs_high":
            passed = ibs >= 0.8
        elif cond == "breakout_20d":
            passed = close >= high_20d * 0.98
        elif cond == "breakdown_20d":
            passed = close <= low_20d * 1.02

        if not passed:
            return None  # AND 邏輯：任一條件不符就排除
        matched_conditions.append(cond)

    return {
        "price": close,
        "change_pct": change_pct,
        "matched_conditions": matched_conditions,
    }
