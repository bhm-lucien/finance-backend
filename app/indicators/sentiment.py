"""
情緒指數模組（模組 11）+ AI 總結建議（模組 12）

情緒指數基於：
- RSI 貪婪/恐懼
- 融資餘額變化（散戶追漲指標）
- 法人動向偏離度
- 成交量異常度
- 價格相對高低位

AI 總結整合所有模組輸出，生成投資建議
"""
import pandas as pd
import numpy as np
from app.services.data_fetcher import (
    fetch_stock_price,
    fetch_institutional_investors,
    fetch_margin_trading,
)
from app.indicators.technical import calculate_rsi, calculate_macd, calculate_kd


def calculate_sentiment(stock_id: str) -> dict:
    """
    計算台股情緒指數（模組 12）— 整合即時報價
    """
    from app.services.realtime_context import get_realtime_context

    df = fetch_stock_price(stock_id, days=60)
    inst_df = fetch_institutional_investors(stock_id, days=30)
    margin_df = fetch_margin_trading(stock_id, days=30)
    ctx = get_realtime_context(stock_id)

    if len(df) < 20:
        return _default_sentiment()

    close = df["close"].iloc[-1]
    rsi = calculate_rsi(df).iloc[-1]

    # ── 1. 散戶偏值（RSI + 乖離率 + 即時漲跌）──
    ma20 = df["close"].rolling(20).mean().iloc[-1]
    bias = (close - ma20) / ma20 * 100

    retail_score = 50
    if rsi > 70 and bias > 5:
        retail_score = 85
    elif rsi > 60:
        retail_score = 70
    elif rsi < 30 and bias < -5:
        retail_score = 15
    elif rsi < 40:
        retail_score = 30

    # 即時修正
    if ctx["is_crashing"]:
        retail_score = max(10, retail_score - 30)
    elif ctx["is_dropping"]:
        retail_score = max(15, retail_score - 20)
    elif ctx["is_weak"]:
        retail_score = max(20, retail_score - 10)
    elif ctx["is_surging"]:
        retail_score = min(90, retail_score + 20)

    # ── 2. 法人情緒偏值 ──
    institutional_score = 50
    if not inst_df.empty and "buy" in inst_df.columns:
        recent = inst_df.tail(10)
        net = recent["buy"].sum() - recent["sell"].sum()
        if net > 0:
            institutional_score = min(85, 55 + int(net / 1000000))
        else:
            institutional_score = max(15, 50 + int(net / 1000000))

    # 即時修正
    if ctx["is_crashing"]:
        institutional_score = max(10, institutional_score - 25)
    elif ctx["is_dropping"]:
        institutional_score = max(20, institutional_score - 15)

    # ── 3. 主力偏值 ──
    vol_5 = df["volume"].tail(5).mean()
    vol_20 = df["volume"].tail(20).mean()
    vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 1

    macd_data = calculate_macd(df)
    macd_hist = macd_data["histogram"].iloc[-1]

    main_force_score = 50
    if vol_ratio > 1.5 and macd_hist > 0:
        main_force_score = 85
    elif vol_ratio > 1.2 and macd_hist > 0:
        main_force_score = 70
    elif vol_ratio < 0.7 and macd_hist < 0:
        main_force_score = 25
    elif macd_hist < 0:
        main_force_score = 35

    # 即時修正
    if ctx["is_crashing"]:
        main_force_score = max(10, main_force_score - 30)
    elif ctx["is_dropping"]:
        main_force_score = max(20, main_force_score - 15)
    elif ctx["is_surging"]:
        main_force_score = min(90, main_force_score + 20)

    # ── 4. FOMO 程度 ──
    pct_5d = (close - df["close"].iloc[-6]) / df["close"].iloc[-6] * 100
    fomo_score = 50
    if pct_5d > 5 and vol_ratio > 1.5:
        fomo_score = 90
    elif pct_5d > 3 and vol_ratio > 1.2:
        fomo_score = 75
    elif pct_5d > 0:
        fomo_score = 55
    elif pct_5d < -3:
        fomo_score = 25
    else:
        fomo_score = 40

    # 即時修正
    if ctx["is_crashing"]:
        fomo_score = max(5, fomo_score - 35)
    elif ctx["is_dropping"]:
        fomo_score = max(15, fomo_score - 20)

    # ── 總情緒計算 ──
    total_sentiment = int(
        retail_score * 0.25 +
        institutional_score * 0.2 +
        main_force_score * 0.25 +
        fomo_score * 0.3
    )
    total_sentiment = min(100, max(0, total_sentiment))

    # 情緒標籤
    if total_sentiment >= 75:
        label = "極度貪婪"
    elif total_sentiment >= 55:
        label = "貪婪"
    elif total_sentiment >= 45:
        label = "中性"
    elif total_sentiment >= 25:
        label = "恐懼"
    else:
        label = "極度恐懼"

    return {
        "total": total_sentiment,
        "label": label,
        "details": {
            "retail": {"label": "散戶偏值", "value": retail_score},
            "institutional": {"label": "法人情緒", "value": institutional_score},
            "main_force": {"label": "主力偏值", "value": main_force_score},
            "fomo": {"label": "FOMO程度", "value": fomo_score},
        },
    }


