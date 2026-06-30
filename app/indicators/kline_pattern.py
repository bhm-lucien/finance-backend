"""
K 線型態辨識模組
辨識短期（1~3 根）及中長期組合型態，
給出多空意義與後續走勢預測
"""
import pandas as pd
import numpy as np
from app.services.data_fetcher import fetch_stock_price


def analyze_kline_patterns(stock_id: str, days: int = 120) -> dict:
    """
    K 線型態分析

    Returns:
        {
            "short_term": [  # 短期型態（近 1~3 根 K 線）
                {
                    "name": "錘子線",
                    "type": "bullish",  # bullish / bearish / neutral
                    "meaning": "下跌趨勢中出現，暗示底部反轉",
                    "prediction": "短線可能止跌反彈",
                    "reliability": 3,  # 1~5 可靠度
                }
            ],
            "long_term": [  # 中長期組合型態
                {
                    "name": "W 底",
                    "type": "bullish",
                    "meaning": "雙重底部確認，趨勢可能反轉向上",
                    "prediction": "中期看多，目標頸線上方等幅",
                    "reliability": 4,
                }
            ],
            "summary": "短期出現錘子線止跌訊號，中期疑似形成W底，偏多看待"
        }
    """
    df = fetch_stock_price(stock_id, days=days)

    if len(df) < 20:
        return {"short_term": [], "long_term": [], "summary": "資料不足，無法辨識"}

    # 計算輔助欄位
    df["body"] = df["close"] - df["open"]
    df["body_abs"] = df["body"].abs()
    df["upper_shadow"] = df["high"] - df[["open", "close"]].max(axis=1)
    df["lower_shadow"] = df[["open", "close"]].min(axis=1) - df["low"]
    df["range"] = df["high"] - df["low"]
    df["avg_body"] = df["body_abs"].rolling(20).mean()

    short_term = _detect_short_term_patterns(df)
    long_term = _detect_long_term_patterns(df)
    summary = _generate_summary(short_term, long_term)

    return {
        "short_term": short_term,
        "long_term": long_term,
        "summary": summary,
    }


