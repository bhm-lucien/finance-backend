"""
台股完整股票清單服務
從 FinMind 取得所有上市上櫃股票代碼與名稱
"""
import time
import requests
from app.config import FINMIND_API_URL, FINMIND_TOKEN

_stock_list_cache: dict | None = None
_cache_time: float = 0
CACHE_TTL = 86400  # 24 小時快取


def fetch_all_stocks() -> dict:
    """
    取得全部台股上市上櫃股票代碼和名稱

    Returns:
        dict: {stock_id: stock_name} 例如 {"2330": "台積電", ...}
    """
    global _stock_list_cache, _cache_time

    if _stock_list_cache and (time.time() - _cache_time < CACHE_TTL):
        return _stock_list_cache

    all_stocks = {}

    # 從 FinMind 取得上市股票清單
    try:
        params = {"dataset": "TaiwanStockInfo"}
        if FINMIND_TOKEN:
            params["token"] = FINMIND_TOKEN

        response = requests.get(FINMIND_API_URL, params=params, timeout=15)
        data = response.json()

        if data.get("status") == 200 and data.get("data"):
            for item in data["data"]:
                stock_id = item.get("stock_id", "")
                stock_name = item.get("stock_name", "")
                if stock_id and stock_name:
                    all_stocks[stock_id] = stock_name
    except Exception as e:
        print(f"[股票清單] 取得失敗: {e}")

    if all_stocks:
        _stock_list_cache = all_stocks
        _cache_time = time.time()

    return all_stocks
