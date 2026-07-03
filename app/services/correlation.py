"""
相關性分析服務

計算自選股之間的漲跌相關性矩陣
"""
import time
import numpy as np
import pandas as pd
from app.services.data_fetcher import fetch_stock_price
from app.services.stock_list import fetch_all_stocks


_corr_cache: dict[str, dict] = {}
CACHE_TTL = 600  # 10 分鐘快取


def calculate_correlation_matrix(stock_ids: list[str], days: int = 60) -> dict:
    """
    計算多檔股票之間的漲跌相關性矩陣

    Args:
        stock_ids: 股票代碼列表
        days: 計算天數

    Returns:
        {
            "stocks": ["2330", "2317", ...],
            "names": ["台積電", "鴻海", ...],
            "matrix": [[1.0, 0.65, ...], [0.65, 1.0, ...], ...],
            "high_corr_pairs": [{"stock_a": "2330", "stock_b": "2317", "corr": 0.85}, ...],
            "low_corr_pairs": [...],
        }
    """
    if len(stock_ids) < 2:
        return {"stocks": stock_ids, "names": [], "matrix": [], "high_corr_pairs": [], "low_corr_pairs": []}

    cache_key = f"corr_{'_'.join(sorted(stock_ids))}_{days}"
    if cache_key in _corr_cache:
        entry = _corr_cache[cache_key]
        if time.time() - entry["time"] < CACHE_TTL:
            return entry["data"]

    all_stocks = fetch_all_stocks()

    # 取得各股收盤價
    price_data = {}
    valid_ids = []
    names = []

    for sid in stock_ids:
        try:
            df = fetch_stock_price(sid, days=days)
            if len(df) >= 20:
                # 計算日報酬率
                returns = df["close"].pct_change().dropna()
                price_data[sid] = returns.values
                valid_ids.append(sid)
                names.append(all_stocks.get(sid, sid))
        except Exception:
            continue

    if len(valid_ids) < 2:
        return {"stocks": valid_ids, "names": names, "matrix": [], "high_corr_pairs": [], "low_corr_pairs": []}

    # 對齊長度（取最短的）
    min_len = min(len(v) for v in price_data.values())
    aligned_data = {sid: vals[-min_len:] for sid, vals in price_data.items()}

    # 建立 DataFrame 計算相關性
    df_returns = pd.DataFrame(aligned_data)
    corr_matrix = df_returns.corr()

    # 轉為 list
    matrix = corr_matrix.values.tolist()
    # 四捨五入
    matrix = [[round(v, 3) for v in row] for row in matrix]

    # 找出高/低相關性配對
    high_corr_pairs = []
    low_corr_pairs = []

    for i in range(len(valid_ids)):
        for j in range(i + 1, len(valid_ids)):
            corr_val = round(float(corr_matrix.iloc[i, j]), 3)
            pair = {
                "stock_a": valid_ids[i],
                "name_a": names[i],
                "stock_b": valid_ids[j],
                "name_b": names[j],
                "corr": corr_val,
            }
            if corr_val >= 0.7:
                high_corr_pairs.append(pair)
            elif corr_val <= 0.2:
                low_corr_pairs.append(pair)

    high_corr_pairs.sort(key=lambda x: x["corr"], reverse=True)
    low_corr_pairs.sort(key=lambda x: x["corr"])

    result = {
        "stocks": valid_ids,
        "names": names,
        "matrix": matrix,
        "high_corr_pairs": high_corr_pairs,
        "low_corr_pairs": low_corr_pairs,
        "days": days,
        "update_time": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
    }

    _corr_cache[cache_key] = {"data": result, "time": time.time()}
    return result
