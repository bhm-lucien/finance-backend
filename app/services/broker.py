"""
主力拉抬分析服務
分析外資、投信、自營商、散戶的買賣超趨勢，
並列出買超/賣超前三名券商
"""
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from app.config import FINMIND_API_URL, FINMIND_TOKEN
from app.services.data_fetcher import fetch_institutional_investors, fetch_stock_price


# ── 快取 ──
_broker_cache: dict[str, dict] = {}
CACHE_TTL = 1800  # 30 分鐘


def _get_cache(key: str):
    if key in _broker_cache:
        entry = _broker_cache[key]
        if time.time() - entry["time"] < CACHE_TTL:
            return entry["data"]
        del _broker_cache[key]
    return None


def _set_cache(key: str, data):
    _broker_cache[key] = {"data": data, "time": time.time()}


def _fetch_broker_top(stock_id: str, days: int = 10) -> dict:
    """
    從 FinMind 取得券商分點資料，計算買超/賣超前三名
    """
    cache_key = f"broker_top_{stock_id}_{days}"
    cached = _get_cache(cache_key)
    if cached is not None:
        return cached

    start_date = (datetime.now() - timedelta(days=days + 10)).strftime("%Y-%m-%d")

    params = {
        "dataset": "TaiwanStockTradingDailyReport",
        "data_id": stock_id,
        "start_date": start_date,
    }
    if FINMIND_TOKEN:
        params["token"] = FINMIND_TOKEN

    try:
        response = requests.get(FINMIND_API_URL, params=params, timeout=15)
        data = response.json()

        if data.get("status") != 200 or not data.get("data"):
            result = {"top_buyers": [], "top_sellers": []}
            _set_cache(cache_key, result)
            return result

        df = pd.DataFrame(data["data"])
        df["date"] = pd.to_datetime(df["date"])

        # 取最近 N 個交易日
        trading_dates = sorted(df["date"].unique())
        recent_dates = trading_dates[-days:] if len(trading_dates) >= days else trading_dates
        df = df[df["date"].isin(recent_dates)]

        # 計算每個券商的淨買超合計
        df["net_buy"] = df["buy"] - df["sell"]
        broker_net = df.groupby("securities_trader")["net_buy"].sum().reset_index()
        broker_net.columns = ["broker", "net_buy"]

        # 買超前三
        top_buyers = broker_net.nlargest(3, "net_buy")
        top_buyers_list = [
            {"broker": row["broker"], "net_buy": int(row["net_buy"])}
            for _, row in top_buyers.iterrows()
            if row["net_buy"] > 0
        ]

        # 賣超前三（最大賣超）
        top_sellers = broker_net.nsmallest(3, "net_buy")
        top_sellers_list = [
            {"broker": row["broker"], "net_sell": int(abs(row["net_buy"]))}
            for _, row in top_sellers.iterrows()
            if row["net_buy"] < 0
        ]

        result = {"top_buyers": top_buyers_list, "top_sellers": top_sellers_list}
        _set_cache(cache_key, result)
        return result

    except Exception:
        result = {"top_buyers": [], "top_sellers": []}
        _set_cache(cache_key, result)
        return result


