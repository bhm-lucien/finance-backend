"""
綜合評分模組 — 飆股雷達、健康度、燈號、劇本推演
整合技術指標 + 籌碼分析做多維度評分
"""
import numpy as np
import pandas as pd
from app.services.data_fetcher import (
    fetch_stock_price,
    fetch_institutional_investors,
    fetch_margin_trading,
)
from app.indicators.technical import (
    calculate_rsi,
    calculate_macd,
    calculate_kd,
    calculate_moving_averages,
)


def calculate_radar_scores(stock_id: str, days: int = 120) -> dict:
    """
    飆股雷達圖評分（模組 3）

    六個維度：趨勢強度、能態、集碼、波動、法人、主力
    每個維度 0~100 分

    Returns:
        dict 包含六維分數 + 飆股等級 + 風險值
    """
    df = fetch_stock_price(stock_id, days=days)
    inst_df = fetch_institutional_investors(stock_id, days=30)
    margin_df = fetch_margin_trading(stock_id, days=30)

    if len(df) < 30:
        return _default_radar()

    # ── 1. 趨勢強度 ──
    ma = calculate_moving_averages(df)
    close = df["close"].iloc[-1]
    ma5 = ma["ma5"].iloc[-1]
    ma20 = ma["ma20"].iloc[-1]
    ma60 = ma["ma60"].iloc[-1] if not pd.isna(ma["ma60"].iloc[-1]) else close

    # 多頭排列加分
    trend_score = 50
    if close > ma5 > ma20 > ma60:
        trend_score = 92
    elif close > ma5 > ma20:
        trend_score = 80
    elif close > ma20:
        trend_score = 65
    elif close < ma5 < ma20 < ma60:
        trend_score = 15
    elif close < ma20:
        trend_score = 35

    # 近 20 日漲幅加成
    pct_20d = (close - df["close"].iloc[-21]) / df["close"].iloc[-21] * 100 if len(df) > 20 else 0
    trend_score = min(100, trend_score + pct_20d * 0.5)

    # ── 2. 能態（動能）──
    rsi = calculate_rsi(df).iloc[-1]
    macd_data = calculate_macd(df)
    macd_hist = macd_data["histogram"].iloc[-1]

    energy_score = 50
    if rsi > 70 and macd_hist > 0:
        energy_score = 90
    elif rsi > 60 and macd_hist > 0:
        energy_score = 75
    elif rsi > 50:
        energy_score = 60
    elif rsi < 30:
        energy_score = 20
    else:
        energy_score = 40

    # ── 3. 集碼（籌碼集中度）──
    chips_score = 50
    if not inst_df.empty and "buy" in inst_df.columns:
        recent_inst = inst_df.tail(10)
        net_buy = recent_inst["buy"].sum() - recent_inst["sell"].sum()
        if net_buy > 0:
            chips_score = min(95, 60 + (net_buy / 1000000) * 5)
        else:
            chips_score = max(20, 50 + (net_buy / 1000000) * 5)

    # ── 4. 波動 ──
    recent_20 = df.tail(20)
    atr = (recent_20["high"] - recent_20["low"]).mean()
    atr_pct = atr / close * 100
    # 波動適中為高分，過大或過小扣分
    if 1.5 < atr_pct < 3.5:
        volatility_score = 85
    elif 1 < atr_pct < 5:
        volatility_score = 65
    elif atr_pct > 5:
        volatility_score = 40
    else:
        volatility_score = 50

    # ── 5. 法人 ──
    institutional_score = 50
    if not inst_df.empty and "name" in inst_df.columns:
        foreign = inst_df[inst_df["name"].str.contains("外資", na=False)]
        if not foreign.empty and "buy" in foreign.columns:
            foreign_net = foreign["buy"].sum() - foreign["sell"].sum()
            if foreign_net > 0:
                institutional_score = min(95, 60 + foreign_net / 500000)
            else:
                institutional_score = max(15, 50 + foreign_net / 500000)

    # ── 6. 主力 ──
    # 用近 5 日成交量集中度 + 價量配合度
    vol_5d = df["volume"].tail(5).mean()
    vol_20d = df["volume"].tail(20).mean()
    vol_ratio = vol_5d / vol_20d if vol_20d > 0 else 1

    main_force_score = 50
    if vol_ratio > 1.5 and pct_20d > 3:
        main_force_score = 88
    elif vol_ratio > 1.2 and pct_20d > 0:
        main_force_score = 72
    elif vol_ratio > 1:
        main_force_score = 58
    elif vol_ratio < 0.7:
        main_force_score = 30

    # ── 計算飆股等級和風險值 ──
    scores = {
        "trend": int(min(100, max(0, trend_score))),
        "energy": int(min(100, max(0, energy_score))),
        "chips": int(min(100, max(0, chips_score))),
        "volatility": int(min(100, max(0, volatility_score))),
        "institutional": int(min(100, max(0, institutional_score))),
        "mainForce": int(min(100, max(0, main_force_score))),
    }

    avg_score = sum(scores.values()) / 6

    # 飆股等級
    if avg_score >= 85:
        grade = "S"
    elif avg_score >= 75:
        grade = "A"
    elif avg_score >= 60:
        grade = "B"
    elif avg_score >= 45:
        grade = "C"
    else:
        grade = "D"

    # 風險值（越高越危險）
    risk_value = int(min(100, max(0, (rsi - 30) * 1.2 + (100 - volatility_score) * 0.3)))

    return {
        "scores": scores,
        "grade": grade,
        "risk_value": risk_value,
        "avg_score": int(avg_score),
    }