def _detect_short_term_patterns(df: pd.DataFrame) -> list[dict]:
    """辨識短期 K 線型態（最近 1~3 根）"""
    patterns = []

    if len(df) < 3:
        return patterns

    today = df.iloc[-1]
    yesterday = df.iloc[-2]
    day_before = df.iloc[-3]

    body = float(today["body"])
    body_abs = float(today["body_abs"])
    upper = float(today["upper_shadow"])
    lower = float(today["lower_shadow"])
    rng = float(today["range"])
    avg_body = float(today["avg_body"]) if not pd.isna(today["avg_body"]) else body_abs

    # 避免除以零
    if rng == 0:
        rng = 0.01
    if avg_body == 0:
        avg_body = 0.01

    # ── 單根 K 線型態 ──

    # 十字星（Doji）
    if body_abs < rng * 0.1:
        if upper > rng * 0.3 and lower > rng * 0.3:
            patterns.append({
                "name": "長腳十字星",
                "type": "neutral",
                "meaning": "多空激烈拉鋸，趨勢即將轉向",
                "prediction": "需觀察隔日方向確認，可能反轉",
                "reliability": 3,
            })
        else:
            patterns.append({
                "name": "十字星",
                "type": "neutral",
                "meaning": "市場猶豫不決，前趨勢可能暫停",
                "prediction": "等待隔日確認方向",
                "reliability": 2,
            })

    # 錘子線（Hammer）— 下跌趨勢中，長下影線
    elif lower > body_abs * 2 and upper < body_abs * 0.5:
        # 檢查是否在下跌趨勢中
        recent_trend = float(df["close"].iloc[-5:].mean() - df["close"].iloc[-10:-5].mean())
        if recent_trend < 0:
            patterns.append({
                "name": "錘子線",
                "type": "bullish",
                "meaning": "下跌趨勢中出現長下影線，買方力道浮現",
                "prediction": "短線可能止跌反彈，隔日收紅確認",
                "reliability": 3,
            })
        else:
            patterns.append({
                "name": "吊人線",
                "type": "bearish",
                "meaning": "上漲趨勢中出現長下影線，賣壓開始浮現",
                "prediction": "短線漲勢可能暫歇，注意回落風險",
                "reliability": 3,
            })

    # 射擊之星（Shooting Star）— 長上影線
    elif upper > body_abs * 2 and lower < body_abs * 0.5:
        recent_trend = float(df["close"].iloc[-5:].mean() - df["close"].iloc[-10:-5].mean())
        if recent_trend > 0:
            patterns.append({
                "name": "射擊之星",
                "type": "bearish",
                "meaning": "上漲趨勢中出現長上影線，上方壓力沉重",
                "prediction": "短線可能拉回，注意壓力位",
                "reliability": 3,
            })
        else:
            patterns.append({
                "name": "倒錘子線",
                "type": "bullish",
                "meaning": "下跌趨勢中出現倒錘，買方嘗試反攻",
                "prediction": "若隔日收紅確認，可能止跌",
                "reliability": 2,
            })

    # 大陽線
    elif body > avg_body * 1.5 and body > 0:
        patterns.append({
            "name": "大陽線",
            "type": "bullish",
            "meaning": "強勁買盤進場，多方佔絕對優勢",
            "prediction": "短線續漲機率高，但注意追高風險",
            "reliability": 3,
        })

    # 大陰線
    elif body < -avg_body * 1.5:
        patterns.append({
            "name": "大陰線",
            "type": "bearish",
            "meaning": "強勁賣壓湧出，空方佔絕對優勢",
            "prediction": "短線續跌機率高，不宜搶反彈",
            "reliability": 3,
        })

    # ── 雙根 K 線型態 ──

    y_body = float(yesterday["body"])
    y_body_abs = float(yesterday["body_abs"])

    # 多頭吞噬（Bullish Engulfing）
    if (y_body < 0 and body > 0 and
        float(today["open"]) <= float(yesterday["close"]) and
        float(today["close"]) >= float(yesterday["open"]) and
        body_abs > y_body_abs):
        patterns.append({
            "name": "多頭吞噬",
            "type": "bullish",
            "meaning": "陰線後出現大陽線完全包覆，買方強勢反攻",
            "prediction": "反轉向上機率高，可留意進場點",
            "reliability": 4,
        })

    # 空頭吞噬（Bearish Engulfing）
    elif (y_body > 0 and body < 0 and
          float(today["open"]) >= float(yesterday["close"]) and
          float(today["close"]) <= float(yesterday["open"]) and
          body_abs > y_body_abs):
        patterns.append({
            "name": "空頭吞噬",
            "type": "bearish",
            "meaning": "陽線後出現大陰線完全包覆，賣方強勢壓制",
            "prediction": "反轉向下機率高，宜減碼觀望",
            "reliability": 4,
        })

    # 多頭孕線（Bullish Harami）
    elif (y_body < 0 and body > 0 and
          y_body_abs > body_abs * 1.5 and
          float(today["open"]) > float(yesterday["close"]) and
          float(today["close"]) < float(yesterday["open"])):
        patterns.append({
            "name": "多頭孕線",
            "type": "bullish",
            "meaning": "大陰後小陽被包在前一根實體內，跌勢可能暫緩",
            "prediction": "止跌訊號，等確認後可試單",
            "reliability": 2,
        })

    # 空頭孕線（Bearish Harami）
    elif (y_body > 0 and body < 0 and
          y_body_abs > body_abs * 1.5 and
          float(today["open"]) < float(yesterday["close"]) and
          float(today["close"]) > float(yesterday["open"])):
        patterns.append({
            "name": "空頭孕線",
            "type": "bearish",
            "meaning": "大陽後小陰被包在前一根實體內，漲勢可能暫緩",
            "prediction": "觀望訊號，注意隔日走勢",
            "reliability": 2,
        })

    # ── 三根 K 線型態 ──

    db_body = float(day_before["body"])

    # 晨星（Morning Star）
    if (db_body < 0 and float(day_before["body_abs"]) > avg_body and
        float(yesterday["body_abs"]) < avg_body * 0.5 and
        body > 0 and body_abs > avg_body * 0.8):
        patterns.append({
            "name": "晨星",
            "type": "bullish",
            "meaning": "大陰 → 小K → 大陽，經典底部反轉訊號",
            "prediction": "中短線反轉向上機率高",
            "reliability": 4,
        })

    # 夜星（Evening Star）
    elif (db_body > 0 and float(day_before["body_abs"]) > avg_body and
          float(yesterday["body_abs"]) < avg_body * 0.5 and
          body < 0 and body_abs > avg_body * 0.8):
        patterns.append({
            "name": "夜星",
            "type": "bearish",
            "meaning": "大陽 → 小K → 大陰，經典頂部反轉訊號",
            "prediction": "中短線反轉向下機率高",
            "reliability": 4,
        })

    # 紅三兵（Three White Soldiers）
    if (db_body > 0 and y_body > 0 and body > 0 and
        float(yesterday["close"]) > float(day_before["close"]) and
        float(today["close"]) > float(yesterday["close"])):
        patterns.append({
            "name": "紅三兵",
            "type": "bullish",
            "meaning": "連三日收紅且持續創高，多方氣勢強勁",
            "prediction": "續漲機率高，可順勢做多",
            "reliability": 4,
        })

    # 黑三兵（Three Black Crows）
    elif (db_body < 0 and y_body < 0 and body < 0 and
          float(yesterday["close"]) < float(day_before["close"]) and
          float(today["close"]) < float(yesterday["close"])):
        patterns.append({
            "name": "黑三兵",
            "type": "bearish",
            "meaning": "連三日收黑且持續破低，空方氣勢強勁",
            "prediction": "續跌機率高，不宜做多",
            "reliability": 4,
        })

    # 如果沒有偵測到明確型態
    if not patterns:
        if body > 0:
            patterns.append({
                "name": "普通陽線",
                "type": "neutral",
                "meaning": "一般紅K，無特殊型態",
                "prediction": "無明確方向訊號",
                "reliability": 1,
            })
        else:
            patterns.append({
                "name": "普通陰線",
                "type": "neutral",
                "meaning": "一般黑K，無特殊型態",
                "prediction": "無明確方向訊號",
                "reliability": 1,
            })

    return patterns


