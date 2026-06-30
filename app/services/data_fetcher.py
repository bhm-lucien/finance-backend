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


# ── 快取機制 ──────────────────────────────────────────

_cache: dict[str, dict] = {}
CACHE_TTL = 3600  # 快取有效期 1 小時（秒）
BACKUP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data_backup")

# 確保備份資料夾存在
os.makedirs(BACKUP_DIR, exist_ok=True)


def _get_cache(key: str):
    """從快取取得資料，若過期回傳 None"""
    if key in _cache:
        entry = _cache[key]
        if time.time() - entry["time"] < CACHE_TTL:
            return entry["data"]
        else:
            del _cache[key]
    return None


def _set_cache(key: str, data):
    """存入快取"""
    _cache[key] = {"data": data, "time": time.time()}


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
            response = requests.get(FINMIND_API_URL, params=params, timeout=15)
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

    # 如果 API 失敗，嘗試用本地備份
    if data.get("status") != 200 or not raw_data:
        backup = _load_backup(cache_key)
        if backup:
            raw_data = backup
        else:
            raise ValueError(f"無法取得股票 {stock_id} 的資料：{data.get('msg', '未知錯誤')}（無本地備份）")
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