def generate_scenarios(stock_id: str) -> dict:
    """
    明日劇本推演（模組 4）

    根據技術指標和籌碼狀態，推算三種可能劇本的機率

    Returns:
        dict 包含三個劇本及其機率和條件
    """
    df = fetch_stock_price(stock_id, days=60)
    if len(df) < 20:
        return _default_scenarios()

    close = df["close"].iloc[-1]
    ma = calculate_moving_averages(df)
    rsi = calculate_rsi(df).iloc[-1]
    macd_data = calculate_macd(df)
    macd_hist = macd_data["histogram"].iloc[-1]
    kd = calculate_kd(df)
    k_val = kd["k"].iloc[-1]

    ma5 = ma["ma5"].iloc[-1]
    ma20 = ma["ma20"].iloc[-1]
    ma60 = ma["ma60"].iloc[-1] if not pd.isna(ma["ma60"].iloc[-1]) else close

    # 計算支撐壓力
    recent_20 = df.tail(20)
    resistance = float(recent_20["high"].max())
    support = float(recent_20["low"].min())

    # ── 基礎機率 ──
    bull_prob = 33
    neutral_prob = 34
    bear_prob = 33

    # 根據指標調整機率
    if close > ma5 > ma20:
        bull_prob += 15
        bear_prob -= 15
    elif close < ma5 < ma20:
        bear_prob += 15
        bull_prob -= 15

    if macd_hist > 0:
        bull_prob += 8
        bear_prob -= 8
    else:
        bear_prob += 8
        bull_prob -= 8

    if rsi > 70:
        bear_prob += 10
        bull_prob -= 5
        neutral_prob -= 5
    elif rsi < 30:
        bull_prob += 10
        bear_prob -= 5
        neutral_prob -= 5

    if k_val > 80:
        bear_prob += 5
        bull_prob -= 5
    elif k_val < 20:
        bull_prob += 5
        bear_prob -= 5

    # 正規化到 100%
    total = bull_prob + neutral_prob + bear_prob
    bull_prob = max(5, int(bull_prob / total * 100))
    neutral_prob = max(5, int(neutral_prob / total * 100))
    bear_prob = 100 - bull_prob - neutral_prob

    # 計算目標價（限制在漲跌停範圍內）
    prev_close = float(df["close"].iloc[-2]) if len(df) > 1 else float(close)
    limit_up = round(prev_close * 1.10, 2)
    limit_down = round(prev_close * 0.90, 2)

    bull_target = round(min(float(close) * 1.03, limit_up), 2)
    bear_stop = round(max(float(close) * 0.97, limit_down), 2)
    bear_target = round(max(float(close) * 0.95, limit_down), 2)

    return {
        "scenarios": [
            {
                "name": "突破上漲",
                "probability": bull_prob,
                "color": "red",
                "condition": f"站穩 {ma5:.1f} 之上，量能擴大",
                "target": bull_target,
                "stop": round(float(ma20), 2),
            },
            {
                "name": "震盪整理",
                "probability": neutral_prob,
                "color": "orange",
                "condition": f"在 {support:.0f} ~ {resistance:.0f} 區間震盪整理",
                "target": round(min(resistance, limit_up), 2),
                "stop": round(max(support, limit_down), 2),
            },
            {
                "name": "轉弱下跌",
                "probability": bear_prob,
                "color": "green",
                "condition": f"跌破 {support:.0f}，量能不縮",
                "target": bear_target,
                "stop": bear_stop,
            },
        ],
        "key_levels": {
            "resistance": round(resistance, 2),
            "support": round(support, 2),
            "ma5": round(float(ma5), 2),
            "ma20": round(float(ma20), 2),
        },
    }