def analyze_market_forces(stock_id: str) -> dict:
    """
    分析誰在拉抬：外資、投信、自營商、散戶

    Returns:
        {
            "forces": {
                "foreign": {"name": "外資", "net_buy": 3000, "consecutive_days": 5, "trend": "積極買入"},
                "investment_trust": {"name": "投信", "net_buy": 500, "consecutive_days": 3, "trend": "買進"},
                "dealer": {"name": "自營商", "net_buy": -200, "consecutive_days": 0, "trend": "調節"},
                "retail": {"name": "散戶", "net_buy": -1500, "consecutive_days": 0, "trend": "賣出中"},
            },
            "conclusion": "目前主要由外資拉抬",
            "top_buyers": [...],
            "top_sellers": [...],
        }
    """
    cache_key = f"forces_{stock_id}"
    cached = _get_cache(cache_key)
    if cached is not None:
        return cached

    # 取得三大法人買賣超（近 15 天，足夠分析連續天數）
    inst_df = fetch_institutional_investors(stock_id, days=15)

    # 取得股價（用來估算散戶）
    try:
        price_df = fetch_stock_price(stock_id, days=15)
    except Exception:
        price_df = pd.DataFrame()

    forces = {
        "foreign": {"name": "外資", "net_buy": 0, "consecutive_days": 0, "trend": "無資料"},
        "investment_trust": {"name": "投信", "net_buy": 0, "consecutive_days": 0, "trend": "無資料"},
        "dealer": {"name": "自營商", "net_buy": 0, "consecutive_days": 0, "trend": "無資料"},
        "retail": {"name": "散戶", "net_buy": 0, "consecutive_days": 0, "trend": "無資料"},
    }

    if inst_df.empty:
        result = {
            "forces": forces,
            "conclusion": "資料不足，無法判斷",
            "top_buyers": [],
            "top_sellers": [],
        }
        _set_cache(cache_key, result)
        return result

    # ── 解析三大法人資料 ──
    # FinMind 的欄位：date, stock_id, name (外資/投信/自營商), buy, sell
    # name 可能為 "Foreign_Investor", "Investment_Trust", "Dealer_self", "Dealer_Hedging"
    inst_df["net"] = inst_df["buy"] - inst_df["sell"]

    # 識別法人類型的 mapping
    foreign_keywords = ["Foreign", "外資", "外國"]
    trust_keywords = ["Investment_Trust", "投信"]
    dealer_keywords = ["Dealer", "自營"]

    def classify_investor(name: str) -> str:
        name_str = str(name)
        for kw in foreign_keywords:
            if kw in name_str:
                return "foreign"
        for kw in trust_keywords:
            if kw in name_str:
                return "investment_trust"
        for kw in dealer_keywords:
            if kw in name_str:
                return "dealer"
        return "other"

    inst_df["investor_type"] = inst_df["name"].apply(classify_investor)

    # 按投資人類型和日期彙總
    daily_summary = inst_df.groupby(["date", "investor_type"])["net"].sum().reset_index()

    # 取得所有交易日（排序）
    all_dates = sorted(daily_summary["date"].unique())

    # 分析各法人
    total_institutional_net = 0

    for inv_type, force_key in [("foreign", "foreign"), ("investment_trust", "investment_trust"), ("dealer", "dealer")]:
        inv_data = daily_summary[daily_summary["investor_type"] == inv_type].sort_values("date")

        if inv_data.empty:
            continue

        # 累計淨買超（近 5 日）
        recent_5 = inv_data.tail(5)
        net_buy_total = int(recent_5["net"].sum())
        total_institutional_net += net_buy_total

        # 計算連續買/賣超天數（從最近一日回推）
        consecutive = 0
        for _, row in inv_data.iloc[::-1].iterrows():
            if net_buy_total >= 0 and row["net"] > 0:
                consecutive += 1
            elif net_buy_total < 0 and row["net"] < 0:
                consecutive += 1
            else:
                break

        # 趨勢判斷
        if net_buy_total > 0:
            if consecutive >= 4:
                trend = "積極買入"
            elif consecutive >= 2:
                trend = "買進"
            else:
                trend = "小幅買超"
        elif net_buy_total < 0:
            if consecutive >= 4:
                trend = "持續賣出"
            elif consecutive >= 2:
                trend = "調節"
            else:
                trend = "小幅賣超"
        else:
            trend = "觀望"

        forces[force_key] = {
            "name": forces[force_key]["name"],
            "net_buy": net_buy_total,
            "consecutive_days": consecutive,
            "trend": trend,
        }

    # ── 散戶估算 ──
    # 散戶 ≈ 總成交量的買賣方向 - 三大法人淨買超
    # 簡化：散戶淨買超 = -三大法人淨買超（零和遊戲）
    retail_net = -total_institutional_net

    retail_consecutive = 0
    # 用每日資料估算散戶連續天數
    daily_inst_total = daily_summary.groupby("date")["net"].sum().reset_index()
    daily_inst_total = daily_inst_total.sort_values("date")
    for _, row in daily_inst_total.iloc[::-1].iterrows():
        retail_daily = -row["net"]
        if retail_net >= 0 and retail_daily > 0:
            retail_consecutive += 1
        elif retail_net < 0 and retail_daily < 0:
            retail_consecutive += 1
        else:
            break

    if retail_net > 0:
        if retail_consecutive >= 4:
            retail_trend = "積極買入"
        elif retail_consecutive >= 2:
            retail_trend = "買進"
        else:
            retail_trend = "小幅買超"
    elif retail_net < 0:
        if retail_consecutive >= 4:
            retail_trend = "持續賣出"
        elif retail_consecutive >= 2:
            retail_trend = "賣出中"
        else:
            retail_trend = "小幅賣超"
    else:
        retail_trend = "觀望"

    forces["retail"] = {
        "name": "散戶",
        "net_buy": retail_net,
        "consecutive_days": retail_consecutive,
        "trend": retail_trend,
    }

    # ── 總結判斷 ──
    # 找出最大買超者
    force_list = [
        (forces["foreign"]["name"], forces["foreign"]["net_buy"]),
        (forces["investment_trust"]["name"], forces["investment_trust"]["net_buy"]),
        (forces["dealer"]["name"], forces["dealer"]["net_buy"]),
        (forces["retail"]["name"], forces["retail"]["net_buy"]),
    ]
    force_list.sort(key=lambda x: x[1], reverse=True)

    top_buyer = force_list[0]
    top_seller = force_list[-1]

    if top_buyer[1] > 0:
        conclusion = f"目前主要由{top_buyer[0]}拉抬"
        # 如果前兩名都在買
        if force_list[1][1] > 0:
            conclusion += f"，{force_list[1][0]}同步買進"
    elif top_seller[1] < 0:
        conclusion = f"目前{top_seller[0]}為主要賣壓"
    else:
        conclusion = "各方力量均衡，觀望態勢"

    # ── 券商買賣超前三名 ──
    broker_top = _fetch_broker_top(stock_id, days=5)

    result = {
        "forces": forces,
        "conclusion": conclusion,
        "top_buyers": broker_top["top_buyers"],
        "top_sellers": broker_top["top_sellers"],
    }

    _set_cache(cache_key, result)
    return result
