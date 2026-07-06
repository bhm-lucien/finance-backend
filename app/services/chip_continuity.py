"""
籌碼連續性分析服務

提供：
1. 外資/投信連買排行
2. 大戶持股變化
3. 融資融券趨勢
"""
import time
import pandas as pd
from datetime import datetime, timedelta
from app.services.data_fetcher import fetch_institutional_investors, fetch_margin_trading, fetch_stock_price
from app.services.stock_list import fetch_all_stocks


_continuity_cache: dict[str, dict] = {}
CACHE_TTL = 600  # 10 分鐘快取


def analyze_chip_continuity(stock_id: str, days: int = 30) -> dict:
    """
    分析單一個股的籌碼連續性

    Returns:
        {
            "foreign_streak": int,        # 外資連買天數（負數=連賣）
            "trust_streak": int,          # 投信連買天數
            "foreign_total": int,         # 外資近N日累計買賣超(張)
            "trust_total": int,           # 投信近N日累計
            "margin_trend": str,          # 融資趨勢（增加/減少/持平）
            "short_trend": str,           # 融券趨勢
            "margin_change": int,         # 融資增減(張)
            "short_change": int,          # 融券增減(張)
            "big_holder_change": float,   # 大戶持股變化(%)（用法人買賣推估）
        }
    """
    cache_key = f"chip_{stock_id}_{days}"
    if cache_key in _continuity_cache:
        entry = _continuity_cache[cache_key]
        if time.time() - entry["time"] < CACHE_TTL:
            return entry["data"]

    result = {
        "stock_id": stock_id,
        "foreign_streak": 0,
        "trust_streak": 0,
        "foreign_total": 0,
        "trust_total": 0,
        "margin_trend": "持平",
        "short_trend": "持平",
        "margin_change": 0,
        "short_change": 0,
        "big_holder_change": 0.0,
    }

    # 法人買賣超
    try:
        inst_df = fetch_institutional_investors(stock_id, days=days)
        if not inst_df.empty and "name" in inst_df.columns:
            # 外資
            foreign = inst_df[inst_df["name"].str.contains("外資|Foreign_Investor", na=False)].copy()
            if not foreign.empty and "buy" in foreign.columns and "sell" in foreign.columns:
                foreign["net"] = foreign["buy"] - foreign["sell"]
                # 按日期分組加總
                foreign["date_str"] = foreign["date"].dt.strftime("%Y-%m-%d")
                daily_foreign = foreign.groupby("date_str")["net"].sum().reset_index()
                daily_foreign = daily_foreign.sort_values("date_str")

                result["foreign_total"] = int(daily_foreign["net"].sum())
                result["foreign_streak"] = _calc_streak(daily_foreign["net"].tolist())

            # 投信
            trust = inst_df[inst_df["name"].str.contains("投信|Investment_Trust", na=False)].copy()
            if not trust.empty and "buy" in trust.columns and "sell" in trust.columns:
                trust["net"] = trust["buy"] - trust["sell"]
                trust["date_str"] = trust["date"].dt.strftime("%Y-%m-%d")
                daily_trust = trust.groupby("date_str")["net"].sum().reset_index()
                daily_trust = daily_trust.sort_values("date_str")

                result["trust_total"] = int(daily_trust["net"].sum())
                result["trust_streak"] = _calc_streak(daily_trust["net"].tolist())

            # 大戶持股變化推估（外資+投信淨買/發行股數 近似）
            total_net = result["foreign_total"] + result["trust_total"]
            # 取得近期平均成交量作為基準
            try:
                price_df = fetch_stock_price(stock_id, days=30)
                if len(price_df) > 0:
                    avg_vol = price_df["volume"].mean()
                    if avg_vol > 0:
                        result["big_holder_change"] = round(total_net / avg_vol * 100, 2)
            except Exception:
                pass

    except Exception:
        pass

    # 融資融券
    try:
        margin_df = fetch_margin_trading(stock_id, days=days)
        if not margin_df.empty and len(margin_df) >= 2:
            if "MarginPurchaseTodayBalance" in margin_df.columns:
                first_margin = float(margin_df["MarginPurchaseTodayBalance"].iloc[0])
                last_margin = float(margin_df["MarginPurchaseTodayBalance"].iloc[-1])
                change = last_margin - first_margin
                result["margin_change"] = int(change)
                if change > 100:
                    result["margin_trend"] = "增加"
                elif change < -100:
                    result["margin_trend"] = "減少"
                else:
                    result["margin_trend"] = "持平"

            if "ShortSaleTodayBalance" in margin_df.columns:
                first_short = float(margin_df["ShortSaleTodayBalance"].iloc[0])
                last_short = float(margin_df["ShortSaleTodayBalance"].iloc[-1])
                change = last_short - first_short
                result["short_change"] = int(change)
                if change > 50:
                    result["short_trend"] = "增加"
                elif change < -50:
                    result["short_trend"] = "減少"
                else:
                    result["short_trend"] = "持平"

    except Exception:
        pass

    _continuity_cache[cache_key] = {"data": result, "time": time.time()}
    return result


def get_continuous_buy_ranking(top_n: int = 20, days: int = 30) -> dict:
    """
    取得外資/投信連買排行榜

    Returns:
        {
            "foreign_top": [...],  # 外資連買天數排行
            "trust_top": [...],    # 投信連買天數排行
            "update_time": "..."
        }
    """
    cache_key = f"ranking_{top_n}_{days}"
    if cache_key in _continuity_cache:
        entry = _continuity_cache[cache_key]
        if time.time() - entry["time"] < CACHE_TTL:
            return entry["data"]

    all_stocks = fetch_all_stocks()
    # 只掃描四碼股票
    stock_ids = [sid for sid in all_stocks.keys() if len(sid) == 4 and sid.isdigit()][:30]

    foreign_list = []
    trust_list = []

    for sid in stock_ids:
        try:
            chip = analyze_chip_continuity(sid, days=days)
            name = all_stocks.get(sid, sid)

            if chip["foreign_streak"] > 0:
                foreign_list.append({
                    "stock_id": sid,
                    "name": name,
                    "streak": chip["foreign_streak"],
                    "total": chip["foreign_total"],
                })

            if chip["trust_streak"] > 0:
                trust_list.append({
                    "stock_id": sid,
                    "name": name,
                    "streak": chip["trust_streak"],
                    "total": chip["trust_total"],
                })

        except Exception:
            continue

    # 排序取前 N
    foreign_list.sort(key=lambda x: x["streak"], reverse=True)
    trust_list.sort(key=lambda x: x["streak"], reverse=True)

    result = {
        "foreign_top": foreign_list[:top_n],
        "trust_top": trust_list[:top_n],
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    _continuity_cache[cache_key] = {"data": result, "time": time.time()}
    return result


def _calc_streak(values: list) -> int:
    """
    計算連續方向天數
    正數 = 連買天數，負數 = 連賣天數
    """
    if not values:
        return 0

    streak = 0
    last_direction = None

    for val in reversed(values):
        if val > 0:
            direction = "buy"
        elif val < 0:
            direction = "sell"
        else:
            break  # 碰到 0 就中斷

        if last_direction is None:
            last_direction = direction
            streak = 1
        elif direction == last_direction:
            streak += 1
        else:
            break

    if last_direction == "sell":
        return -streak
    return streak