def _detect_long_term_patterns(df: pd.DataFrame) -> list[dict]:
    """辨識中長期組合型態"""
    patterns = []

    if len(df) < 30:
        return patterns

    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)

    # ── W 底（Double Bottom）──
    w_bottom = _detect_double_bottom(lows, closes)
    if w_bottom:
        patterns.append(w_bottom)

    # ── M 頭（Double Top）──
    m_top = _detect_double_top(highs, closes)
    if m_top:
        patterns.append(m_top)

    # ── 頭肩底 ──
    hs_bottom = _detect_head_shoulders_bottom(lows, closes)
    if hs_bottom:
        patterns.append(hs_bottom)

    # ── 頭肩頂 ──
    hs_top = _detect_head_shoulders_top(highs, closes)
    if hs_top:
        patterns.append(hs_top)

    # ── 三角收斂 ──
    triangle = _detect_triangle(highs, lows, closes)
    if triangle:
        patterns.append(triangle)

    # ── 上升趨勢 / 下降趨勢 ──
    trend = _detect_trend(closes)
    if trend:
        patterns.append(trend)

    return patterns


def _detect_double_bottom(lows: np.ndarray, closes: np.ndarray) -> dict | None:
    """偵測 W 底型態（近 40 根 K 線）"""
    window = min(40, len(lows))
    recent_lows = lows[-window:]
    recent_closes = closes[-window:]

    # 找兩個低點
    min_idx = np.argmin(recent_lows)
    min_val = recent_lows[min_idx]

    # 在最低點前後各找第二個低點
    tolerance = min_val * 0.03  # 3% 容差

    second_low_idx = None
    for i in range(len(recent_lows)):
        if abs(i - min_idx) > 5 and recent_lows[i] < min_val + tolerance:
            second_low_idx = i
            break

    if second_low_idx is None:
        return None

    # 確認兩低點之間有反彈（頸線）
    start = min(min_idx, second_low_idx)
    end = max(min_idx, second_low_idx)
    if end - start < 5:
        return None

    neckline = float(np.max(recent_closes[start:end]))

    # 確認目前股價在頸線附近或突破
    current = float(closes[-1])
    if current > neckline * 0.97:
        target = neckline + (neckline - min_val)
        return {
            "name": "W 底（雙重底）",
            "type": "bullish",
            "meaning": f"雙重底確認，頸線約 {round(neckline, 1)}，底部支撐 {round(min_val, 1)}",
            "prediction": f"突破頸線後目標 {round(target, 1)}，回測頸線可布局",
            "reliability": 4,
        }

    return None


