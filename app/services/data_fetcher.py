"""
資料抓取服務 — 從 FinMind 和證交所取得股票資料
加入記憶體快取 + 本地檔案備份，避免 API 限流問題
"""
import os
import json
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from app.config import FINMIND_API_URL, FINMIND_TOKEN


# ── 快取機制（二層：記憶體 + SQLite 持久化）──────────────

_cache: dict[str, dict] = {}
CACHE_TTL = 3600  # 快取有效期 1 小時（秒）
BACKUP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data_backup")

# 確保備份資料夾存在
os.makedirs(BACKUP_DIR, exist_ok=True)


def _get_cache(key: str):
    """
    從快取取得資料（二層）
    1. 先查記憶體快取（最快）
    2. 記憶體沒有再查 SQLite（持久化）
    """
    # 第一層：記憶體
    if key in _cache:
        entry = _cache[key]
        if time.time() - entry["time"] < CACHE_TTL:
            return entry["data"]
        else:
            del _cache[key]

    # 第二層：SQLite
    try:
        from app.services.cache_db import cache_get
        data = cache_get(f"df_{key}")
        if data is not None:
            df = pd.DataFrame(data)
            # 確保 date 欄位是 datetime 型別
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
            # 回填記憶體快取
            _cache[key] = {"data": df, "time": time.time()}
            return df
    except Exception:
        pass

    return None


def _set_cache(key: str, data):
    """存入快取（二層）"""
    _cache[key] = {"data": data, "time": time.time()}
    # 也存到 SQLite（DataFrame 轉為 list of dict）
    try:
        from app.services.cache_db import cache_set
        if isinstance(data, pd.DataFrame):
            cache_set(f"df_{key}", data.to_dict(orient="records"), ttl=CACHE_TTL)
    except Exception:
        pass


def _save_backup(key: str, raw_data: list):
    """將原始 API 資料存成本地 JSON 備份"""
    try:
        filepath = os.path.join(BACKUP_DIR, f"{key}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump({"data": raw_data, "saved_at": datetime.now().isoformat()}, f)
    except Exception:
        pass


def _load_backup(key: str) -> list | None:
    """從本地 JSON 備份讀取資料"""
    try:
        filepath = os.path.join(BACKUP_DIR, f"{key}.json")
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                backup = json.load(f)
            return backup.get("data")
    except Exception:
        pass
    return None


# ── API 請求（帶重試）──────────────────────────────────

def _finmind_request(params: dict, max_retries: int = 2) -> dict:
    """
    向 FinMind 發送請求，帶簡單重試機制
    """
    if FINMIND_TOKEN:
        params["token"] = FINMIND_TOKEN

    for attempt in range(max_retries + 1):
        try:
            response = requests.get(FINMIND_API_URL, params=params, timeout=10)
            data = response.json()

            # 如果觸發限流，等一下重試
            if data.get("status") != 200:
                msg = data.get("msg", "")
                if "upper limit" in msg.lower() and attempt < max_retries:
                    time.sleep(3 * (attempt + 1))
                    continue
                return data

            return data
        except requests.exceptions.Timeout:
            if attempt < max_retries:
                time.sleep(2)
                continue
            return {"status": 408, "msg": "請求逾時", "data": []}
        except Exception as e:
            return {"status": 500, "msg": str(e), "data": []}

    return {"status": 429, "msg": "請求次數超過上限", "data": []}


# ── 資料抓取函式 ──────────────────────────────────────

def fetch_stock_price(stock_id: str, days: int = 120) -> pd.DataFrame:
    """
    從 FinMind 取得歷史股價資料（有快取 + 本地備份）
    若 FinMind 失敗，使用本地備份。TWSE fallback 改為後台預取，不阻塞 API。
    """
    cache_key = f"price_{stock_id}_{days}"
    cached = _get_cache(cache_key)
    if cached is not None:
        return cached

    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": stock_id,
        "start_date": start_date,
    }

    data = _finmind_request(params)
    raw_data = data.get("data", [])

    if data.get("status") != 200 or not raw_data:
        # 使用本地備份（不阻塞等待 TWSE）
        backup = _load_backup(cache_key)
        if backup:
            raw_data = backup
        else:
            # 觸發後台 TWSE 預取（非阻塞）
            _schedule_twse_prefetch(stock_id, days)
            raise ValueError(f"股票 {stock_id} 資料暫時無法取得（FinMind 限流中，背景預取已排程）")
    else:
        _save_backup(cache_key, raw_data)

    df = pd.DataFrame(raw_data)

    # 欄位標準化
    df = df.rename(columns={
        "date": "date",
        "stock_id": "stock_id",
        "Trading_Volume": "volume",
        "Trading_money": "amount",
        "open": "open",
        "max": "high",
        "min": "low",
        "close": "close",
        "spread": "change",
        "Trading_turnover": "turnover",
    })

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    _set_cache(cache_key, df)
    return df


