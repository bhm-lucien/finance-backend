"""
產業板塊資金流向分析

X 軸：板塊平均漲跌幅（%）
Y 軸：板塊量能比（今日成交量 / 近期均量）
泡泡大小：板塊成交金額
顏色：漲潮（漲+放量）/輪動（漲+縮量）/觀望（跌+縮量）/退潮（跌+放量）

資料來源：TWSE 全市場收盤行情
"""
import time
import requests
from datetime import datetime
from app.services.industry import fetch_industry_classification


_sector_flow_cache: dict[str, dict] = {}
CACHE_TTL = 60  # 1 分鐘快取（盤中即時資料需要夠新鮮）


def fetch_sector_flow(days: int = 5) -> dict:
    """
    計算各產業板塊的資金流向

    Returns:
        {
            "sectors": [...],
            "summary": {"rising": N, "rotating": N, "watching": N, "falling": N},
            "update_time": "...",
        }
    """
    cache_key = f"sector_flow_{days}"
    if cache_key in _sector_flow_cache:
        entry = _sector_flow_cache[cache_key]
        if time.time() - entry["time"] < CACHE_TTL:
            return entry["data"]

    # 取得產業分類
    industry_data = fetch_industry_classification()
    categories = industry_data.get("categories", [])

    if not categories:
        return {"sectors": [], "summary": {}, "update_time": ""}

    # 取得今日全市場行情
    market_data = _fetch_today_market_full()

    if not market_data:
        return {"sectors": [], "summary": {}, "update_time": ""}

    # 計算各板塊指標
    sectors = []
    for cat in categories:
        sector_name = cat["name"]
        stocks = cat["stocks"]

        change_pcts = []
        volumes = []
        turnover_total = 0.0
        top_stocks = []

        for s in stocks:
            stock_id = s["id"]
            if stock_id not in market_data:
                continue

            md = market_data[stock_id]
            pct = md.get("change_pct", 0)
            vol = md.get("volume", 0)
            turnover = md.get("turnover", 0)

            change_pcts.append(pct)
            volumes.append(vol)
            turnover_total += turnover
            top_stocks.append({
                "id": stock_id,
                "name": s["name"],
                "change_pct": pct,
            })

        if not change_pcts:
            continue

        avg_change_pct = round(sum(change_pcts) / len(change_pcts), 2)
        # 量能比：用板塊成交量佔比作為相對指標
        # 這裡簡化為用板塊內股票數量加權的概念
        avg_volume = sum(volumes) / len(volumes) if volumes else 0

        # 量能比（簡化：用成交金額的 log 作為大小依據）
        vol_ratio = round(turnover_total / 1e8, 1)  # 億元

        top_stocks.sort(key=lambda x: x["change_pct"], reverse=True)

        # 判斷狀態
        status = _determine_status(avg_change_pct, vol_ratio)

        sectors.append({
            "name": sector_name,
            "flow_amount": vol_ratio,          # 成交金額（億）
            "flow_speed": avg_volume / 1000,   # 平均成交量（張）
            "change_pct": avg_change_pct,
            "status": status,
            "stock_count": len(change_pcts),
            "top_stocks": top_stocks[:3],
        })

    # 按漲跌幅排序
    sectors.sort(key=lambda x: x["change_pct"], reverse=True)

    # 統計各狀態數量
    summary = {
        "rising": sum(1 for s in sectors if s["status"] == "漲潮"),
        "rotating": sum(1 for s in sectors if s["status"] == "輪動"),
        "watching": sum(1 for s in sectors if s["status"] == "觀望"),
        "falling": sum(1 for s in sectors if s["status"] == "退潮"),
    }

    result = {
        "sectors": sectors,
        "summary": summary,
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    _sector_flow_cache[cache_key] = {"data": result, "time": time.time()}
    return result


def _determine_status(change_pct: float, turnover_billion: float) -> str:
    """
    判斷板塊狀態（用漲跌幅 + 成交金額）

    - 漲潮：漲 + 成交活絡（金額 > 中位數）
    - 輪動：漲 + 成交清淡
    - 觀望：跌 + 成交清淡
    - 退潮：跌 + 成交活絡
    """
    # 簡化判斷：用漲跌幅方向 + 成交金額高低
    is_up = change_pct > 0.1
    is_active = turnover_billion > 5  # 成交金額 > 5 億視為活絡

    if is_up and is_active:
        return "漲潮"
    elif is_up and not is_active:
        return "輪動"
    elif not is_up and not is_active:
        return "觀望"
    else:
        return "退潮"


def _fetch_today_market_full() -> dict[str, dict]:
    """
    取得今日全市場即時行情（漲跌幅 + 成交量 + 成交金額）
    盤中時間使用證交所即時報價，非盤中使用 STOCK_DAY_ALL

    Returns:
        {stock_id: {"change_pct": float, "volume": int, "turnover": float}}
    """
    result = {}

    try:
        # 判斷是否為盤中時間
        from datetime import datetime, timezone, timedelta
        tw_tz = timezone(timedelta(hours=8))
        now = datetime.now(tw_tz)
        is_market_hours = (9 <= now.hour < 14) and now.weekday() < 5

        if is_market_hours:
            # 盤中：使用 mis.twse 即時報價（分批，每次最多 20 檔）
            try:
                import time as t
                stock_ids = _get_main_stock_ids()

                # 分批查詢（每次 20 檔）
                batch_size = 20
                for batch_start in range(0, len(stock_ids), batch_size):
                    batch = stock_ids[batch_start:batch_start + batch_size]
                    stock_codes = "|".join([f"tse_{sid}.tw" for sid in batch])
                    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={stock_codes}&json=1&delay=0&_={int(t.time()*1000)}"
                    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://mis.twse.com.tw/"}

                    try:
                        response = requests.get(url, headers=headers, timeout=10)
                        data = response.json()

                        for item in data.get("msgArray", []):
                            stock_id = item.get("c", "").strip()
                            if not stock_id or len(stock_id) != 4:
                                continue

                            try:
                                price_str = item.get("z", "").replace("-", "")
                                yesterday_str = item.get("y", "").replace("-", "")
                                vol_str = item.get("v", "0").replace("-", "0").replace(",", "")

                                if not price_str or not yesterday_str:
                                    continue

                                price = float(price_str)
                                yesterday = float(yesterday_str)
                                volume = int(vol_str)

                                if price > 0 and yesterday > 0:
                                    change_pct = round((price - yesterday) / yesterday * 100, 2)
                                    result[stock_id] = {
                                        "change_pct": change_pct,
                                        "volume": volume,
                                        "turnover": 0,
                                        "close": price,
                                    }
                            except (ValueError, TypeError):
                                continue
                    except Exception:
                        continue

                    time.sleep(0.3)  # 批次間隔

                if result:
                    return result
            except Exception as e:
                print(f"[板塊資金] 即時報價失敗，改用 STOCK_DAY_ALL: {e}")

        # 非盤中或即時失敗：使用 STOCK_DAY_ALL
        url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()

        for item in data:
            stock_id = item.get("Code", "").strip()
            if not stock_id or not stock_id.isdigit() or len(stock_id) != 4:
                continue

            close = _safe_float(item.get("ClosingPrice", "0"))
            change = _safe_float(item.get("Change", "0"))
            volume = _safe_float(item.get("TradeVolume", "0"))
            turnover = _safe_float(item.get("TradeValue", "0"))

            prev_close = close - change if close > 0 else 0
            change_pct = round(change / prev_close * 100, 2) if prev_close > 0 else 0

            result[stock_id] = {
                "change_pct": change_pct,
                "volume": int(volume),
                "turnover": turnover,
                "close": close,
            }

    except Exception as e:
        print(f"[板塊資金] 取得今日行情失敗: {e}")

    return result


def _get_main_stock_ids() -> list[str]:
    """取得主要股票代碼列表（用於批量即時報價）"""
    try:
        from app.services.stock_list import fetch_all_stocks
        all_stocks = fetch_all_stocks()
        return [sid for sid in all_stocks.keys() if len(sid) == 4 and sid.isdigit()][:100]
    except Exception:
        # Fallback 熱門股
        return ["2330", "2317", "2454", "2308", "2303", "2412", "2881", "2882", "2886", "2891"]


def _safe_float(val) -> float:
    """安全轉換浮點數"""
    try:
        if isinstance(val, str):
            val = val.replace(",", "")
        return float(val) if val else 0.0
    except (ValueError, TypeError):
        return 0.0
