"""
股票分析 API 路由
"""
import asyncio
import numpy as np
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


@router.get("/report/{stock_id}")
async def get_stock_report(stock_id: str):
    """AI 個股研究報告（基本面分析、DCF 估值、三情境預測）"""
    from app.services.stock_report import generate_stock_report
    try:
        result = await asyncio.to_thread(generate_stock_report, stock_id)
        if result.get("error"):
            raise HTTPException(status_code=500, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/podcasts")
async def get_podcasts(podcast_id: str = "all", limit: int = 20):
    """取得財經 Podcast 最新集數列表"""
    from app.services.podcast import fetch_podcast_episodes
    try:
        result = fetch_podcast_episodes(podcast_id, limit)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cache/clear")
async def clear_cache():
    """清除所有快取"""
    from app.services.cache_db import cache_clear_all
    cache_clear_all()
    return {"message": "快取已清除"}


# ══════════════════════════════════════════════════════
# 新增 API：籌碼連續性、相關性、持倉健檢、熱力圖、批量報價
# ══════════════════════════════════════════════════════

@router.get("/chip-continuity/{stock_id}")
async def get_chip_continuity(stock_id: str, days: int = Query(default=30, ge=7, le=90)):
    """取得單一個股的籌碼連續性分析"""
    from app.services.chip_continuity import analyze_chip_continuity
    try:
        result = analyze_chip_continuity(stock_id, days=days)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chip-continuity-ranking")
async def get_chip_continuity_ranking(
    top_n: int = Query(default=20, ge=5, le=50),
    days: int = Query(default=30, ge=7, le=90),
):
    """取得外資/投信連買排行榜"""
    from app.services.chip_continuity import get_continuous_buy_ranking
    try:
        result = await asyncio.to_thread(get_continuous_buy_ranking, top_n, days)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/correlation")
async def get_correlation_matrix(body: dict):
    """
    計算自選股漲跌相關性矩陣

    Body: {"stock_ids": ["2330", "2317", "2454"], "days": 60}
    """
    from app.services.correlation import calculate_correlation_matrix

    stock_ids = body.get("stock_ids", [])
    days = body.get("days", 60)

    if len(stock_ids) < 2:
        raise HTTPException(status_code=400, detail="至少需要 2 檔股票")
    if len(stock_ids) > 20:
        raise HTTPException(status_code=400, detail="最多支援 20 檔股票")

    try:
        result = await asyncio.to_thread(calculate_correlation_matrix, stock_ids, days)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/portfolio-health")
async def get_portfolio_health(body: dict):
    """
    AI 持倉健檢

    Body: {"holdings": [{"stock_id": "2330", "shares": 1000, "cost": 580.0}, ...]}
    """
    from app.services.portfolio_health import analyze_portfolio_health

    holdings = body.get("holdings", [])
    if not holdings:
        raise HTTPException(status_code=400, detail="持倉資料為空")

    try:
        result = await asyncio.to_thread(analyze_portfolio_health, holdings)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/heatmap")
async def get_market_heatmap():
    """
    取得即時行情熱力圖資料（Finviz Map 風格）
    按產業分群，顏色 = 漲跌幅（限制 15 檔避免過慢）
    """
    from app.services.sector_flow import fetch_sector_flow

    try:
        flow = fetch_sector_flow()
        sectors = flow.get("sectors", [])

        heatmap_data = []
        total_stocks = 0

        for sector in sectors:
            if total_stocks >= 15:
                break

            sector_stocks = []
            for stock in sector.get("top_stocks", [])[:3]:
                if total_stocks >= 15:
                    break
                sector_stocks.append({
                    "stock_id": stock["id"],
                    "name": stock["name"],
                    "change_pct": stock.get("change_pct", 0),
                    "price": 0,
                    "volume": 0,
                })
                total_stocks += 1

            if sector_stocks:
                heatmap_data.append({
                    "sector": sector["name"],
                    "change_pct": sector["change_pct"],
                    "stocks": sector_stocks,
                    "flow_amount": sector.get("flow_amount", 0),
                })

        return {
            "sectors": heatmap_data,
            "update_time": flow.get("update_time", ""),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch-realtime")
async def get_batch_realtime(body: dict):
    """
    批量取得即時報價（自選股監控用）

    Body: {"stock_ids": ["2330", "2317", "2454"]}
    """
    from app.services.realtime import fetch_realtime_price

    stock_ids = body.get("stock_ids", [])
    if not stock_ids:
        raise HTTPException(status_code=400, detail="股票清單為空")

    results = []
    for sid in stock_ids[:30]:  # 最多 30 檔
        try:
            rt = fetch_realtime_price(sid)
            results.append({"stock_id": sid, **rt})
        except Exception:
            results.append({"stock_id": sid, "price": 0, "change_pct": 0})

    return {"quotes": results, "count": len(results)}


@router.get("/pe-river/{stock_id}")
async def get_pe_river(stock_id: str, years: int = Query(default=5, ge=1, le=10)):
    """
    取得本益比河流圖資料

    計算歷史本益比帶狀區間（偏低/合理/偏高/過高）
    """
    try:
        # 取得歷史資料（先嘗試長期，失敗就取短期）
        df = None
        for attempt_days in [min(years * 365, 1200), 365, 120]:
            try:
                df = fetch_stock_price(stock_id, days=attempt_days)
                if len(df) >= 60:
                    break
            except Exception:
                continue

        if df is None or len(df) < 60:
            raise HTTPException(status_code=404, detail="歷史資料不足，請稍後再試")

        # 用歷史 EPS 估算（簡化版：用收盤價/PE 比值反推）
        # 實際上需要 EPS 資料，這裡用統計法估算本益比區間
        closes = df["close"].values
        dates = df["date"].dt.strftime("%Y-%m-%d").tolist()

        # 滾動計算統計本益比區間
        window = min(252, len(closes) // 2)  # 約一年或一半資料
        pe_data = []

        for i in range(window, len(closes)):
            historical = closes[i - window:i]
            current = closes[i]

            # 用統計分位數模擬本益比河流帶
            p20 = float(np.percentile(historical, 20))
            p40 = float(np.percentile(historical, 40))
            p60 = float(np.percentile(historical, 60))
            p80 = float(np.percentile(historical, 80))

            pe_data.append({
                "date": dates[i],
                "close": round(float(current), 2),
                "cheap": round(p20, 2),       # 偏低
                "fair_low": round(p40, 2),    # 合理低
                "fair_high": round(p60, 2),   # 合理高
                "expensive": round(p80, 2),   # 偏高
            })

        # 判斷目前位置
        current_price = closes[-1]
        all_prices = closes[-window:]
        percentile = float(np.searchsorted(np.sort(all_prices), current_price) / len(all_prices) * 100)

        if percentile <= 20:
            zone = "偏低"
        elif percentile <= 50:
            zone = "合理"
        elif percentile <= 80:
            zone = "偏高"
        else:
            zone = "過高"

        return {
            "stock_id": stock_id,
            "data": pe_data[-252:],  # 最近一年
            "current_zone": zone,
            "current_percentile": round(percentile, 1),
            "years": years,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
