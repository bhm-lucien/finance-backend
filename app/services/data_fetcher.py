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
    若 FinMind 失敗，自動 fallback 到 TWSE 開放資料
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

    # 如果 FinMind API 失敗，嘗試 TWSE fallback
    if data.get("status") != 200 or not raw_data:
        # 先嘗試本地備份
        backup = _load_backup(cache_key)
        if backup:
            raw_data = backup
        else:
            # Fallback: TWSE 開放資料
            try:
                twse_data = _fetch_from_twse(stock_id, days)
                if twse_data:
                    raw_data = twse_data
                    print(f"[資料] {stock_id} 使用 TWSE fallback（{len(twse_data)} 筆）")
                else:
                    raise ValueError(f"無法取得股票 {stock_id} 的資料：FinMind 限流且 TWSE 無資料")
            except ValueError:
                raise
            except Exception as e:
                raise ValueError(f"無法取得股票 {stock_id} 的資料：{data.get('msg', '未知錯誤')}（TWSE fallback 也失敗：{e}）")
    else:
        # 成功時存備份
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



# ── TWSE 開放資料 Fallback ─────────────────────────────

def _fetch_from_twse(stock_id: str, days: int = 120) -> list | None:
    """
    從 TWSE 開放資料取得歷史股價（作為 FinMind 的 fallback）
    TWSE API 一次回傳一個月的資料，需要逐月取得

    Returns:
        list of dict（與 FinMind 格式相容）或 None
    """
    import requests as req
    from datetime import datetime, timedelta

    all_data = []
    now = datetime.now()
    months_needed = max(1, days // 30 + 1)

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
                    # TWSE 欄位：日期, 成交股數, 成交金額, 開盤價, 最高價, 最低價, 收盤價, 漲跌價差, 成交筆數
                    date_parts = row[0].strip().split("/")
                    # 民國年轉西元年
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

                    # 漲跌價差
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

            # TWSE 有頻率限制，每次請求間隔 3 秒
            time.sleep(3)

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
