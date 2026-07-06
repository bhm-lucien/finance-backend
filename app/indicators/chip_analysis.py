"""
籌碼分析模組 — 主力意圖分析 + 隔日沖風險
基於三大法人買賣超、融資融券、成交量等真實資料計算
"""
import pandas as pd
import numpy as np
from app.services.data_fetcher import (
    fetch_stock_price,
    fetch_institutional_investors,
    fetch_margin_trading,
)


def analyze_main_force(stock_id: str, days: int = 60) -> dict:
    """
    主力意圖分析（模組 1）

    根據法人買賣超、成交量變化、價格型態判斷主力行為：
    - 主力洗盤：量縮價穩，法人小賣
    - 主力吸籌：量增價穩或小漲，法人持續買
    - 主力出貨：量大價高，法人轉賣
    - 軋空佈局：融券大增但股價不跌
    - 假突破：爆量突破後隔日下跌
    - 假多風險：股價新高但法人大賣
    - 誘空風險：融券大增且股價上漲

    Returns:
        dict 包含各項指標的分數 (1~5) 和 AI 結論
    """
    # 取得資料
    df = fetch_stock_price(stock_id, days=days)
    inst_df = fetch_institutional_investors(stock_id, days=30)
    margin_df = fetch_margin_trading(stock_id, days=30)

    if len(df) < 20:
        return _default_result()

    # 取得即時報價（補充盤中資訊）
    try:
        from app.services.realtime import fetch_realtime_price
        rt = fetch_realtime_price(stock_id)
        rt_change_pct = rt.get("change_pct", 0) if rt.get("price", 0) > 0 else 0
    except Exception:
        rt_change_pct = 0

    recent = df.tail(10)
    prev = df.tail(20).head(10)

    # ── 計算各項指標 ──

    # 1. 成交量分析
    avg_vol_recent = recent["volume"].mean()
    avg_vol_prev = prev["volume"].mean()
    vol_ratio = avg_vol_recent / avg_vol_prev if avg_vol_prev > 0 else 1

    # 2. 價格趨勢
    price_change_5d = (df["close"].iloc[-1] - df["close"].iloc[-6]) / df["close"].iloc[-6] * 100
    price_change_10d = (df["close"].iloc[-1] - df["close"].iloc[-11]) / df["close"].iloc[-11] * 100
    is_near_high = df["close"].iloc[-1] >= df["close"].tail(20).quantile(0.9)

    # 3. 法人買賣超
    net_buy = 0
    foreign_net = 0
    if not inst_df.empty:
        # 計算近 5 日法人淨買賣
        recent_inst = inst_df.tail(15)  # 每日有多筆（外資/投信/自營）
        if "buy" in recent_inst.columns and "sell" in recent_inst.columns:
            net_buy = (recent_inst["buy"].sum() - recent_inst["sell"].sum())
            # 外資部分
            foreign = recent_inst[recent_inst["name"].str.contains("外資|Foreign_Investor", na=False)] if "name" in recent_inst.columns else pd.DataFrame()
            if not foreign.empty:
                foreign_net = foreign["buy"].sum() - foreign["sell"].sum()

    # 4. 融資融券
    margin_increase = 0
    short_increase = 0
    if not margin_df.empty and len(margin_df) >= 2:
        if "MarginPurchaseTodayBalance" in margin_df.columns:
            margin_increase = float(margin_df["MarginPurchaseTodayBalance"].iloc[-1]) - float(margin_df["MarginPurchaseTodayBalance"].iloc[0])
        if "ShortSaleTodayBalance" in margin_df.columns:
            short_increase = float(margin_df["ShortSaleTodayBalance"].iloc[-1]) - float(margin_df["ShortSaleTodayBalance"].iloc[0])

    # ── 評分計算 (1~5 分) ──

    # 主力洗盤：量縮 + 小跌或持平
    wash_score = 1
    if vol_ratio < 0.7 and -2 < price_change_5d < 1:
        wash_score = 4
    elif vol_ratio < 0.85 and -1 < price_change_5d < 2:
        wash_score = 3
    elif vol_ratio < 0.9:
        wash_score = 2

    # 主力吸籌：量增 + 穩步上漲 + 法人買
    accumulate_score = 1
    if vol_ratio > 1.2 and price_change_5d > 0 and net_buy > 0:
        accumulate_score = 4
    elif vol_ratio > 1.1 and price_change_5d > 0:
        accumulate_score = 3
    elif net_buy > 0 and price_change_5d > 0:
        accumulate_score = 2

    # 主力出貨：高檔 + 量大 + 法人賣 + 盤中大跌
    distribute_score = 1
    if rt_change_pct < -5:
        distribute_score = 5
    elif rt_change_pct < -3:
        distribute_score = 5
    elif rt_change_pct < -1.5:
        distribute_score = 4
    elif rt_change_pct < -0.8:
        distribute_score = 3
    elif is_near_high and vol_ratio > 1.5 and net_buy < 0:
        distribute_score = 5
    elif is_near_high and vol_ratio > 1.3:
        distribute_score = 4
    elif is_near_high and net_buy < 0:
        distribute_score = 3
    elif vol_ratio > 1.2 and net_buy < 0:
        distribute_score = 2

    # 軋空佈局：融券增加但股價上漲
    squeeze_score = 1
    if short_increase > 0 and price_change_5d > 2:
        squeeze_score = 4
    elif short_increase > 0 and price_change_5d > 0:
        squeeze_score = 3
    elif short_increase > 0:
        squeeze_score = 2

    # 假突破：近日爆量後股價回落
    fake_breakout_score = 1
    if len(df) >= 3:
        day_before = df.iloc[-3]
        yesterday = df.iloc[-2]
        today = df.iloc[-1]
        if yesterday["volume"] > avg_vol_prev * 2 and today["close"] < yesterday["close"]:
            fake_breakout_score = 4
        elif yesterday["volume"] > avg_vol_prev * 1.5 and today["close"] < yesterday["open"]:
            fake_breakout_score = 3

    # 假多風險：股價高檔但法人持續賣 + 盤中大跌
    fake_bull_score = 1
    if rt_change_pct < -3:
        fake_bull_score = 5
    elif rt_change_pct < -1.5:
        fake_bull_score = 4
    elif rt_change_pct < -0.8 and is_near_high:
        fake_bull_score = 4
    elif is_near_high and net_buy < 0:
        fake_bull_score = 4
        if foreign_net < 0:
            fake_bull_score = 5
    elif is_near_high and price_change_5d < 0:
        fake_bull_score = 3

    # 誘空風險：融券增加且股價持續上漲
    bear_trap_score = 1
    if short_increase > 0 and price_change_10d > 5:
        bear_trap_score = 4
    elif short_increase > 0 and price_change_5d > 3:
        bear_trap_score = 3

    # ── AI 結論 ──
    conclusion = _generate_conclusion(
        distribute_score, accumulate_score, wash_score,
        fake_bull_score, is_near_high, net_buy, vol_ratio,
        rt_change_pct
    )

    return {
        "wash": {"score": wash_score, "label": "主力洗盤"},
        "accumulate": {"score": accumulate_score, "label": "主力吸籌"},
        "distribute": {"score": distribute_score, "label": "主力出貨"},
        "squeeze": {"score": squeeze_score, "label": "軋空佈局"},
        "fake_breakout": {"score": fake_breakout_score, "label": "假突破"},
        "fake_bull": {"score": fake_bull_score, "label": "假多風險"},
        "bear_trap": {"score": bear_trap_score, "label": "誘空風險"},
        "conclusion": conclusion,
    }


