"""
AI 操盤建議模組
整合所有分析結果（含 K 線型態），產出具體的操作建議、價位、勝率
像股票分析師一樣給出明確的買賣建議
"""
import numpy as np
import pandas as pd
from app.services.data_fetcher import fetch_stock_price
from app.indicators.technical import (
    calculate_rsi, calculate_macd, calculate_kd,
    calculate_moving_averages, calculate_bollinger_bands,
    calculate_volume_profile,
)
from app.indicators.kline_pattern import analyze_kline_patterns
from app.services.realtime_context import get_realtime_context


def generate_trading_advice(stock_id: str) -> dict:
    """
    產生完整的 AI 操盤建議

    Returns:
        dict 包含買進價、壓力價、支撐、策略建議、勝率統計等
    """
    df = fetch_stock_price(stock_id, days=180)
    ctx = get_realtime_context(stock_id)

    if len(df) < 30:
        return {"error": "資料不足"}

    # 注入即時報價到最後一根 K 棒
    df = _inject_realtime_to_df(df, stock_id, ctx)

    close = float(df["close"].iloc[-1])
    current_price = ctx["price"] if ctx["price"] > 0 else close

    # ── 計算關鍵技術指標 ──
    ma = calculate_moving_averages(df)
    rsi = float(calculate_rsi(df).iloc[-1])
    macd_data = calculate_macd(df)
    macd_hist = float(macd_data["histogram"].iloc[-1])
    kd = calculate_kd(df)
    k_val = float(kd["k"].iloc[-1])
    bb = calculate_bollinger_bands(df)

    ma5 = float(ma["ma5"].iloc[-1])
    ma10 = float(ma["ma10"].iloc[-1])
    ma20 = float(ma["ma20"].iloc[-1])
    ma60 = float(ma["ma60"].iloc[-1]) if not pd.isna(ma["ma60"].iloc[-1]) else close
    bb_lower = float(bb["lower"].iloc[-1])
    bb_upper = float(bb["upper"].iloc[-1])

    # 近期高低點
    high_20d = float(df["high"].tail(20).max())
    low_20d = float(df["low"].tail(20).min())
    high_60d = float(df["high"].tail(60).max())
    low_60d = float(df["low"].tail(60).min())

    # ATR
    df["tr"] = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr = float(df["tr"].tail(14).mean())

    # ── 漲跌停限制（用昨收計算，確保可靠）──
    yesterday_close = ctx.get("yesterday_close", 0)
    if yesterday_close <= 0:
        # 如果 ctx 沒有昨收，用 df 倒數第二根的收盤價
        yesterday_close = float(df["close"].iloc[-2]) if len(df) > 1 else current_price
    limit_up = round(yesterday_close * 1.10, 2)
    limit_down = round(yesterday_close * 0.90, 2)

    # Volume Profile POC（最大成交量價格帶）
    vp = calculate_volume_profile(df.tail(60), bins=15)
    poc_price = 0
    if vp:
        max_vol_bin = max(vp, key=lambda x: x["volume"])
        poc_price = (max_vol_bin["price_low"] + max_vol_bin["price_high"]) / 2

    # ── 1. 支撐帶分析（買進價位）──
    # 加入更貼近目前價位的支撐參考
    low_5d = float(df["low"].tail(5).min())  # 近 5 日低點
    low_10d = float(df["low"].tail(10).min())  # 近 10 日低點
    atr_support = current_price - atr * 1.0  # ATR 動態支撐

    supports = sorted([
        ma20, ma60, bb_lower, low_20d, poc_price, low_5d, low_10d, atr_support
    ])
    # 取最近的兩個低於目前價格的支撐，但不能離太遠（限制在 10% 內）
    valid_supports = [s for s in supports if s > 0 and s < current_price * 0.99 and s > current_price * 0.90]

    # 如果沒有找到 10% 以內的支撐，用 ATR 動態計算
    if not valid_supports:
        valid_supports = [round(current_price - atr * 1.0, 2), round(current_price - atr * 2.0, 2)]

    primary_support = valid_supports[-1] if valid_supports else round(current_price * 0.95, 2)
    secondary_support = valid_supports[-2] if len(valid_supports) >= 2 else round(current_price - atr * 2.0, 2)

    # ── 2. 壓力帶分析（不追高價位）──
    resistances = sorted([
        high_20d, bb_upper, ma5 if ma5 > current_price else high_60d
    ])
    valid_resistances = [r for r in resistances if r > current_price * 1.01]
    primary_resistance = valid_resistances[0] if valid_resistances else round(current_price + atr * 1.5, 2)

    # ── 3. 建議買進價 ──
    # 理想買進價 = 主要支撐上方一點
    ideal_buy = round(primary_support * 1.005, 2)
    # 不要追高價 = 壓力位下方
    dont_chase_above = round(primary_resistance * 0.98, 2)

    # ── 4. 操作策略判斷 ──
    # 短線適合度
    short_term_ok = rsi < 70 and macd_hist > 0 and k_val < 80
    # 波段適合度
    swing_ok = current_price > ma20 and ma5 > ma20
    # 長線適合度（不適合的條件）
    long_term_risk = rsi > 70 or current_price > high_60d * 0.98

    # ── 5. 情境建議 ──
    scenarios = []

    if ctx["is_crashing"] or ctx["is_dropping"]:
        scenarios.append({
            "condition": "爆量下跌",
            "action": f"跌至 {round(primary_support, 1)} 附近可分批承接，停損設 {round(secondary_support * 0.98, 1)}",
            "color": "green",
        })

    if current_price < ma20:
        # 跌破月線：等支撐止穩再介入
        gap_pct = (ma20 - current_price) / ma20 * 100
        scenarios.append({
            "condition": "跌破月線",
            "action": f"等待 {round(primary_support, 1)} 附近止穩再分批承接，停損設 {round(secondary_support * 0.97, 1)}",
            "color": "orange",
        })

    if current_price > high_20d * 0.98:
        scenarios.append({
            "condition": "突破近期高點",
            "action": f"突破 {round(high_20d, 1)} 可追，但要帶量，停利設 {round(high_20d * 1.05, 1)}",
            "color": "red",
        })

    if rsi > 75:
        scenarios.append({
            "condition": "指標過熱",
            "action": "不適合長抱，短線獲利了結，突破高點就分批賣出",
            "color": "orange",
        })

    if not scenarios:
        if current_price > ma20:
            scenarios.append({
                "condition": "趨勢正常",
                "action": f"在 {round(ma20, 1)}~{round(ma5, 1)} 間拉回可布局",
                "color": "green",
            })
        else:
            scenarios.append({
                "condition": "偏弱整理",
                "action": f"等待 {round(primary_support, 1)} 止穩或量縮不破低再介入",
                "color": "orange",
            })

    # ── 6. 勝率統計（歷史回測）──
    win_rates = _calculate_win_rates(df, ma20, ma60, primary_support, current_price)

    # ── 7. K 線型態分析 ──
    kline_data = analyze_kline_patterns(stock_id)
    kline_bias = _evaluate_kline_bias(kline_data)

    # ── 8. 最高勝率操作邏輯（納入 K 線型態 + 風報比）──
    stop_loss_price = max(secondary_support * 0.97, current_price * 0.90)
    buy_rr = (primary_resistance - ideal_buy) / max(ideal_buy - stop_loss_price, 0.01)

    best_strategy = _determine_best_strategy(
        rsi, macd_hist, k_val, current_price, ma20, ma60,
        primary_support, primary_resistance, win_rates, kline_bias, buy_rr
    )

    # 加入 K 線型態的情境建議
    if kline_bias["signal"] and kline_bias["signal"] != "neutral":
        scenarios.append({
            "condition": f"K線型態：{kline_bias['pattern_name']}",
            "action": kline_bias["suggestion"],
            "color": "red" if kline_bias["signal"] == "bullish" else "green",
        })

    return {
        "current_price": round(current_price, 2),
        "buy_zone": {
            "ideal": round(ideal_buy, 2),
            "support_1": round(primary_support, 2),
            "support_2": round(secondary_support, 2),
        },
        "sell_zone": {
            "dont_chase": round(dont_chase_above, 2),
            "resistance": round(primary_resistance, 2),
            "take_profit": round(primary_resistance * 1.02, 2),
        },
        "stop_loss": round(max(secondary_support * 0.97, current_price * 0.90), 2),
        "day_trade_zone": _calc_day_trade_zone(current_price, atr, limit_up, limit_down, ctx),
        "risk_reward": {
            "buy_rr": round((primary_resistance - ideal_buy) / max(ideal_buy - max(secondary_support * 0.97, current_price * 0.90), 0.01), 2),
            "rating": "佳" if (primary_resistance - ideal_buy) / max(ideal_buy - max(secondary_support * 0.97, current_price * 0.90), 0.01) >= 2 else "普通" if (primary_resistance - ideal_buy) / max(ideal_buy - max(secondary_support * 0.97, current_price * 0.90), 0.01) >= 1.5 else "差",
        },
        "suitability": {
            "short_term": "適合" if short_term_ok else "不適合",
            "swing": "適合" if swing_ok else "不適合",
            "long_term": "注意風險" if long_term_risk else "可考慮",
        },
        "scenarios": scenarios,
        "win_rates": win_rates,
        "best_strategy": best_strategy,
        "kline_pattern": kline_bias.get("pattern_name", ""),
        "predictions": _generate_predictions(df, current_price, atr, ma5, ma20, ma60, rsi, macd_hist, k_val, primary_support, primary_resistance),
        "key_levels": {
            "ma5": round(ma5, 2),
            "ma20": round(ma20, 2),
            "ma60": round(ma60, 2),
            "poc": round(poc_price, 2),
        },
    }