def calculate_health_scores(stock_id: str) -> dict:
    """
    個股健康度評分（模組 9）— 整合即時報價
    """
    from app.services.realtime_context import get_realtime_context

    df = fetch_stock_price(stock_id, days=120)
    inst_df = fetch_institutional_investors(stock_id, days=30)
    ctx = get_realtime_context(stock_id)

    if len(df) < 30:
        return {"trend": 50, "chips": 50, "mainForce": 50, "value": 50, "overall": "中性"}

    close = df["close"].iloc[-1]
    ma = calculate_moving_averages(df)
    rsi = calculate_rsi(df).iloc[-1]

    ma5 = ma["ma5"].iloc[-1]
    ma20 = ma["ma20"].iloc[-1]
    ma60 = ma["ma60"].iloc[-1] if not pd.isna(ma["ma60"].iloc[-1]) else close

    # 趨勢健康
    trend = 50
    if close > ma5 > ma20 > ma60:
        trend = 88
    elif close > ma5 > ma20:
        trend = 75
    elif close > ma20:
        trend = 60
    elif close < ma20:
        trend = 35

    # 即時修正趨勢
    if ctx["is_crashing"]:
        trend = max(10, trend - 40)
    elif ctx["is_dropping"]:
        trend = max(15, trend - 25)
    elif ctx["is_weak"]:
        trend = max(25, trend - 10)

    # 籌碼健康
    chips = 50
    if not inst_df.empty and "buy" in inst_df.columns:
        net = inst_df["buy"].sum() - inst_df["sell"].sum()
        if net > 0:
            chips = min(90, 60 + int(net / 500000))
        else:
            chips = max(20, 50 + int(net / 500000))

    # 即時修正籌碼
    if ctx["is_crashing"]:
        chips = max(10, chips - 25)
    elif ctx["is_dropping"]:
        chips = max(15, chips - 15)

    # 主力控盤
    vol_5 = df["volume"].tail(5).mean()
    vol_20 = df["volume"].tail(20).mean()
    vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 1
    pct_5d = (close - df["close"].iloc[-6]) / df["close"].iloc[-6] * 100

    main_force = 50
    if vol_ratio > 1.2 and pct_5d > 0:
        main_force = 78
    elif vol_ratio > 1 and pct_5d > 0:
        main_force = 65
    elif vol_ratio < 0.8:
        main_force = 40

    # 即時修正主力
    if ctx["is_crashing"]:
        main_force = max(10, main_force - 30)
    elif ctx["is_dropping"]:
        main_force = max(20, main_force - 15)

    # 價值健康（RSI + 乖離率）
    bias_20 = (close - ma20) / ma20 * 100 if ma20 > 0 else 0
    value = 50
    if 40 < rsi < 60 and abs(bias_20) < 5:
        value = 80
    elif 30 < rsi < 70:
        value = 65
    elif rsi > 80 or rsi < 20:
        value = 30

    # 總評
    avg = (trend + chips + main_force + value) / 4
    if avg > 80:
        overall = "過熱"
    elif avg > 65:
        overall = "健康"
    elif avg > 45:
        overall = "中性"
    else:
        overall = "低迷"

    return {
        "trend": int(trend),
        "chips": int(chips),
        "mainForce": int(main_force),
        "value": int(value),
        "overall": overall,
    }