def analyze_day_trade_risk(stock_id: str, days: int = 30) -> dict:
    """
    隔日沖風險分析（模組 2）— 整合即時報價
    """
    from app.services.realtime_context import get_realtime_context

    df = fetch_stock_price(stock_id, days=days)
    ctx = get_realtime_context(stock_id)

    if len(df) < 10:
        return _default_risk_result()

    today = df.iloc[-1]
    recent_5 = df.tail(5)
    recent_20 = df.tail(20)

    avg_vol_20 = recent_20["volume"].mean()
    today_vol = today["volume"]

    # ── 使用即時資料補強 ──
    rt_change = ctx.get("change_pct", 0)
    rt_volume = ctx.get("volume", 0)

    # 如果有即時成交量，用即時的（更準確）
    if rt_volume > 0:
        # 即時量是張，歷史量是股，統一比較
        rt_vol_shares = rt_volume * 1000
        vol_concentration = rt_vol_shares / avg_vol_20 if avg_vol_20 > 0 else 1
    else:
        vol_concentration = today_vol / avg_vol_20 if avg_vol_20 > 0 else 1

    # ── 各項風險評估 ──

    # 1. 券商集中度（盤中跌停或大跌代表主力大量賣出）
    if ctx["is_crashing"]:
        concentration_level = "高"
        concentration_score = 90
    elif ctx["is_dropping"]:
        concentration_level = "高"
        concentration_score = 75
    elif vol_concentration > 3:
        concentration_level = "高"
        concentration_score = 90
    elif vol_concentration > 2:
        concentration_level = "高"
        concentration_score = 75
    elif vol_concentration > 1.5:
        concentration_level = "中"
        concentration_score = 55
    else:
        concentration_level = "低"
        concentration_score = 30

    # 2. 分點集中度
    vol_std = recent_5["volume"].std()
    vol_mean = recent_5["volume"].mean()
    vol_cv = vol_std / vol_mean if vol_mean > 0 else 0

    if ctx["is_crashing"] or vol_cv > 0.5:
        broker_level = "高"
        broker_score = 80
    elif ctx["is_dropping"] or vol_cv > 0.3:
        broker_level = "中"
        broker_score = 55
    else:
        broker_level = "低"
        broker_score = 30

    # 3. 爆量程度
    if ctx["is_crashing"]:
        volume_level = "高"
        volume_score = 95
    elif vol_concentration > 2.5:
        volume_level = "高"
        volume_score = 90
    elif vol_concentration > 1.8 or ctx["is_dropping"]:
        volume_level = "高"
        volume_score = 70
    elif vol_concentration > 1.3:
        volume_level = "中"
        volume_score = 50
    else:
        volume_level = "低"
        volume_score = 25

    # 4. 開高走低風險（即時跌幅就是開高走低的直接證據）
    if rt_change < -3:
        open_high_level = "高"
        open_high_score = 95
    elif rt_change < -1.5:
        open_high_level = "高"
        open_high_score = 80
    elif rt_change < -0.5:
        open_high_level = "中"
        open_high_score = 55
    else:
        # 用歷史K線的上影線判斷
        body = abs(today["close"] - today["open"])
        upper_shadow = today["high"] - max(today["close"], today["open"])
        candle_range = today["high"] - today["low"]
        upper_ratio = upper_shadow / candle_range if candle_range > 0 else 0

        if upper_ratio > 0.6:
            open_high_level = "高"
            open_high_score = 85
        elif upper_ratio > 0.4:
            open_high_level = "中"
            open_high_score = 55
        else:
            open_high_level = "低"
            open_high_score = 25

    # 5. 高檔爆量K風險
    is_high = today["close"] >= recent_20["close"].quantile(0.85)

    if ctx["is_crashing"] and is_high:
        high_vol_level = "高"
        high_vol_score = 95
    elif ctx["is_dropping"] and is_high:
        high_vol_level = "高"
        high_vol_score = 80
    elif is_high and vol_concentration > 2:
        high_vol_level = "高"
        high_vol_score = 90
    elif is_high and vol_concentration > 1.5:
        high_vol_level = "中"
        high_vol_score = 60
    elif is_high:
        high_vol_level = "低"
        high_vol_score = 40
    else:
        high_vol_level = "低"
        high_vol_score = 20

    # 總風險分數（加權平均）
    total_risk = int(
        concentration_score * 0.25 +
        broker_score * 0.2 +
        volume_score * 0.25 +
        open_high_score * 0.15 +
        high_vol_score * 0.15
    )
    total_risk = min(100, max(0, total_risk))

    # 籌碼穩定度（5 星制）
    stability = 5 - int(total_risk / 25)
    stability = max(1, min(5, stability))

    # 明日出貨風險
    if total_risk >= 75:
        tomorrow_risk = "高"
    elif total_risk >= 50:
        tomorrow_risk = "中"
    else:
        tomorrow_risk = "低"

    return {
        "total_risk": total_risk,
        "details": {
            "concentration": {"label": "主力券商集中度", "level": concentration_level, "score": concentration_score},
            "broker": {"label": "分點集中度", "level": broker_level, "score": broker_score},
            "volume": {"label": "爆量程度", "level": volume_level, "score": volume_score},
            "open_high": {"label": "開高走低風險", "level": open_high_level, "score": open_high_score},
            "high_vol_k": {"label": "高檔爆量K風險", "level": high_vol_level, "score": high_vol_score},
        },
        "stability_stars": stability,
        "tomorrow_risk": tomorrow_risk,
    }