def _evaluate_kline_bias(kline_data: dict) -> dict:
    """
    評估 K 線型態的多空偏向

    Returns:
        {
            "signal": "bullish" / "bearish" / "neutral",
            "score": 2,  # -5 ~ +5
            "pattern_name": "多頭吞噬",
            "suggestion": "K線出現多頭吞噬，短線偏多操作",
        }
    """
    score = 0
    top_pattern = ""
    top_reliability = 0

    # 短期型態加權
    for p in kline_data.get("short_term", []):
        weight = p.get("reliability", 1)
        if p["type"] == "bullish":
            score += weight
        elif p["type"] == "bearish":
            score -= weight

        if weight > top_reliability:
            top_reliability = weight
            top_pattern = p["name"]

    # 長期型態加權（權重 x2）
    for p in kline_data.get("long_term", []):
        weight = p.get("reliability", 1) * 2
        if p["type"] == "bullish":
            score += weight
        elif p["type"] == "bearish":
            score -= weight

        if p.get("reliability", 1) * 2 > top_reliability:
            top_reliability = p.get("reliability", 1) * 2
            top_pattern = p["name"]

    # 判斷信號方向
    if score >= 3:
        signal = "bullish"
        suggestion = f"K線出現{top_pattern}，短線偏多操作，可留意拉回買點"
    elif score <= -3:
        signal = "bearish"
        suggestion = f"K線出現{top_pattern}，短線偏空，宜減碼或觀望"
    else:
        signal = "neutral"
        suggestion = "K線無明確方向訊號"

    return {
        "signal": signal,
        "score": score,
        "pattern_name": top_pattern,
        "suggestion": suggestion,
    }