def fetch_institutional_investors(stock_id: str, days: int = 30) -> pd.DataFrame:
    """
    從 FinMind 取得三大法人買賣超資料（有快取 + 本地備份）
    若 FinMind 失敗，fallback 到 TWSE 開放資料
    """
    cache_key = f"inst_{stock_id}_{days}"
    cached = _get_cache(cache_key)
    if cached is not None:
        return cached

    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    params = {
        "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
        "data_id": stock_id,
        "start_date": start_date,
    }

    data = _finmind_request(params)
    raw_data = data.get("data", [])

    if data.get("status") != 200 or not raw_data:
        backup = _load_backup(cache_key)
        if backup:
            raw_data = backup
        else:
            result = pd.DataFrame()
            _set_cache(cache_key, result)
            return result
    else:
        _save_backup(cache_key, raw_data)

    df = pd.DataFrame(raw_data)
    df["date"] = pd.to_datetime(df["date"])

    _set_cache(cache_key, df)
    return df


def fetch_margin_trading(stock_id: str, days: int = 30) -> pd.DataFrame:
    """
    從 FinMind 取得融資融券資料（有快取 + 本地備份）
    """
    cache_key = f"margin_{stock_id}_{days}"
    cached = _get_cache(cache_key)
    if cached is not None:
        return cached

    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    params = {
        "dataset": "TaiwanStockMarginPurchaseShortSale",
        "data_id": stock_id,
        "start_date": start_date,
    }

    data = _finmind_request(params)
    raw_data = data.get("data", [])

    if data.get("status") != 200 or not raw_data:
        backup = _load_backup(cache_key)
        if backup:
            raw_data = backup
        else:
            result = pd.DataFrame()
            _set_cache(cache_key, result)
            return result
    else:
        _save_backup(cache_key, raw_data)

    df = pd.DataFrame(raw_data)
    df["date"] = pd.to_datetime(df["date"])

    _set_cache(cache_key, df)
    return df


# ── 後台 TWSE 預取排程 ─────────────────────────────

import threading

_twse_prefetch_queue: set = set()  # 待預取的股票


def _schedule_twse_prefetch(stock_id: str, days: int):
    """排程後台預取（非阻塞），避免重複排程"""
    key = f"{stock_id}_{days}"
    if key in _twse_prefetch_queue:
        return
    _twse_prefetch_queue.add(key)

    def _do_prefetch():
        try:
            data = _fetch_from_twse(stock_id, days)
            if data:
                print(f"[TWSE 預取] {stock_id} 完成（{len(data)} 筆）")
        except Exception as e:
            print(f"[TWSE 預取] {stock_id} 失敗: {e}")
        finally:
            _twse_prefetch_queue.discard(key)

    thread = threading.Thread(target=_do_prefetch, daemon=True)
    thread.start()


# ── TWSE 開放資料 Fallback（後台預取用）─────────────────
_twse_lock = threading.Lock()  # 並發鎖，同時只允許一個 TWSE 請求