def _detect_double_top(highs: np.ndarray, closes: np.ndarray) -> dict | None:
    """偵測 M 頭型態（近 40 根 K 線）"""
    window = min(40, len(highs))
    recent_highs = highs[-window:]
    recent_closes = closes[-window:]

    max_idx = np.argmax(recent_highs)
    max_val = recent_highs[max_idx]

    tolerance = max_val * 0.03

    second_high_idx = None
    for i in range(len(recent_highs)):
        if abs(i - max_idx) > 5 and recent_highs[i] > max_val - tolerance:
            second_high_idx = i
            break

    if second_high_idx is None:
        return None

    start = min(max_idx, second_high_idx)
    end = max(max_idx, second_high_idx)
    if end - start < 5:
        return None

    neckline = float(np.min(recent_closes[start:end]))
    current = float(closes[-1])

    if current < neckline * 1.03:
        target = neckline - (max_val - neckline)
        return {
            "name": "M 頭（雙重頂）",
            "type": "bearish",
            "meaning": f"雙重頂確認，頸線約 {round(neckline, 1)}，頂部壓力 {round(max_val, 1)}",
            "prediction": f"跌破頸線目標 {round(target, 1)}，反彈頸線為壓力",
            "reliability": 4,
        }

    return None


def _detect_head_shoulders_bottom(lows: np.ndarray, closes: np.ndarray) -> dict | None:
    """偵測頭肩底型態（近 60 根 K 線）"""
    window = min(60, len(lows))
    if window < 30:
        return None

    recent_lows = lows[-window:]

    # 找三個低點：左肩、頭、右肩
    # 頭應該是最低的
    head_idx = np.argmin(recent_lows)
    head_val = recent_lows[head_idx]

    # 左肩：頭之前的局部低點
    if head_idx < 8:
        return None
    left_region = recent_lows[:head_idx - 3]
    if len(left_region) < 5:
        return None
    left_idx = np.argmin(left_region)
    left_val = left_region[left_idx]

    # 右肩：頭之後的局部低點
    if head_idx + 8 > window:
        return None
    right_region = recent_lows[head_idx + 3:]
    if len(right_region) < 5:
        return None
    right_idx = np.argmin(right_region)
    right_val = right_region[right_idx]

    # 驗證：頭低於兩肩，兩肩高度接近
    if head_val >= left_val or head_val >= right_val:
        return None
    if abs(left_val - right_val) / left_val > 0.05:
        return None

    neckline = float(max(closes[left_idx:head_idx].max(), closes[head_idx:head_idx + right_idx + 3].max()))
    current = float(closes[-1])

    if current > neckline * 0.97:
        return {
            "name": "頭肩底",
            "type": "bullish",
            "meaning": f"經典反轉型態，頸線約 {round(neckline, 1)}",
            "prediction": "突破頸線後中期看多，回測頸線為買點",
            "reliability": 5,
        }

    return None


def _detect_head_shoulders_top(highs: np.ndarray, closes: np.ndarray) -> dict | None:
    """偵測頭肩頂型態（近 60 根 K 線）"""
    window = min(60, len(highs))
    if window < 30:
        return None

    recent_highs = highs[-window:]

    head_idx = np.argmax(recent_highs)
    head_val = recent_highs[head_idx]

    if head_idx < 8:
        return None
    left_region = recent_highs[:head_idx - 3]
    if len(left_region) < 5:
        return None
    left_idx = np.argmax(left_region)
    left_val = left_region[left_idx]

    if head_idx + 8 > window:
        return None
    right_region = recent_highs[head_idx + 3:]
    if len(right_region) < 5:
        return None
    right_idx = np.argmax(right_region)
    right_val = right_region[right_idx]

    if head_val <= left_val or head_val <= right_val:
        return None
    if abs(left_val - right_val) / left_val > 0.05:
        return None

    neckline = float(min(closes[left_idx:head_idx].min(), closes[head_idx:head_idx + right_idx + 3].min()))
    current = float(closes[-1])

    if current < neckline * 1.03:
        return {
            "name": "頭肩頂",
            "type": "bearish",
            "meaning": f"經典反轉型態，頸線約 {round(neckline, 1)}",
            "prediction": "跌破頸線後中期看空，反彈頸線為賣點",
            "reliability": 5,
        }

    return None