def _calculate_win_rates(df: pd.DataFrame, ma20: float, ma60: float, support: float, current: float) -> list:
    """計算不同買進價位的歷史勝率（持有 5 日後獲利的比率）"""
    results = []

    # 在 MA20 附近買進的勝率
    ma20_buys = df[abs(df["close"] - ma20) / ma20 < 0.02]
    if len(ma20_buys) > 5:
        wins = 0
        total = 0
        for idx in ma20_buys.index:
            if idx + 5 < len(df):
                future_price = df["close"].iloc[idx + 5]
                buy_price = df["close"].iloc[idx]
                if future_price > buy_price:
                    wins += 1
                total += 1
        if total > 0:
            results.append({
                "label": f"月線({round(ma20, 0)})附近買",
                "price": round(ma20, 2),
                "win_rate": round(wins / total * 100, 0),
                "samples": total,
            })

    # 在支撐附近買進的勝率
    support_buys = df[df["low"] <= support * 1.02]
    if len(support_buys) > 3:
        wins = 0
        total = 0
        for idx in support_buys.index:
            if idx + 5 < len(df):
                future_price = df["close"].iloc[idx + 5]
                buy_price = df["close"].iloc[idx]
                if future_price > buy_price:
                    wins += 1
                total += 1
        if total > 0:
            results.append({
                "label": f"支撐({round(support, 0)})附近買",
                "price": round(support, 2),
                "win_rate": round(wins / total * 100, 0),
                "samples": total,
            })

    # RSI < 30 時買進的勝率
    rsi_series = calculate_rsi(df)
    oversold = df[rsi_series < 30]
    if len(oversold) > 2:
        wins = 0
        total = 0
        for idx in oversold.index:
            if idx + 5 < len(df):
                future_price = df["close"].iloc[idx + 5]
                buy_price = df["close"].iloc[idx]
                if future_price > buy_price:
                    wins += 1
                total += 1
        if total > 0:
            results.append({
                "label": "RSI超賣時買",
                "price": round(float(oversold["close"].mean()), 2),
                "win_rate": round(wins / total * 100, 0),
                "samples": total,
            })

    # 如果都沒資料，給預設
    if not results:
        results.append({
            "label": f"目前價({round(current, 0)})買進",
            "price": round(current, 2),
            "win_rate": 50,
            "samples": 0,
        })

    return sorted(results, key=lambda x: x["win_rate"], reverse=True)