def _fetch_from_twse(stock_id: str, days: int = 120) -> list | None:
    """
    從 TWSE 開放資料取得歷史股價（作為 FinMind 的 fallback）
    TWSE API 一次回傳一個月的資料，需要逐月取得
    加入並發鎖避免多個請求同時呼叫 TWSE 造成容器卡死

    Returns:
        list of dict（與 FinMind 格式相容）或 None
    """
    # 並發限制：如果已有其他請求在用 TWSE，直接放棄
    if not _twse_lock.acquire(blocking=False):
        print(f"[TWSE fallback] {stock_id} 跳過（已有其他請求進行中）")
        return None
    import requests as req
    from datetime import datetime, timedelta

    all_data = []
    now = datetime.now()
    months_needed = min(3, max(1, days // 30 + 1))  # 最多取 3 個月，避免太慢

    try:
        for i in range(months_needed):
            target_date = now - timedelta(days=30 * i)
            date_str = target_date.strftime("%Y%m%d")

            try:
                url = f"https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={date_str}&stockNo={stock_id}"
                headers = {"User-Agent": "Mozilla/5.0"}
                resp = req.get(url, headers=headers, timeout=10)

                if resp.status_code != 200:
                    continue

                result = resp.json()
                if result.get("stat") != "OK" or not result.get("data"):
                    continue

                # 解析 TWSE 資料格式
                for row in result["data"]:
                    try:
                        date_parts = row[0].strip().split("/")
                        year = int(date_parts[0]) + 1911
                        month = int(date_parts[1])
                        day = int(date_parts[2])
                        date_val = f"{year}-{month:02d}-{day:02d}"

                        volume = int(row[1].replace(",", ""))
                        amount = int(row[2].replace(",", "")) if row[2].replace(",", "").isdigit() else 0
                        open_price = float(row[3].replace(",", "")) if row[3].replace(",", "").replace(".", "").isdigit() else 0
                        high_price = float(row[4].replace(",", "")) if row[4].replace(",", "").replace(".", "").isdigit() else 0
                        low_price = float(row[5].replace(",", "")) if row[5].replace(",", "").replace(".", "").isdigit() else 0
                        close_price = float(row[6].replace(",", "")) if row[6].replace(",", "").replace(".", "").isdigit() else 0

                        spread_str = row[7].replace(",", "").replace("+", "").replace("X", "0").replace(" ", "")
                        try:
                            spread = float(spread_str) if spread_str else 0
                        except (ValueError, TypeError):
                            spread = 0

                        if close_price > 0:
                            all_data.append({
                                "date": date_val,
                                "stock_id": stock_id,
                                "Trading_Volume": volume,
                                "Trading_money": amount,
                                "open": open_price,
                                "max": high_price,
                                "min": low_price,
                                "close": close_price,
                                "spread": spread,
                                "Trading_turnover": 0,
                            })
                    except (ValueError, IndexError):
                        continue

                time.sleep(1.5)

            except Exception as e:
                print(f"[TWSE fallback] 取得 {stock_id} {date_str} 失敗: {e}")
                continue

        if not all_data:
            return None

        # 去重複並排序
        seen_dates = set()
        unique_data = []
        for item in all_data:
            if item["date"] not in seen_dates:
                seen_dates.add(item["date"])
                unique_data.append(item)

        unique_data.sort(key=lambda x: x["date"])

        # 存入備份
        if unique_data:
            cache_key = f"price_{stock_id}_{days}"
            _save_backup(cache_key, unique_data)

        return unique_data

    except Exception as e:
        print(f"[TWSE fallback] {stock_id} 異常: {e}")
        return None
    finally:
        _twse_lock.release()


def _fetch_institutional_from_twse(stock_id: str, days: int = 30) -> list | None:
    """
    從 TWSE 取得三大法人買賣超（T86 報表）
    """
    if not _twse_lock.acquire(blocking=False):
        return None
    import requests as req

    all_data = []
    now = datetime.now()

    # 取最近幾個交易日的資料（最多取 days 天，但 TWSE 每次只能查一天）
    # 為了效率只取最近 10 個交易日
    fetch_days = min(days, 10)

    for i in range(fetch_days):
        target_date = now - timedelta(days=i)
        # 跳過週末
        if target_date.weekday() >= 5:
            continue

        date_str = target_date.strftime("%Y%m%d")

        try:
            url = f"https://www.twse.com.tw/fund/T86?response=json&date={date_str}&selectType=ALL"
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = req.get(url, headers=headers, timeout=10)

            if resp.status_code != 200:
                continue

            result = resp.json()
            if result.get("stat") != "OK" or not result.get("data"):
                continue

            # 找到目標股票
            for row in result["data"]:
                sid = row[0].strip()
                if sid != stock_id:
                    continue

                try:
                    # T86 欄位：證券代號, 證券名稱, 外陸資買進股數(不含外資自營商), 外陸資賣出股數, ...
                    # 買進/賣出是「股數」
                    foreign_buy = int(row[2].replace(",", ""))
                    foreign_sell = int(row[3].replace(",", ""))
                    trust_buy = int(row[8].replace(",", "")) if len(row) > 8 else 0
                    trust_sell = int(row[9].replace(",", "")) if len(row) > 9 else 0
                    dealer_buy = int(row[12].replace(",", "")) if len(row) > 12 else 0
                    dealer_sell = int(row[13].replace(",", "")) if len(row) > 13 else 0

                    date_val = target_date.strftime("%Y-%m-%d")

                    # 外資
                    all_data.append({
                        "date": date_val,
                        "stock_id": stock_id,
                        "name": "Foreign_Investor",
                        "buy": foreign_buy // 1000,   # 股轉張
                        "sell": foreign_sell // 1000,
                    })
                    # 投信
                    all_data.append({
                        "date": date_val,
                        "stock_id": stock_id,
                        "name": "Investment_Trust",
                        "buy": trust_buy // 1000,
                        "sell": trust_sell // 1000,
                    })
                    # 自營商
                    all_data.append({
                        "date": date_val,
                        "stock_id": stock_id,
                        "name": "Dealer_self",
                        "buy": dealer_buy // 1000,
                        "sell": dealer_sell // 1000,
                    })
                except (ValueError, IndexError):
                    continue
                break  # 找到就跳出

            time.sleep(1.5)  # TWSE 頻率限制

        except Exception as e:
            print(f"[TWSE 法人 fallback] {date_str} 失敗: {e}")
            continue

    if not all_data:
        _twse_lock.release()
        return None

    # 修正 name 欄位以相容既有的篩選邏輯（用「外資」「投信」關鍵字）
    for item in all_data:
        if item["name"] == "Foreign_Investor":
            item["name"] = "外資及陸資(不含外資自營商)"
        elif item["name"] == "Investment_Trust":
            item["name"] = "投信"
        elif item["name"] == "Dealer_self":
            item["name"] = "自營商(自行買賣)"

    # 存備份
    cache_key = f"inst_{stock_id}_{days}"
    _save_backup(cache_key, all_data)

    _twse_lock.release()
    return all_data


def _fetch_margin_from_twse(stock_id: str, days: int = 30) -> list | None:
    """
    從 TWSE 取得融資融券資料
    """
    if not _twse_lock.acquire(blocking=False):
        return None
    import requests as req

    all_data = []
    now = datetime.now()

    # 取最近幾個交易日
    fetch_days = min(days, 10)

    for i in range(fetch_days):
        target_date = now - timedelta(days=i)
        if target_date.weekday() >= 5:
            continue

        date_str = target_date.strftime("%Y%m%d")

        try:
            url = f"https://www.twse.com.tw/exchangeReport/MI_MARGN?response=json&date={date_str}&selectType=ALL"
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = req.get(url, headers=headers, timeout=10)

            if resp.status_code != 200:
                continue

            result = resp.json()
            if result.get("stat") != "OK":
                continue

            # 找 data 區塊（可能是 data 或 creditList）
            rows = result.get("data", []) or result.get("creditList", [])
            if not rows:
                continue

            for row in rows:
                sid = row[0].strip() if row else ""
                if sid != stock_id:
                    continue

                try:
                    # MI_MARGN 欄位：
                    # 股票代號, 股票名稱, 融資買進, 融資賣出, 融資現金償還, 融資前日餘額, 融資今日餘額,
                    # 融券買進, 融券賣出, 融券現券償還, 融券前日餘額, 融券今日餘額, ...
                    date_val = target_date.strftime("%Y-%m-%d")

                    margin_balance = int(row[6].replace(",", "")) if len(row) > 6 else 0
                    short_balance = int(row[12].replace(",", "")) if len(row) > 12 else 0

                    all_data.append({
                        "date": date_val,
                        "stock_id": stock_id,
                        "MarginPurchaseTodayBalance": margin_balance,
                        "ShortSaleTodayBalance": short_balance,
                    })
                except (ValueError, IndexError):
                    continue
                break

            time.sleep(1.5)

        except Exception as e:
            print(f"[TWSE 融資券 fallback] {date_str} 失敗: {e}")
            continue

    if not all_data:
        _twse_lock.release()
        return None

    # 存備份
    cache_key = f"margin_{stock_id}_{days}"
    _save_backup(cache_key, all_data)

    _twse_lock.release()
    return all_data
