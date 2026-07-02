"""
股票分析 API 路由
"""
import asyncio
from fastapi import APIRouter, HTTPException, Query
from app.services.data_fetcher import (
    fetch_stock_price,
    fetch_institutional_investors,
    fetch_margin_trading,
)
from app.indicators.technical import calculate_all_indicators
from app.indicators.chip_analysis import analyze_main_force, analyze_day_trade_risk
from app.indicators.scoring import (
    calculate_radar_scores,
    generate_scenarios,
    calculate_health_scores,
    determine_signal_light,
)
from app.indicators.sentiment import calculate_sentiment, generate_ai_summary

router = APIRouter(prefix="/api/stock", tags=["stock"])


@router.get("/analysis/{stock_id}")
async def get_stock_analysis(
    stock_id: str,
    days: int = Query(default=120, ge=30, le=365),
):
    """
    取得個股完整分析資料，包含 OHLCV + 技術指標 + Volume Profile
    """
    try:
        df = await asyncio.to_thread(fetch_stock_price, stock_id, days)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    indicators = await asyncio.to_thread(calculate_all_indicators, df)

    # 最新一筆收盤資訊
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest

    price_change = float(latest["close"] - prev["close"])
    price_change_pct = (price_change / float(prev["close"])) * 100

    return {
        "stock_id": stock_id,
        "latest": {
            "date": str(latest["date"].date()),
            "open": float(latest["open"]),
            "high": float(latest["high"]),
            "low": float(latest["low"]),
            "close": float(latest["close"]),
            "volume": int(latest["volume"]),
            "change": round(price_change, 2),
            "change_pct": round(price_change_pct, 2),
        },
        "indicators": indicators,
    }


@router.get("/institutional/{stock_id}")
async def get_institutional_data(
    stock_id: str,
    days: int = Query(default=30, ge=7, le=90),
):
    """
    取得三大法人買賣超資料
    """
    df = fetch_institutional_investors(stock_id, days=days)

    if df.empty:
        return {"stock_id": stock_id, "data": []}

    # 轉換日期格式
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return {
        "stock_id": stock_id,
        "data": df.to_dict(orient="records"),
    }


@router.get("/margin/{stock_id}")
async def get_margin_data(
    stock_id: str,
    days: int = Query(default=30, ge=7, le=90),
):
    """
    取得融資融券資料
    """
    df = fetch_margin_trading(stock_id, days=days)

    if df.empty:
        return {"stock_id": stock_id, "data": []}

    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return {
        "stock_id": stock_id,
        "data": df.to_dict(orient="records"),
    }