def _determine_best_strategy(rsi, macd_hist, k_val, price, ma20, ma60, support, resistance, win_rates, kline_bias=None, buy_rr=0) -> dict:
    """決定最高勝率的操作邏輯（含 K 線型態 + 風報比參考）"""

    # 找最高勝率
    best_wr = win_rates[0] if win_rates else {"win_rate": 50, "label": "未知"}

    # K 線型態偏向
    kline_signal = kline_bias.get("signal", "neutral") if kline_bias else "neutral"
    kline_pattern = kline_bias.get("pattern_name", "") if kline_bias else ""

    # 風報比評估
    rr_warning = ""
    if buy_rr < 1.5:
        rr_warning = "。風報比偏低（{:.1f}），進場需謹慎".format(buy_rr)
    elif buy_rr >= 2.5 and rsi < 70:
        # 只有在非過熱狀態下，高風報比才建議進場
        rr_warning = "。風報比佳（{:.1f}），逢低可布局".format(buy_rr)
    elif buy_rr >= 2.5 and rsi >= 70:
        rr_warning = "。風報比佳（{:.1f}），但目前指標過熱，建議等拉回".format(buy_rr)

    if price < ma20 and rsi < 40:
        gap_pct = (ma20 - price) / ma20 * 100
        if gap_pct > 3:
            strategy = "等待止穩"
            logic = f"已跌破月線 {round(gap_pct, 1)}%，建議等跌至 {round(support, 1)} 止穩再分批買進"
            action = "逢低分批承接"
        else:
            strategy = "等待止穩"
            logic = f"目前在月線下方且 RSI 偏低，建議等跌至 {round(support, 1)} 再分批買進，勝率較高"
            action = "逢低分批承接"
        # K 線出現多頭訊號，可更積極
        if kline_signal == "bullish":
            logic += f"。K線出現{kline_pattern}，止跌訊號浮現"
            action = "止跌訊號出現，可小量試單"
    elif price > ma20 and macd_hist > 0 and k_val < 75:
        strategy = "順勢做多"
        logic = f"站穩月線且 MACD 多頭，拉回 {round(support, 1)} 附近買進，停損設 {round(support * 0.97, 1)}"
        action = "拉回支撐買進"
        if kline_signal == "bullish":
            logic += f"。K線{kline_pattern}強化多方訊號"
        elif kline_signal == "bearish":
            logic += f"。但K線出現{kline_pattern}，短線留意拉回"
    elif rsi > 70 or k_val > 80:
        strategy = "短線獲利了結"
        logic = f"指標過熱，不追高。持有者在 {round(resistance, 1)} 附近分批賣出，跌破 {round(support, 1)} 停損"
        action = "突破高點分批賣出"
        if kline_signal == "bearish":
            logic += f"。K線{kline_pattern}確認過熱反轉"
    elif price < support * 1.03:
        strategy = "逢低承接"
        logic = f"接近支撐 {round(support, 1)}，可小量試單，停損 {round(support * 0.95, 1)}，目標 {round(resistance, 1)}"
        action = "支撐附近分批買"
        if kline_signal == "bullish":
            logic += f"。K線{kline_pattern}支持反彈"
    else:
        strategy = "觀望等待"
        logic = f"位於中間區間，無明確進場訊號。等拉回 {round(support, 1)} 止穩或突破 {round(resistance, 1)} 帶量再動作"
        action = "等待更好進場點"
        if kline_signal == "bullish":
            strategy = "偏多觀察"
            logic += f"。K線{kline_pattern}顯示多方蓄力"
        elif kline_signal == "bearish":
            strategy = "偏空觀察"
            logic += f"。K線{kline_pattern}顯示短線偏弱"

    # 加入風報比提醒到策略邏輯
    logic += rr_warning

    return {
        "strategy": strategy,
        "logic": logic,
        "action": action,
        "best_win_rate": best_wr.get("win_rate", 50),
        "best_method": best_wr.get("label", ""),
        "risk_reward_ratio": round(buy_rr, 2),
    }