def _detect_triangle(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> dict | None:
    """偵測三角收斂型態（近 20 根）"""
    window = min(20, len(highs))
    if window < 10:
        return None

    recent_highs = highs[-window:]
    recent_lows = lows[-window:]

    # 計算高點是否越來越低、低點是否越來越高
    half = window // 2
    first_half_high = float(recent_highs[:half].max())
    second_half_high = float(recent_highs[half:].max())
    first_half_low = float(recent_lows[:half].min())
    second_half_low = float(recent_lows[half:].min())

    high_contracting = second_half_high < first_half_high
    low_rising = second_half_low > first_half_low

    if high_contracting and low_rising:
        # 對稱三角收斂
        current = float(closes[-1])
        midpoint = (second_half_high + second_half_low) / 2
        if abs(current - midpoint) / midpoint < 0.03:
            return {
                "name": "三角收斂",
                "type": "neutral",
                "meaning": f"高點下移、低點上移，波動收窄，即將選擇方向",
                "prediction": "突破上緣看多，跌破下緣看空，等待方向確認",
                "reliability": 3,
            }
    elif high_contracting and not low_rising:
        # 下降三角形
        return {
            "name": "下降三角形",
            "type": "bearish",
            "meaning": "高點持續下移但低點持平，賣壓逐漸加重",
            "prediction": "跌破水平支撐可能加速下跌",
            "reliability": 3,
        }
    elif not high_contracting and low_rising:
        # 上升三角形
        return {
            "name": "上升三角形",
            "type": "bullish",
            "meaning": "低點持續上移但高點持平，買盤逐漸堆積",
            "prediction": "突破水平壓力可能加速上漲",
            "reliability": 3,
        }

    return None


def _detect_trend(closes: np.ndarray) -> dict | None:
    """偵測整體趨勢方向"""
    if len(closes) < 20:
        return None

    ma5 = float(np.mean(closes[-5:]))
    ma20 = float(np.mean(closes[-20:]))
    ma60 = float(np.mean(closes[-60:])) if len(closes) >= 60 else ma20

    current = float(closes[-1])

    if current > ma5 > ma20 > ma60:
        return {
            "name": "多頭排列",
            "type": "bullish",
            "meaning": "短中長期均線多頭排列，趨勢健康向上",
            "prediction": "順勢做多，拉回均線為買點",
            "reliability": 4,
        }
    elif current < ma5 < ma20 < ma60:
        return {
            "name": "空頭排列",
            "type": "bearish",
            "meaning": "短中長期均線空頭排列，趨勢持續向下",
            "prediction": "不宜做多，反彈均線為壓力",
            "reliability": 4,
        }
    elif ma5 > ma20 and current < ma5:
        return {
            "name": "短線拉回",
            "type": "neutral",
            "meaning": "中期趨勢尚可，但短期拉回修正中",
            "prediction": "等待止穩再進場，跌破20日線轉弱",
            "reliability": 2,
        }

    return None


def _generate_summary(short_term: list, long_term: list) -> str:
    """產生綜合總結"""
    parts = []

    # 短期型態總結
    bullish_short = [p for p in short_term if p["type"] == "bullish"]
    bearish_short = [p for p in short_term if p["type"] == "bearish"]

    if bullish_short:
        names = "、".join(p["name"] for p in bullish_short)
        parts.append(f"短期出現{names}，偏多訊號")
    elif bearish_short:
        names = "、".join(p["name"] for p in bearish_short)
        parts.append(f"短期出現{names}，偏空訊號")
    else:
        parts.append("短期無明確方向訊號")

    # 長期型態總結
    bullish_long = [p for p in long_term if p["type"] == "bullish"]
    bearish_long = [p for p in long_term if p["type"] == "bearish"]

    if bullish_long:
        names = "、".join(p["name"] for p in bullish_long)
        parts.append(f"中長期呈現{names}結構")
    elif bearish_long:
        names = "、".join(p["name"] for p in bearish_long)
        parts.append(f"中長期呈現{names}結構")

    # 綜合判斷
    total_bull = len(bullish_short) + len(bullish_long) * 2
    total_bear = len(bearish_short) + len(bearish_long) * 2

    if total_bull > total_bear + 1:
        parts.append("整體偏多看待")
    elif total_bear > total_bull + 1:
        parts.append("整體偏空看待")
    else:
        parts.append("多空未明，宜觀望")

    return "；".join(parts)
