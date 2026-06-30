"""
趨勢線辨識模組
自動找出近期高點連線（壓力趨勢線）和低點連線（支撐趨勢線）
"""
import numpy as np
import pandas as pd
from app.services.data_fetcher import fetch_stock_price


def calculate_trendlines(stock_id: str, days: int = 60) -> dict:
    """
    計算自動辨識的趨勢線

    Returns:
        {
            "ohlcv": [...],  # K 線資料
            "support_line": {"start": {"idx": 10, "price": 100}, "end": {"idx": 55, "price": 110}},
            "resistance_line": {"start": {"idx": 5, "price": 120}, "end": {"idx": 50, "price": 115}},
            "trend_direction": "上升" / "下降" / "盤整",
            "support_slope": 0.5,  # 支撐線斜率（每日）
            "resistance_slope": -0.3,
        }
    """
    df = fetch_stock_price(stock_id, days=days)

    if len(df) < 20:
        return {"ohlcv": [], "support_line": None, "resistance_line": None, "trend_direction": "未知"}

    # 準備 OHLCV 資料
    ohlcv = []
    for _, row in df.iterrows():
        ohlcv.append({
            "date": str(row["date"].date()) if hasattr(row["date"], "date") else str(row["date"])[:10],
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": int(row["volume"]),
        })

    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    closes = df["close"].values.astype(float)
    n = len(df)

    # ── 找局部高點（壓力線用）──
    resistance_peaks = _find_peaks(highs, order=5)

    # ── 找局部低點（支撐線用）──
    support_troughs = _find_troughs(lows, order=5)

    # ── 計算壓力趨勢線（連接最近的兩個高點）──
    resistance_line = _fit_trendline(resistance_peaks, highs, n, line_type="resistance")

    # ── 計算支撐趨勢線（連接最近的兩個低點）──
    support_line = _fit_trendline(support_troughs, lows, n, line_type="support")

    # ── 判斷趨勢方向 ──
    trend_direction = "盤整"
    support_slope = 0
    resistance_slope = 0

    if support_line:
        support_slope = (support_line["end"]["price"] - support_line["start"]["price"]) / max(1, support_line["end"]["idx"] - support_line["start"]["idx"])
    if resistance_line:
        resistance_slope = (resistance_line["end"]["price"] - resistance_line["start"]["price"]) / max(1, resistance_line["end"]["idx"] - resistance_line["start"]["idx"])

    if support_slope > 0 and resistance_slope > 0:
        trend_direction = "上升"
    elif support_slope < 0 and resistance_slope < 0:
        trend_direction = "下降"
    elif support_slope > 0 and resistance_slope <= 0:
        trend_direction = "收斂（可能突破）"
    elif support_slope <= 0 and resistance_slope > 0:
        trend_direction = "擴散"
    else:
        trend_direction = "盤整"

    # 計算延伸預測價位（趨勢線延伸到最後一根 K 棒的價位）
    support_at_end = None
    resistance_at_end = None

    if support_line:
        slope = support_slope
        days_from_start = n - 1 - support_line["start"]["idx"]
        support_at_end = round(support_line["start"]["price"] + slope * days_from_start, 2)

    if resistance_line:
        slope = resistance_slope
        days_from_start = n - 1 - resistance_line["start"]["idx"]
        resistance_at_end = round(resistance_line["start"]["price"] + slope * days_from_start, 2)

    return {
        "ohlcv": ohlcv,
        "support_line": support_line,
        "resistance_line": resistance_line,
        "trend_direction": trend_direction,
        "support_slope": round(support_slope, 4),
        "resistance_slope": round(resistance_slope, 4),
        "support_at_current": support_at_end,
        "resistance_at_current": resistance_at_end,
        "current_price": round(float(closes[-1]), 2),
    }


def _find_peaks(data: np.ndarray, order: int = 5) -> list[int]:
    """找局部高點的索引"""
    peaks = []
    for i in range(order, len(data) - order):
        if all(data[i] >= data[i - j] for j in range(1, order + 1)) and \
           all(data[i] >= data[i + j] for j in range(1, order + 1)):
            peaks.append(i)
    return peaks


def _find_troughs(data: np.ndarray, order: int = 5) -> list[int]:
    """找局部低點的索引"""
    troughs = []
    for i in range(order, len(data) - order):
        if all(data[i] <= data[i - j] for j in range(1, order + 1)) and \
           all(data[i] <= data[i + j] for j in range(1, order + 1)):
            troughs.append(i)
    return troughs


def _fit_trendline(points: list[int], prices: np.ndarray, total_len: int, line_type: str) -> dict | None:
    """
    用最近的兩個轉折點擬合趨勢線

    Args:
        points: 局部轉折點索引列表
        prices: 對應的價格陣列（high 或 low）
        total_len: 資料總長度
        line_type: "support" 或 "resistance"
    """
    if len(points) < 2:
        # 轉折點不夠，用最近 half 的最高/最低兩點
        half = total_len // 2
        if line_type == "resistance":
            first_idx = int(np.argmax(prices[:half]))
            second_idx = half + int(np.argmax(prices[half:]))
        else:
            first_idx = int(np.argmin(prices[:half]))
            second_idx = half + int(np.argmin(prices[half:]))
        points = [first_idx, second_idx]

    # 取最近的兩個點
    recent_points = points[-2:]
    idx1, idx2 = recent_points[0], recent_points[1]

    # 確保有距離
    if abs(idx2 - idx1) < 3:
        if len(points) >= 3:
            idx1 = points[-3]
        else:
            return None

    price1 = float(prices[idx1])
    price2 = float(prices[idx2])

    return {
        "start": {"idx": int(idx1), "price": round(price1, 2)},
        "end": {"idx": int(idx2), "price": round(price2, 2)},
    }