def determine_signal_light(stock_id: str) -> dict:
    """
    飆股預警燈號（模組 10）— 整合即時報價

    紅燈：主力出貨（高檔爆量 + 法人賣 + 盤中大跌）
    黃橙：過熱整理（RSI > 70 或盤中下跌）
    綠燈：低檔轉強（RSI < 40 且量增）
    黑燈：跌破趨勢（跌破 MA20 + 量增 + 盤中崩跌）
    """
    from app.services.realtime_context import get_realtime_context

    df = fetch_stock_price(stock_id, days=60)
    inst_df = fetch_institutional_investors(stock_id, days=15)
    ctx = get_realtime_context(stock_id)

    if len(df) < 20:
        return {"light": "black", "label": "資料不足", "reason": "無法判斷"}

    close = df["close"].iloc[-1]
    ma = calculate_moving_averages(df)
    rsi = calculate_rsi(df).iloc[-1]
    ma20 = ma["ma20"].iloc[-1]

    vol_today = df["volume"].iloc[-1]
    vol_avg = df["volume"].tail(20).mean()
    vol_ratio = vol_today / vol_avg if vol_avg > 0 else 1

    is_high = close >= df["close"].tail(20).quantile(0.85)

    net_buy = 0
    if not inst_df.empty and "buy" in inst_df.columns:
        net_buy = inst_df["buy"].sum() - inst_df["sell"].sum()

    # ── 即時優先判斷 ──
    if ctx["is_crashing"]:
        return {
            "light": "red",
            "label": "盤中崩跌",
            "reason": f"盤中跌幅 {ctx['change_pct']:.1f}%，主力大量拋售，極高風險",
        }

    if ctx["is_dropping"]:
        return {
            "light": "red",
            "label": "主力出貨",
            "reason": f"盤中跌 {abs(ctx['change_pct']):.1f}%，賣壓沉重，風險升高",
        }

    if ctx["is_weak"] and is_high:
        return {
            "light": "orange",
            "label": "高檔轉弱",
            "reason": f"高檔區盤中走弱（{ctx['change_pct']:.1f}%），注意回檔風險",
        }

    # ── 歷史資料判斷 ──
    if is_high and vol_ratio > 1.5 and net_buy < 0:
        return {
            "light": "red",
            "label": "主力出貨",
            "reason": "高檔爆量、法人賣超、風險升高",
        }

    if rsi > 70 or (is_high and vol_ratio < 0.8):
        return {
            "light": "orange",
            "label": "過熱整理",
            "reason": "指標高檔鈍化、高檔量溫與回檔整理",
        }

    if close < ma20 and vol_ratio > 1.2:
        return {
            "light": "black",
            "label": "跌破趨勢",
            "reason": "跌破支撐、轉弱下跌",
        }

    if ctx["is_strong"]:
        return {
            "light": "green",
            "label": "趨勢向上",
            "reason": f"盤中漲 {ctx['change_pct']:.1f}%，多方氣勢強",
        }

    if rsi < 45 and vol_ratio > 1.1 and close > ma["ma5"].iloc[-1]:
        return {
            "light": "green",
            "label": "低檔轉強",
            "reason": "主力吸籌、趨勢向上",
        }

    if ctx["is_weak"]:
        return {
            "light": "orange",
            "label": "盤中偏弱",
            "reason": f"盤中小跌 {abs(ctx['change_pct']):.1f}%，觀察是否止穩",
        }

    return {
        "light": "green",
        "label": "趨勢正常",
        "reason": "目前無明顯風險訊號",
    }


def _default_radar() -> dict:
    return {
        "scores": {"trend": 50, "energy": 50, "chips": 50, "volatility": 50, "institutional": 50, "mainForce": 50},
        "grade": "C",
        "risk_value": 50,
        "avg_score": 50,
    }


def _default_scenarios() -> dict:
    return {
        "scenarios": [
            {"name": "突破上漲", "probability": 33, "color": "red", "condition": "資料不足", "target": 0, "stop": 0},
            {"name": "震盪整理", "probability": 34, "color": "orange", "condition": "資料不足", "target": 0, "stop": 0},
            {"name": "轉弱下跌", "probability": 33, "color": "green", "condition": "資料不足", "target": 0, "stop": 0},
        ],
        "key_levels": {"resistance": 0, "support": 0, "ma5": 0, "ma20": 0},
    }