@router.get("/main-force/{stock_id}")
async def get_main_force_analysis(stock_id: str):
    """
    取得主力意圖分析（模組 1）
    """
    try:
        result = analyze_main_force(stock_id)
        return {"stock_id": stock_id, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失敗：{str(e)}")


@router.get("/day-trade-risk/{stock_id}")
async def get_day_trade_risk(stock_id: str):
    """
    取得隔日沖風險分析（模組 2）
    """
    try:
        result = analyze_day_trade_risk(stock_id)
        return {"stock_id": stock_id, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失敗：{str(e)}")


@router.get("/radar/{stock_id}")
async def get_radar_scores(stock_id: str):
    """飆股雷達圖評分（模組 3）"""
    try:
        return {"stock_id": stock_id, **calculate_radar_scores(stock_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scenarios/{stock_id}")
async def get_scenarios(stock_id: str):
    """明日劇本推演（模組 4）"""
    try:
        return {"stock_id": stock_id, **generate_scenarios(stock_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health/{stock_id}")
async def get_health_scores(stock_id: str):
    """個股健康度評分（模組 8）"""
    try:
        return {"stock_id": stock_id, **calculate_health_scores(stock_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signal/{stock_id}")
async def get_signal_light(stock_id: str):
    """飆股預警燈號（模組 9）"""
    try:
        return {"stock_id": stock_id, **determine_signal_light(stock_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sentiment/{stock_id}")
async def get_sentiment(stock_id: str):
    """台股情緒指數（模組 11）"""
    try:
        return {"stock_id": stock_id, **calculate_sentiment(stock_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary/{stock_id}")
async def get_ai_summary(stock_id: str):
    """AI 總結與投資建議（模組 12）"""
    try:
        # 收集各模組資料
        from app.indicators.chip_analysis import analyze_main_force, analyze_day_trade_risk

        modules_data = {
            "main_force": analyze_main_force(stock_id),
            "day_trade_risk": analyze_day_trade_risk(stock_id),
            "radar": calculate_radar_scores(stock_id),
            "health": calculate_health_scores(stock_id),
            "signal": determine_signal_light(stock_id),
            "sentiment": calculate_sentiment(stock_id),
            "bull_bear": {},  # 從 technical 已算好
        }

        # 取得多空比
        from app.indicators.technical import calculate_all_indicators
        df = fetch_stock_price(stock_id, days=60)
        indicators = calculate_all_indicators(df)
        modules_data["bull_bear"] = indicators.get("bull_bear", {})

        result = generate_ai_summary(stock_id, modules_data)
        return {"stock_id": stock_id, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/realtime/{stock_id}")
async def get_realtime_price(stock_id: str):
    """取得即時股價（證交所盤中報價）"""
    from app.services.realtime import fetch_realtime_price
    try:
        result = fetch_realtime_price(stock_id)
        return {"stock_id": stock_id, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/intraday/{stock_id}")
async def get_intraday_ticks(stock_id: str):
    """取得今日盤中分時走勢資料"""
    from app.services.realtime import fetch_intraday_ticks
    try:
        ticks = fetch_intraday_ticks(stock_id)
        return {"stock_id": stock_id, "ticks": ticks, "count": len(ticks)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market-indices")
async def get_market_indices():
    """取得大盤指標（台指期、道瓊、S&P500、那斯達克、費半）"""
    from app.services.market_index import fetch_market_indices
    try:
        indices = fetch_market_indices()
        return {"indices": indices}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stock-list")
async def get_stock_list():
    """取得全部台股上市上櫃股票清單（代碼 + 名稱）"""
    from app.services.stock_list import fetch_all_stocks
    try:
        stocks = fetch_all_stocks()
        return {"count": len(stocks), "stocks": stocks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/day-trading/{stock_id}")
async def get_day_trading_analysis(stock_id: str):
    """取得當沖指標分析"""
    from app.indicators.day_trading import analyze_day_trading
    try:
        result = analyze_day_trading(stock_id)
        return {"stock_id": stock_id, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/news")
async def get_news(stock_id: str = ""):
    """取得財經新聞（台股 + 國際 + 個股）"""
    from app.services.news import fetch_finance_news
    try:
        news = fetch_finance_news(stock_id)
        return {"news": news, "count": len(news)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market-limit-stats")
async def get_market_limit_stats():
    """取得全市場漲跌停家數統計"""
    import requests as req
    import time as t

    try:
        # 從證交所取得大盤統計
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw&json=1&delay=0&_={int(t.time()*1000)}"
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://mis.twse.com.tw/"}
        response = req.get(url, headers=headers, timeout=10)
        data = response.json()

        # 嘗試從證交所漲跌統計 API
        stats_url = "https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&type=MS"
        stats_resp = req.get(stats_url, headers=headers, timeout=10)
        stats_data = stats_resp.json()

        limit_up = 0
        limit_down = 0
        up_count = 0
        down_count = 0
        flat_count = 0

        if stats_data.get("stat") == "OK" and stats_data.get("data8"):
            # data8 通常有漲跌家數統計
            for row in stats_data["data8"]:
                if "漲停" in str(row[0]):
                    limit_up = int(str(row[1]).replace(",", "")) if row[1] else 0
                elif "跌停" in str(row[0]):
                    limit_down = int(str(row[1]).replace(",", "")) if row[1] else 0
                elif "上漲" in str(row[0]):
                    up_count = int(str(row[1]).replace(",", "")) if row[1] else 0
                elif "下跌" in str(row[0]):
                    down_count = int(str(row[1]).replace(",", "")) if row[1] else 0
                elif "持平" in str(row[0]):
                    flat_count = int(str(row[1]).replace(",", "")) if row[1] else 0

        return {
            "limit_up": limit_up,
            "limit_down": limit_down,
            "up_count": up_count,
            "down_count": down_count,
            "flat_count": flat_count,
        }
    except Exception as e:
        return {
            "limit_up": 0,
            "limit_down": 0,
            "up_count": 0,
            "down_count": 0,
            "flat_count": 0,
            "error": str(e),
        }


@router.get("/trading-advice/{stock_id}")
async def get_trading_advice(stock_id: str):
    """取得 AI 操盤建議（模組 15）"""
    from app.indicators.trading_advice import generate_trading_advice
    try:
        result = generate_trading_advice(stock_id)
        return {"stock_id": stock_id, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/broker-accumulation/{stock_id}")
async def get_broker_accumulation(stock_id: str):
    """取得主力拉抬分析（外資/投信/自營商/散戶 + 券商前三）"""
    from app.services.broker import analyze_market_forces
    try:
        result = analyze_market_forces(stock_id)
        return {"stock_id": stock_id, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/industry-classification")
async def get_industry_classification():
    """取得 TWSE 官方產業分類及成分股"""
    from app.services.industry import fetch_industry_classification
    try:
        result = fetch_industry_classification()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/kline-pattern/{stock_id}")
async def get_kline_pattern(stock_id: str):
    """取得 K 線型態辨識分析"""
    from app.indicators.kline_pattern import analyze_kline_patterns
    try:
        result = analyze_kline_patterns(stock_id)
        return {"stock_id": stock_id, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trendline/{stock_id}")
async def get_trendline(stock_id: str):
    """取得 K 棒趨勢線分析"""
    from app.indicators.trendline import calculate_trendlines
    try:
        result = calculate_trendlines(stock_id)
        return {"stock_id": stock_id, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sector-flow")
async def get_sector_flow(days: int = Query(default=5, ge=1, le=30)):
    """
    取得產業板塊資金流向分析
    包含各板塊的法人資金流入/流出、漲潮/退潮狀態
    """
    from app.services.sector_flow import fetch_sector_flow
    try:
        result = fetch_sector_flow(days=days)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/filter/conditions")
async def get_filter_conditions():
    """取得所有可用的篩選條件列表"""
    from app.services.stock_filter import get_available_conditions
    return {"conditions": get_available_conditions()}


@router.post("/filter")
async def filter_stocks_api(body: dict):
    """
    條件式篩選股票

    Body: {"conditions": ["above_ma20", "macd_bull", "vol_surge"], "max_results": 30}
    """
    from app.services.stock_filter import filter_stocks
    conditions = body.get("conditions", [])
    max_results = body.get("max_results", 30)

    if not conditions:
        raise HTTPException(status_code=400, detail="請至少選擇一個篩選條件")

    try:
        result = filter_stocks(conditions=conditions, max_results=max_results)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cache/stats")
async def get_cache_stats():
    """取得快取統計（debug 用）"""
    from app.services.cache_db import cache_stats
    return cache_stats()


@router.post("/cache/clear")
async def clear_cache():
    """清除所有快取"""
    from app.services.cache_db import cache_clear_all
    cache_clear_all()
    return {"message": "快取已清除"}
