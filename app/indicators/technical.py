"""
技術指標計算模組
計算 RSI、MACD、KD、布林通道等常用指標
"""
import pandas as pd
import numpy as np


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """計算 RSI 相對強弱指標"""
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.ewm(span=period, min_periods=period).mean()
    avg_loss = loss.ewm(span=period, min_periods=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9
) -> dict:
    """
    計算 MACD 指標

    Returns:
        dict 包含 macd, signal, histogram
    """
    ema_fast = df["close"].ewm(span=fast, min_periods=fast).mean()
    ema_slow = df["close"].ewm(span=slow, min_periods=slow).mean()

    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, min_periods=signal).mean()
    histogram = macd_line - signal_line

    return {
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
    }


def calculate_kd(df: pd.DataFrame, period: int = 9) -> dict:
    """
    計算 KD 隨機指標

    Returns:
        dict 包含 k, d
    """
    low_min = df["low"].rolling(window=period).min()
    high_max = df["high"].rolling(window=period).max()

    rsv = (df["close"] - low_min) / (high_max - low_min) * 100

    # K 值：RSV 的 3 日 EMA
    k = rsv.ewm(span=3, min_periods=1).mean()
    # D 值：K 的 3 日 EMA
    d = k.ewm(span=3, min_periods=1).mean()

    return {"k": k, "d": d}


def calculate_bollinger_bands(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0
) -> dict:
    """
    計算布林通道

    Returns:
        dict 包含 upper, middle, lower
    """
    middle = df["close"].rolling(window=period).mean()
    std = df["close"].rolling(window=period).std()

    upper = middle + std_dev * std
    lower = middle - std_dev * std

    return {"upper": upper, "middle": middle, "lower": lower}


def calculate_moving_averages(df: pd.DataFrame) -> dict:
    """
    計算常用均線 (5, 10, 20, 60, 120)

    Returns:
        dict 包含各期均線
    """
    periods = [5, 10, 20, 60, 120]
    result = {}
    for p in periods:
        result[f"ma{p}"] = df["close"].rolling(window=p).mean()
    return result


def calculate_volume_profile(df: pd.DataFrame, bins: int = 30) -> list:
    """
    計算成交量分布 (Volume Profile) — 精度加強版
    加入套牢區/獲利區標示

    Args:
        df: 含 OHLCV 的 DataFrame
        bins: 分割數量（越多越精細）

    Returns:
        list of dict，每個包含 price_low, price_high, volume, zone_type
    """
    if df.empty:
        return []

    price_min = float(df["low"].min())
    price_max = float(df["high"].max())

    # 避免除以零
    if price_max <= price_min:
        return []

    bin_size = (price_max - price_min) / bins
    current_price = float(df["close"].iloc[-1])

    profiles = []
    total_vol = 0

    for i in range(bins):
        low = price_min + i * bin_size
        high = low + bin_size

        # 計算在此價格區間有交易的成交量（加權：越接近中心權重越高）
        mask = (df["low"] <= high) & (df["high"] >= low)
        matched_rows = df.loc[mask]
        vol = int(matched_rows["volume"].sum())
        total_vol += vol

        # 判斷區域類型
        mid_price = (low + high) / 2
        if mid_price > current_price * 1.01:
            zone_type = "trapped"  # 套牢區（成本高於現價）
        elif mid_price < current_price * 0.99:
            zone_type = "profit"   # 獲利區（成本低於現價）
        else:
            zone_type = "current"  # 目前價位區

        profiles.append({
            "price_low": round(float(low), 2),
            "price_high": round(float(high), 2),
            "volume": vol,
            "zone_type": zone_type,
        })

    # 計算每個區間的成交量佔比
    for p in profiles:
        p["volume_pct"] = round(p["volume"] / total_vol * 100, 1) if total_vol > 0 else 0

    # 找出 POC（最大成交量集中區）
    if profiles:
        poc = max(profiles, key=lambda x: x["volume"])
        poc["is_poc"] = True

    # 計算套牢/獲利比例
    trapped_vol = sum(p["volume"] for p in profiles if p["zone_type"] == "trapped")
    profit_vol = sum(p["volume"] for p in profiles if p["zone_type"] == "profit")
    trapped_pct = round(trapped_vol / total_vol * 100, 1) if total_vol > 0 else 0
    profit_pct = round(profit_vol / total_vol * 100, 1) if total_vol > 0 else 0

    # 在第一筆加入統計摘要（前端可取用）
    if profiles:
        profiles[0]["_summary"] = {
            "trapped_pct": trapped_pct,
            "profit_pct": profit_pct,
            "poc_price": round((poc["price_low"] + poc["price_high"]) / 2, 2) if poc else 0,
            "current_price": round(current_price, 2),
        }

    return profiles