def _calc_day_trade_zone(current_price: float, atr: float, limit_up: float, limit_down: float, ctx: dict) -> dict:
    """
    計算當沖買賣區間
    做多：等拉回到支撐再進場（VWAP、開盤價、盤中低點）
    做空：等反彈到壓力再進場（盤中高點附近）
    """
    rt_open = ctx.get("open", 0) or current_price
    rt_high = ctx.get("high", 0) or current_price
    rt_low = ctx.get("low", 0) or current_price

    # VWAP 估算（用今日開高低收的均值）
    vwap_est = (rt_open + rt_high + rt_low + current_price) / 4

    # ── 做多：等拉回到支撐位再進場 ──
    # 進場參考：VWAP、今日開盤價、盤中低點 + 小幅度
    # 取其中最接近現價但低於現價的位置
    long_supports = sorted([
        vwap_est,
        rt_open,
        rt_low + atr * 0.05,
    ])
    # 選低於現價的最高支撐（最近的拉回位）
    valid_long_entries = [s for s in long_supports if s < current_price * 0.995]
    if valid_long_entries:
        long_entry = valid_long_entries[-1]  # 最接近現價的支撐
    else:
        # 如果沒有（例如已經在低點），用現價小拉回
        long_entry = current_price * 0.995

    # 做多目標：從進場往上 ATR 的 0.3
    long_target = min(long_entry + atr * 0.3, limit_up)
    # 做多停損：進場往下 ATR 的 0.15
    long_stop = max(long_entry - atr * 0.15, limit_down)

    # ── 做空：等反彈到壓力位再進場 ──
    # 做空進場應在高點/壓力位附近（等反彈到高點才空）
    short_resistances = sorted([
        rt_high,  # 今日高點
        rt_high - atr * 0.03,  # 高點略下方
        limit_up * 0.995,  # 接近漲停
    ])
    # 選高於現價的位置（等反彈上去才進場做空）
    valid_short_entries = [r for r in short_resistances if r > current_price * 1.005]
    if valid_short_entries:
        short_entry = valid_short_entries[0]  # 最接近現價的壓力
    else:
        # 已在高點附近，用今日高點作為進場參考
        short_entry = rt_high

    # 做空目標：拉回到 VWAP 或開盤價（取較近的）
    short_targets = sorted([vwap_est, rt_open])
    valid_short_targets = [t for t in short_targets if t < short_entry * 0.99]
    if valid_short_targets:
        short_target = max(valid_short_targets[-1], limit_down)
    else:
        short_target = max(short_entry - atr * 0.3, limit_down)

    # 做空停損：進場往上 ATR 的 0.1（或漲停）
    short_stop = min(short_entry + atr * 0.1, limit_up)

    return {
        "buy_entry": round(long_entry, 2),
        "buy_target": round(long_target, 2),
        "buy_stop": round(long_stop, 2),
        "sell_entry": round(short_entry, 2),
        "sell_target": round(short_target, 2),
        "sell_stop": round(short_stop, 2),
        "vwap": round(vwap_est, 2),
    }


