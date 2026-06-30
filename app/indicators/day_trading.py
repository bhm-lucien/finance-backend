"""
當沖指標模組
計算做多/做空方向建議（含進場價、目標價、停損），
加入當沖量比、成交比重、VWAP 等精準判斷
盤中自動整合即時報價資料
"""
import pandas as pd
import numpy as np
from app.services.data_fetcher import fetch_stock_price


def analyze_day_trading(stock_id: str, days: int = 30) -> dict:
    """
    當沖指標分析（精準版 + 即時報價整合）
    """
    df = fetch_stock_price(stock_id, days=days)

    if len(df) < 10:
        return _default_result()

    # ── 整合即時報價到最後一根 K 棒 ──
    df = _inject_realtime(df, stock_id)

    today = df.iloc[-1]
    yesterday = df.iloc[-2] if len(df) > 1 else today
    close = float(today["close"])
    high = float(today["high"])
    low = float(today["low"])
    open_price = float(today["open"])
    prev_close = float(yesterday["close"])
    vol_today = float(today["volume"])

    # ── 振幅計算 ──
    spread_today = (high - low) / close * 100 if close > 0 else 0
    df["spread_pct"] = (df["high"] - df["low"]) / df["close"] * 100
    avg_spread_5 = float(df["spread_pct"].tail(5).mean())
    avg_spread_20 = float(df["spread_pct"].tail(20).mean())

    # ── ATR（平均真實區間）──
    df["tr"] = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr_14 = float(df["tr"].tail(14).mean())
    atr_pct = atr_14 / close * 100 if close > 0 else 0

    # ── 成交量分析 ──
    vol_avg_5 = float(df["volume"].tail(5).mean())
    vol_avg_20 = float(df["volume"].tail(20).mean())
    vol_ratio_5 = vol_today / vol_avg_5 if vol_avg_5 > 0 else 1
    vol_ratio_20 = vol_today / vol_avg_20 if vol_avg_20 > 0 else 1

    # ── 當沖比率估算 ──
    # 高換手 + 高振幅 = 當沖活躍
    turnover_proxy = vol_today / (vol_avg_20 * 20) * 100 if vol_avg_20 > 0 else 0
    estimated_day_trade_ratio = min(60, max(5, turnover_proxy * 2 + avg_spread_5 * 5))

    # ── 當沖量比（今日量 / 20日均量）──
    day_trade_volume_ratio = round(vol_ratio_20, 2)

    # ── 成交比重（今日量佔近20日總量的比例）──
    total_vol_20 = float(df["volume"].tail(20).sum())
    trade_weight = round(vol_today / total_vol_20 * 100, 2) if total_vol_20 > 0 else 0

    # ── VWAP 估算（用成交量加權平均價）──
    # 用近期資料估算當日 VWAP
    df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3
    df["tp_vol"] = df["typical_price"] * df["volume"]
    vwap_today = float(today["high"] + today["low"] + today["close"]) / 3
    vwap_5d = float(df["tp_vol"].tail(5).sum() / df["volume"].tail(5).sum()) if float(df["volume"].tail(5).sum()) > 0 else close

    # ── 開盤缺口分析 ──
    gap = open_price - prev_close
    gap_pct = gap / prev_close * 100 if prev_close > 0 else 0
    has_gap_up = gap_pct > 0.5
    has_gap_down = gap_pct < -0.5

    # ── 盤中結構分析 ──
    # 紅 K 實體比例
    body = close - open_price
    body_ratio = abs(body) / (high - low) if (high - low) > 0 else 0
    # 上影線比例
    upper_shadow_ratio = (high - max(open_price, close)) / (high - low) if (high - low) > 0 else 0
    # 下影線比例
    lower_shadow_ratio = (min(open_price, close) - low) / (high - low) if (high - low) > 0 else 0

    # ── 支撐 / 壓力計算（用於進出場）──
    ma5 = float(df["close"].tail(5).mean())
    ma20 = float(df["close"].tail(20).mean())
    recent_high_5 = float(df["high"].tail(5).max())
    recent_low_5 = float(df["low"].tail(5).min())

    # ── 漲跌停限制（台股 10%）──
    limit_up = round(prev_close * 1.10, 2)
    limit_down = round(prev_close * 0.90, 2)

    # ── 做多方向分析（更精準）──
    long_score = 0
    long_reasons = []

    # 因素 1：K 棒方向
    if close > open_price:
        long_score += 2
        long_reasons.append(f"今日紅K，實體比 {round(body_ratio * 100)}%")
    else:
        long_score -= 1
        long_reasons.append("今日黑K，多方力道不足")

    # 因素 2：相對 VWAP
    if close > vwap_today:
        long_score += 1
        long_reasons.append("收盤價高於 VWAP，買盤佔優")
    else:
        long_score -= 1
        long_reasons.append("收盤價低於 VWAP，賣壓偏重")

    # 因素 3：量能
    if vol_ratio_20 >= 1.5:
        long_score += 2
        long_reasons.append(f"量能放大（量比 {round(vol_ratio_20, 1)}x），有助突破")
    elif vol_ratio_20 >= 1.0:
        long_score += 1
        long_reasons.append(f"量能正常（量比 {round(vol_ratio_20, 1)}x）")
    else:
        long_score -= 1
        long_reasons.append(f"量縮（量比 {round(vol_ratio_20, 1)}x），突破力道存疑")

    # 因素 4：位置
    if close > ma5:
        long_score += 1
        long_reasons.append("股價站上5日均線")
    if close > ma20:
        long_score += 1
        long_reasons.append("股價站上20日均線")

    # 因素 5：缺口
    if has_gap_up:
        long_score += 1
        long_reasons.append(f"跳空開高 {round(gap_pct, 1)}%，多方氣勢")

    # 做多方向判定
    if long_score >= 5:
        long_direction = "積極做多"
    elif long_score >= 3:
        long_direction = "偏多操作"
    elif long_score >= 1:
        long_direction = "謹慎做多"
    else:
        long_direction = "不建議做多"

    # 做多進場/目標/停損（基於 ATR 和支撐壓力，限制在漲跌停內）
    long_entry = round(max(close - atr_14 * 0.15, recent_low_5, limit_down), 2)
    long_target = round(min(close + atr_14 * 0.4, recent_high_5 * 1.01, limit_up), 2)
    long_stop = round(max(close - atr_14 * 0.25, limit_down), 2)

    # 檢查風險報酬比：如果目標空間 < 停損空間的 1.5 倍，調整為不適合追高
    long_upside = long_target - long_entry
    long_downside = long_entry - long_stop
    if long_upside < long_downside * 1.5 or long_upside / close * 100 < 1.0:
        # 目標空間太小（離漲停太近），進場改為等拉回
        long_entry = round(max(min(vwap_today, open_price) - atr_14 * 0.05, limit_down), 2)
        long_target = round(min(close + atr_14 * 0.2, limit_up), 2)
        if long_score >= 3:
            long_direction = "等拉回再做多"
            long_reasons.append("目前離漲停太近，追高風險大，等拉回 VWAP 附近再進場")
            long_score = max(1, long_score - 2)

    # ── 做空方向分析（更精準）──
    short_score = 0
    short_reasons = []

    # 因素 1：K 棒方向
    if close < open_price:
        short_score += 2
        short_reasons.append(f"今日黑K，實體比 {round(body_ratio * 100)}%")
    else:
        short_score -= 1
        short_reasons.append("今日紅K，空方力道不足")

    # 因素 2：相對 VWAP
    if close < vwap_today:
        short_score += 1
        short_reasons.append("收盤價低於 VWAP，賣壓佔優")
    else:
        short_score -= 1
        short_reasons.append("收盤價高於 VWAP，買盤偏強")

    # 因素 3：量能（空方有利的量能模式）
    if vol_ratio_20 >= 1.5 and close < open_price:
        short_score += 2
        short_reasons.append("帶量下殺，賣壓沉重")
    elif vol_ratio_20 < 0.7:
        short_score += 1
        short_reasons.append("量縮無力反彈，空方有利")
    else:
        short_reasons.append(f"量比 {round(vol_ratio_20, 1)}x，觀察方向")

    # 因素 4：位置
    if close < ma5:
        short_score += 1
        short_reasons.append("股價跌破5日均線")
    if close < ma20:
        short_score += 1
        short_reasons.append("股價跌破20日均線")

    # 因素 5：缺口
    if has_gap_down:
        short_score += 1
        short_reasons.append(f"跳空開低 {round(abs(gap_pct), 1)}%，空方氣勢")

    # 因素 6：上影線壓力
    if upper_shadow_ratio > 0.4:
        short_score += 1
        short_reasons.append(f"長上影線（{round(upper_shadow_ratio * 100)}%），上方壓力大")

    # 做空方向判定
    if short_score >= 5:
        short_direction = "積極做空"
    elif short_score >= 3:
        short_direction = "偏空操作"
    elif short_score >= 1:
        short_direction = "謹慎做空"
    else:
        short_direction = "不建議做空"

    # 做空進場/目標/停損（限制在漲跌停內）
    short_entry = round(min(close + atr_14 * 0.15, recent_high_5, limit_up), 2)
    short_target = round(max(close - atr_14 * 0.4, recent_low_5 * 0.99, limit_down), 2)
    short_stop = round(min(close + atr_14 * 0.25, limit_up), 2)

    # 檢查風險報酬比：如果目標空間太小（離跌停太近），不建議追空
    short_downside = short_entry - short_target
    short_upside_risk = short_stop - short_entry
    if short_downside < short_upside_risk * 1.5 or short_downside / close * 100 < 1.0:
        short_entry = round(min(max(vwap_today, open_price) + atr_14 * 0.05, limit_up), 2)
        short_target = round(max(close - atr_14 * 0.2, limit_down), 2)
        if short_score >= 3:
            short_direction = "等反彈再做空"
            short_reasons.append("目前離跌停太近，追空風險大，等反彈 VWAP 附近再進場")
            short_score = max(1, short_score - 2)

    return {
        "day_trade_ratio": round(estimated_day_trade_ratio, 1),
        "day_trade_volume_ratio": day_trade_volume_ratio,
        "trade_weight": trade_weight,
        "spread_today": round(spread_today, 2),
        "avg_spread_5d": round(avg_spread_5, 2),
        "atr": round(atr_14, 2),
        "atr_pct": round(atr_pct, 2),
        "vwap": round(vwap_today, 2),
        "vol_ratio": round(vol_ratio_20, 2),
        "gap_pct": round(gap_pct, 2),
        "current_price": close,
        "long": {
            "direction": long_direction,
            "score": long_score,
            "entry": long_entry,
            "target": long_target,
            "stop_loss": long_stop,
            "risk_reward": round((long_target - long_entry) / max(long_entry - long_stop, 0.01), 2),
            "reasons": long_reasons,
        },
        "short": {
            "direction": short_direction,
            "score": short_score,
            "entry": short_entry,
            "target": short_target,
            "stop_loss": short_stop,
            "risk_reward": round((short_entry - short_target) / max(short_stop - short_entry, 0.01), 2),
            "reasons": short_reasons,
        },
    }