def generate_ai_summary(stock_id: str, modules_data: dict) -> dict:
    """
    AI 總結與投資建議（模組 12）

    整合所有模組的分析結果，生成綜合投資建議

    Args:
        stock_id: 股票代碼
        modules_data: 其他模組的分析結果

    Returns:
        dict 包含結論、風險等級、建議操作
    """
    # 從各模組提取關鍵資訊
    main_force = modules_data.get("main_force", {})
    day_trade_risk = modules_data.get("day_trade_risk", {})
    radar = modules_data.get("radar", {})
    health = modules_data.get("health", {})
    signal = modules_data.get("signal", {})
    sentiment = modules_data.get("sentiment", {})
    bull_bear = modules_data.get("bull_bear", {})

    # 收集風險訊號
    risk_signals = []
    bullish_signals = []

    # 主力出貨
    distribute_score = main_force.get("distribute", {}).get("score", 0)
    if distribute_score >= 4:
        risk_signals.append("創新高後量縮，顯示主力出貨跡象")

    # 隔日沖風險
    total_risk = day_trade_risk.get("total_risk", 0)
    if total_risk >= 70:
        risk_signals.append(f"隔日沖風險 {total_risk}%，短線有獲利了結壓力")

    # 法人動態
    health_chips = health.get("chips", 50)
    if health_chips < 40:
        risk_signals.append("三大法人近期合計賣超")
    elif health_chips > 70:
        bullish_signals.append("三大法人持續買超")

    # 籌碼集中度
    if health.get("mainForce", 50) < 40:
        risk_signals.append("主力進出量，籌碼集中略減")
    elif health.get("mainForce", 50) > 70:
        bullish_signals.append("主力籌碼集中度提升")

    # 情緒過熱
    sentiment_total = sentiment.get("total", 50)
    if sentiment_total >= 75:
        risk_signals.append("短線目前偏高風險，情緒過熱")
    elif sentiment_total <= 25:
        bullish_signals.append("市場極度恐懼，可能有反彈機會")

    # 技術面
    bull_pct = bull_bear.get("bull_percentage", 50)
    if bull_pct >= 75:
        bullish_signals.append("技術指標多頭排列")
    elif bull_pct <= 25:
        risk_signals.append("技術指標轉弱")

    # ── 決定整體結論 ──
    if len(risk_signals) >= 3:
        conclusion = "高檔震盪風險增高"
        risk_level = "高"
        suggestion = "偏防高出貨"
    elif len(risk_signals) >= 2:
        conclusion = "短線偏震盪，注意風險控管"
        risk_level = "中高"
        suggestion = "守勢操作"
    elif len(bullish_signals) >= 2:
        conclusion = "多方格局延續，可順勢操作"
        risk_level = "低"
        suggestion = "積極做多"
    elif len(bullish_signals) >= 1:
        conclusion = "趨勢尚可，觀察量能變化"
        risk_level = "中低"
        suggestion = "偏多操作"
    else:
        conclusion = "盤勢中性，等待方向確認"
        risk_level = "中"
        suggestion = "觀望為主"

    # 操作建議
    points = risk_signals[:4] if risk_signals else bullish_signals[:4]
    if not points:
        points = ["目前無明顯風險或利多訊號", "建議持續觀察籌碼和技術面變化"]

    return {
        "conclusion": conclusion,
        "risk_level": risk_level,
        "suggestion": suggestion,
        "points": points,
        "signal_light": signal.get("light", "green"),
    }


def _default_sentiment() -> dict:
    return {
        "total": 50,
        "label": "中性",
        "details": {
            "retail": {"label": "散戶偏值", "value": 50},
            "institutional": {"label": "法人情緒", "value": 50},
            "main_force": {"label": "主力偏值", "value": 50},
            "fomo": {"label": "FOMO程度", "value": 50},
        },
    }