def _generate_predictions(df: pd.DataFrame, current_price: float, atr: float,
                          ma5: float, ma20: float, ma60: float,
                          rsi: float, macd_hist: float, k_val: float,
                          support: float, resistance: float) -> dict:
    """
    產生盤前/盤中/盤後三時段預測

    Returns:
        {
            "pre_market": {"direction": "高開", "est_change_pct": 1.2, "reason": "..."},
            "intraday": {"est_close": 810, "est_high": 825, "est_low": 795, "reason": "..."},
            "after_market": {"tomorrow_direction": "偏多", "tomorrow_open_range": [800, 815], "reason": "..."},
        }
    """
    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)

    # 最近的漲跌資訊
    prev_close = float(closes[-2]) if len(closes) > 1 else current_price
    recent_avg_change = float(np.mean(np.diff(closes[-5:]))) if len(closes) > 5 else 0

    # ── 盤前預測：今日開盤方向 ──
    # 如果已有今日開盤價（盤中），用實際資料；否則用預測
    today_open = float(df["open"].iloc[-1])
    actual_gap_pct = (today_open - prev_close) / prev_close * 100 if prev_close > 0 else 0

    if today_open > 0 and abs(actual_gap_pct) > 0.01:
        # 盤中：用實際開盤資料
        if actual_gap_pct > 1:
            pre_direction = "高開"
        elif actual_gap_pct > 0.3:
            pre_direction = "小高開"
        elif actual_gap_pct < -1:
            pre_direction = "低開"
        elif actual_gap_pct < -0.3:
            pre_direction = "小低開"
        else:
            pre_direction = "平開"
        pre_change_pct = round(actual_gap_pct, 2)
        pre_reason = f"今日實際開盤 {today_open:.2f}，缺口 {actual_gap_pct:.1f}%"
    else:
        # 盤前：預測
        pre_direction = "平開"
        pre_change_pct = 0.0
        pre_reason = ""

        if macd_hist > 0 and rsi < 70:
            pre_direction = "偏高開"
            pre_change_pct = round(min(atr / current_price * 30, 3.0), 2)
            pre_reason = "MACD 多頭且未過熱，開盤偏強機率高"
        elif macd_hist < 0 and rsi > 50:
            pre_direction = "偏低開"
            pre_change_pct = round(max(-atr / current_price * 30, -3.0), 2)
            pre_reason = "MACD 空頭轉折中，開盤偏弱機率高"
        elif recent_avg_change > 0:
            pre_direction = "小高開"
            pre_change_pct = round(min(recent_avg_change / current_price * 100, 2.0), 2)
            pre_reason = "近期趨勢偏多，慣性高開"
        elif recent_avg_change < 0:
            pre_direction = "小低開"
            pre_change_pct = round(max(recent_avg_change / current_price * 100, -2.0), 2)
            pre_reason = "近期趨勢偏空，慣性低開"
        else:
            pre_reason = "多空均衡，預估平開"

    # ── 盤中預測：收盤價位 + 高低點 ──
    # 預估今日高低基於 ATR，但限制在漲跌停範圍內
    prev_close_for_limit = float(closes[-2]) if len(closes) > 1 else current_price
    limit_up = round(prev_close_for_limit * 1.10, 2)
    limit_down = round(prev_close_for_limit * 0.90, 2)

    # 計算目前離漲停/跌停的距離
    dist_to_limit_up_pct = (limit_up - current_price) / current_price * 100 if current_price > 0 else 10
    dist_to_limit_down_pct = (current_price - limit_down) / current_price * 100 if current_price > 0 else 10

    est_high = round(min(current_price + atr * 0.3, limit_up), 2)
    est_low = round(max(current_price - atr * 0.3, limit_down), 2)

    # 預估收盤：根據趨勢和指標，也限制在漲跌停內
    # 如果已經接近漲停（< 2%），預估收盤不會再到漲停
    if dist_to_limit_up_pct < 2:
        # 接近漲停，大概率高檔震盪或小拉回
        est_close = round(current_price * 0.995, 2)
        intraday_reason = "接近漲停，預估高檔震盪"
    elif dist_to_limit_down_pct < 2:
        # 接近跌停，大概率低檔震盪或小反彈
        est_close = round(current_price * 1.005, 2)
        intraday_reason = "接近跌停，預估低檔震盪"
    elif rsi > 65 and macd_hist > 0:
        est_close = round(min(current_price + atr * 0.1, limit_up), 2)
        intraday_reason = "指標偏強，預估收盤偏高"
    elif rsi < 35 and macd_hist < 0:
        est_close = round(max(current_price - atr * 0.1, limit_down), 2)
        intraday_reason = "指標偏弱，預估收盤偏低"
    elif k_val > 80:
        est_close = round(max(current_price - atr * 0.05, limit_down), 2)
        intraday_reason = "KD 過熱，尾盤可能拉回"
    elif k_val < 20:
        est_close = round(min(current_price + atr * 0.05, limit_up), 2)
        intraday_reason = "KD 超賣，尾盤可能反彈"
    else:
        est_close = current_price
        intraday_reason = "多空均衡，預估收平"

    # ── 盤後預測：明日走勢 ──
    tomorrow_direction = "觀望"
    # 明日開盤區間限制在當日收盤的 ±3% 內（合理範圍）
    tomorrow_open_low = round(current_price * 0.97, 2)
    tomorrow_open_high = round(current_price * 1.03, 2)
    after_reason = ""

    if current_price > ma5 > ma20 and macd_hist > 0:
        tomorrow_direction = "偏多"
        tomorrow_open_low = round(current_price * 0.99, 2)
        tomorrow_open_high = round(current_price * 1.03, 2)
        after_reason = "均線多頭排列，MACD 正向，明日偏強"
    elif current_price < ma5 < ma20 and macd_hist < 0:
        tomorrow_direction = "偏空"
        tomorrow_open_low = round(current_price * 0.97, 2)
        tomorrow_open_high = round(current_price * 1.01, 2)
        after_reason = "均線空頭排列，MACD 負向，明日偏弱"
    elif rsi > 75:
        tomorrow_direction = "過熱拉回"
        tomorrow_open_low = round(current_price * 0.97, 2)
        tomorrow_open_high = round(current_price * 1.01, 2)
        after_reason = "RSI 過熱，明日可能獲利回吐"
    elif rsi < 25:
        tomorrow_direction = "超賣反彈"
        tomorrow_open_low = round(current_price * 0.99, 2)
        tomorrow_open_high = round(current_price * 1.03, 2)
        after_reason = "RSI 超賣，明日可能技術反彈"
    else:
        tomorrow_direction = "震盪"
        tomorrow_open_low = round(current_price * 0.98, 2)
        tomorrow_open_high = round(current_price * 1.02, 2)
        after_reason = "無明確方向，預估明日窄幅震盪"

    return {
        "pre_market": {
            "direction": pre_direction,
            "est_change_pct": pre_change_pct,
            "reason": pre_reason,
        },
        "intraday": {
            "est_close": est_close,
            "est_high": est_high,
            "est_low": est_low,
            "reason": intraday_reason,
        },
        "after_market": {
            "tomorrow_direction": tomorrow_direction,
            "tomorrow_open_range": [tomorrow_open_low, tomorrow_open_high],
            "reason": after_reason,
        },
    }


