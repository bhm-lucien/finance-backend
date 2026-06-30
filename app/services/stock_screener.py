"""
強勢股篩選系統
從全市場篩選符合條件的強勢股（技術面 + 籌碼面 + 資訊面）
"""
import time
import pandas as pd
from app.services.data_fetcher import fetch_stock_price, fetch_institutional_investors
from app.indicators.technical import calculate_rsi, calculate_macd, calculate_moving_averages
from app.services.stock_list import fetch_all_stocks
from app.services.industry import fetch_industry_classification


_screener_cache: dict[str, dict] = {}
CACHE_TTL = 1800  # 30 分鐘快取


def screen_strong_stocks(top_n: int = 5, industry: str = "") -> list[dict]:
    """
    篩選強勢股

    Args:
        top_n: 回傳前幾名
        industry: 產業篩選（空字串=全市場）

    Returns:
        list of {
            "stock_id": "2330",
            "name": "台積電",
            "score": 85,
            "price": 2400,
            "change_pct": 2.5,
            "reasons": ["突破月線", "外資連買", "RSI轉強"],
        }
    """
    cache_key = f"screener_{industry}_{top_n}"
    if cache_key in _screener_cache:
        entry = _screener_cache[cache_key]
        if time.time() - entry["time"] < CACHE_TTL:
            return entry["data"]

    # 取得股票清單
    if industry:
        # 篩選特定產業
        data = fetch_industry_classification()
        stocks = []
        for cat in data.get("categories", []):
            if industry in cat["name"]:
                stocks = [{"id": s["id"], "name": s["name"]} for s in cat["stocks"]]
                break
    else:
        # 全市場 — 取前 200 支成交量大的股票（避免太多 API 呼叫）
        all_stocks = fetch_all_stocks()
        # 只取四位數代碼的一般股票
        stocks = [s for s in all_stocks if len(s["id"]) == 4 and s["id"].isdigit()][:100]

    if not stocks:
        return []

    # 逐一評分
    scored_stocks = []
    for stock in stocks:
        try:
            score_data = _score_stock(stock["id"], stock["name"])
            if score_data and score_data["score"] >= 60:  # 只保留 60 分以上的
                scored_stocks.append(score_data)
        except Exception:
            continue

        # 限制 API 呼叫數量（避免被限流）
        if len(scored_stocks) >= top_n * 3:
            break

    # 排序取前 N 名
    scored_stocks.sort(key=lambda x: x["score"], reverse=True)
    result = scored_stocks[:top_n]

    _screener_cache[cache_key] = {"data": result, "time": time.time()}
    return result


def _score_stock(stock_id: str, name: str) -> dict | None:
    """評估單一個股的強勢分數"""
    try:
        df = fetch_stock_price(stock_id, days=60)
        if len(df) < 20:
            return None

        close = float(df["close"].iloc[-1])
        prev_close = float(df["close"].iloc[-2])
        change_pct = (close - prev_close) / prev_close * 100

        # ── 技術面評分 ──
        tech_score = 0
        reasons = []

        # 均線
        ma = calculate_moving_averages(df)
        ma5 = float(ma["ma5"].iloc[-1])
        ma20 = float(ma["ma20"].iloc[-1])

        if close > ma5 > ma20:
            tech_score += 20
            reasons.append("均線多頭排列")
        elif close > ma20:
            tech_score += 10

        # RSI
        rsi = float(calculate_rsi(df).iloc[-1])
        if 50 < rsi < 70:
            tech_score += 15
            reasons.append(f"RSI轉強({rsi:.0f})")
        elif rsi > 70:
            tech_score += 5  # 過熱扣分

        # MACD
        macd_data = calculate_macd(df)
        macd_hist = float(macd_data["histogram"].iloc[-1])
        if macd_hist > 0:
            tech_score += 15
            reasons.append("MACD多頭")

        # 突破高點
        high_20d = float(df["high"].tail(20).max())
        if close >= high_20d * 0.98:
            tech_score += 15
            reasons.append("突破近期高點")

        # 量能
        vol_today = float(df["volume"].iloc[-1])
        vol_avg = float(df["volume"].tail(20).mean())
        vol_ratio = vol_today / vol_avg if vol_avg > 0 else 1
        if vol_ratio > 1.5:
            tech_score += 10
            reasons.append(f"量能放大({vol_ratio:.1f}x)")

        # ── 籌碼面評分 ──
        chip_score = 0
        try:
            inst_df = fetch_institutional_investors(stock_id, days=10)
            if not inst_df.empty and "buy" in inst_df.columns:
                net_buy = inst_df["buy"].sum() - inst_df["sell"].sum()
                if net_buy > 0:
                    chip_score += 15
                    reasons.append("法人買超")
        except Exception:
            pass

        # ── 漲幅加分 ──
        momentum_score = 0
        if change_pct > 3:
            momentum_score += 10
            reasons.append(f"今日漲{change_pct:.1f}%")
        elif change_pct > 1:
            momentum_score += 5

        total_score = tech_score + chip_score + momentum_score

        if total_score < 30:
            return None

        return {
            "stock_id": stock_id,
            "name": name,
            "score": min(100, total_score),
            "price": round(close, 2),
            "change_pct": round(change_pct, 2),
            "reasons": reasons[:4],  # 最多 4 個理由
        }

    except Exception:
        return None