def _inject_realtime(df: pd.DataFrame, stock_id: str) -> pd.DataFrame:
    """
    將即時報價注入到 DataFrame 的最後一根 K 棒，
    讓盤中計算能反映即時價格
    """
    try:
        from app.services.realtime import fetch_realtime_price
        rt = fetch_realtime_price(stock_id)

        if rt.get("price", 0) <= 0:
            return df

        price = rt["price"]
        rt_open = rt.get("open", 0)
        rt_high = rt.get("high", 0)
        rt_low = rt.get("low", 0)
        rt_volume = rt.get("volume", 0)

        # 如果即時資料的日期和最後一根 K 棒相同，更新它
        # 如果即時資料是今天但 K 棒資料是昨天，新增一根
        from datetime import datetime, date
        today_date = date.today()
        last_date = df.iloc[-1]["date"]

        if hasattr(last_date, "date"):
            last_date = last_date.date()
        else:
            last_date = pd.to_datetime(last_date).date()

        if last_date == today_date:
            # 更新最後一根
            idx = df.index[-1]
            df.loc[idx, "close"] = price
            if rt_high > 0:
                df.loc[idx, "high"] = max(float(df.loc[idx, "high"]), rt_high)
            if rt_low > 0:
                df.loc[idx, "low"] = min(float(df.loc[idx, "low"]), rt_low)
            if rt_open > 0:
                df.loc[idx, "open"] = rt_open
            if rt_volume > 0:
                df.loc[idx, "volume"] = rt_volume
        else:
            # 新增今日的 K 棒
            new_row = {
                "date": pd.Timestamp(today_date),
                "open": rt_open if rt_open > 0 else price,
                "high": rt_high if rt_high > 0 else price,
                "low": rt_low if rt_low > 0 else price,
                "close": price,
                "volume": rt_volume if rt_volume > 0 else 0,
            }
            # 確保所有原有的欄位都有值
            for col in df.columns:
                if col not in new_row:
                    new_row[col] = df.iloc[-1][col] if col in df.columns else 0
            new_df = pd.DataFrame([new_row])
            df = pd.concat([df, new_df], ignore_index=True)

    except Exception:
        pass

    return df


def _default_result() -> dict:
    return {
        "day_trade_ratio": 0,
        "day_trade_volume_ratio": 0,
        "trade_weight": 0,
        "spread_today": 0,
        "avg_spread_5d": 0,
        "atr": 0,
        "atr_pct": 0,
        "vwap": 0,
        "vol_ratio": 0,
        "gap_pct": 0,
        "current_price": 0,
        "long": {
            "direction": "未知",
            "score": 0,
            "entry": 0,
            "target": 0,
            "stop_loss": 0,
            "reasons": [],
        },
        "short": {
            "direction": "未知",
            "score": 0,
            "entry": 0,
            "target": 0,
            "stop_loss": 0,
            "reasons": [],
        },
    }