def _inject_realtime_to_df(df: pd.DataFrame, stock_id: str, ctx: dict) -> pd.DataFrame:
    """
    將即時報價注入到 DataFrame 的最後一根 K 棒，
    確保盤中計算能反映即時價格
    """
    try:
        price = ctx.get("price", 0)
        if price <= 0:
            return df

        from datetime import date
        today_date = date.today()
        last_date = df.iloc[-1]["date"]

        if hasattr(last_date, "date"):
            last_date = last_date.date()
        else:
            last_date = pd.to_datetime(last_date).date()

        if last_date == today_date:
            # 更新最後一根 K 棒的收盤價為即時價
            idx = df.index[-1]
            df.loc[idx, "close"] = price
            if ctx.get("high", 0) > 0:
                df.loc[idx, "high"] = max(float(df.loc[idx, "high"]), ctx["high"])
            if ctx.get("low", 0) > 0:
                df.loc[idx, "low"] = min(float(df.loc[idx, "low"]), ctx["low"])
        else:
            # 新增今日 K 棒
            new_row = {
                "date": pd.Timestamp(today_date),
                "open": ctx.get("open", price) or price,
                "high": ctx.get("high", price) or price,
                "low": ctx.get("low", price) or price,
                "close": price,
                "volume": ctx.get("volume", 0) or 0,
            }
            for col in df.columns:
                if col not in new_row:
                    new_row[col] = 0
            new_df = pd.DataFrame([new_row])
            df = pd.concat([df, new_df], ignore_index=True)

    except Exception:
        pass

    return df