def _generate_conclusion(distribute, accumulate, wash, fake_bull, is_high, net_buy, vol_ratio, rt_change_pct=0, is_vol_explode=False) -> str:
    """根據各項分數生成 AI 結論文字"""
    # 即時大跌優先判斷
    if rt_change_pct < -5:
        return "盤中重挫，主力大量出貨，極高風險，建議遠離"
    if rt_change_pct < -3:
        return "盤中急跌，主力出貨跡象明顯，短線風險大幅升高"
    if rt_change_pct < -1.5:
        return "盤中明顯走弱，主力賣壓沉重，留意風險"
    if rt_change_pct < -0.8:
        return "盤中偏弱，短線有賣壓，觀察是否止穩"

    if distribute >= 4:
        return "近期主力有高檔出貨跡象，需留意隔日沖與高檔震盪風險"
    if fake_bull >= 4:
        return "股價位於高檔但法人持續賣超，假多風險升高"
    if accumulate >= 4:
        return "主力持續吸籌中，量增價漲格局，短線偏多操作"
    if wash >= 4:
        return "近期量縮震盪，疑似主力洗盤，可留意洗盤結束後的起漲訊號"
    if is_high and net_buy < 0:
        return "股價高檔區間，法人賣超，需注意追高風險"
    if vol_ratio > 1.5:
        return "近期成交量明顯放大，關注是否為主力進場或出場訊號"
    if rt_change_pct < -1:
        return "盤中走弱，短線偏空，留意支撐是否守住"
    return "目前主力動態無明顯異常，持續觀察籌碼變化"


def _default_result() -> dict:
    """資料不足時的預設結果"""
    return {
        "wash": {"score": 1, "label": "主力洗盤"},
        "accumulate": {"score": 1, "label": "主力吸籌"},
        "distribute": {"score": 1, "label": "主力出貨"},
        "squeeze": {"score": 1, "label": "軋空佈局"},
        "fake_breakout": {"score": 1, "label": "假突破"},
        "fake_bull": {"score": 1, "label": "假多風險"},
        "bear_trap": {"score": 1, "label": "誘空風險"},
        "conclusion": "資料不足，無法分析",
    }


def _default_risk_result() -> dict:
    """資料不足時的預設風險結果"""
    return {
        "total_risk": 0,
        "details": {},
        "stability_stars": 3,
        "tomorrow_risk": "未知",
    }