def calculate_all_indicators(df: pd.DataFrame) -> dict:
    """
    計算所有技術指標，回傳整合結果

    Returns:
        dict 包含所有指標資料
    """
    rsi = calculate_rsi(df)
    macd = calculate_macd(df)
    kd = calculate_kd(df)
    bollinger = calculate_bollinger_bands(df)
    ma = calculate_moving_averages(df)

    # 組裝到 DataFrame
    indicators_df = df[["date", "open", "high", "low", "close", "volume"]].copy()
    indicators_df["rsi"] = rsi
    indicators_df["macd"] = macd["macd"]
    indicators_df["macd_signal"] = macd["signal"]
    indicators_df["macd_histogram"] = macd["histogram"]
    indicators_df["k"] = kd["k"]
    indicators_df["d"] = kd["d"]
    indicators_df["bb_upper"] = bollinger["upper"]
    indicators_df["bb_middle"] = bollinger["middle"]
    indicators_df["bb_lower"] = bollinger["lower"]

    for key, series in ma.items():
        indicators_df[key] = series

    # 多空判斷
    latest = indicators_df.iloc[-1] if not indicators_df.empty else None
    bull_bear = _assess_bull_bear(latest) if latest is not None else {}

    # 將 NaN 替換為 None（JSON 可序列化）
    indicators_df = indicators_df.where(indicators_df.notna(), None)

    # 轉換為 records 時，確保 float 值可序列化
    records = []
    for _, row in indicators_df.iterrows():
        record = {}
        for col in indicators_df.columns:
            val = row[col]
            if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
                record[col] = None
            elif hasattr(val, 'isoformat'):
                record[col] = val.isoformat()[:10]
            else:
                record[col] = val
        records.append(record)

    return {
        "ohlcv": records,
        "volume_profile": calculate_volume_profile(df),
        "bull_bear": bull_bear,
    }


def _assess_bull_bear(latest: pd.Series) -> dict:
    """根據最新一筆指標判斷多空狀態"""
    rsi_val = latest.get("rsi", 50)
    macd_val = latest.get("macd", 0)
    macd_hist = latest.get("macd_histogram", 0)
    k_val = latest.get("k", 50)
    d_val = latest.get("d", 50)

    # RSI 判斷
    if rsi_val > 70:
        rsi_status = "過熱"
    elif rsi_val > 50:
        rsi_status = "偏多"
    elif rsi_val > 30:
        rsi_status = "偏空"
    else:
        rsi_status = "超賣"

    # MACD 判斷
    macd_status = "多頭" if macd_hist > 0 else "空頭"

    # KD 判斷
    if k_val > 80:
        kd_status = "高檔鈍化"
    elif k_val > 50:
        kd_status = "多方"
    elif k_val > 20:
        kd_status = "空方"
    else:
        kd_status = "低檔"

    # 多方能量百分比
    bull_score = 0
    if rsi_val > 50:
        bull_score += 25
    if macd_hist > 0:
        bull_score += 25
    if k_val > d_val:
        bull_score += 25
    if latest.get("close", 0) > latest.get("ma20", 0):
        bull_score += 25

    return {
        "rsi_value": round(float(rsi_val), 1),
        "rsi_status": rsi_status,
        "macd_status": macd_status,
        "kd_status": kd_status,
        "k_value": round(float(k_val), 1),
        "d_value": round(float(d_val), 1),
        "bull_percentage": bull_score,
        "bear_percentage": 100 - bull_score,
    }
