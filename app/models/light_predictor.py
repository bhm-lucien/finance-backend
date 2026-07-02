"""
輕量價格預測器（不需要 PyTorch）

使用方法：
- 線性回歸趨勢線
- 布林通道作為信賴區間
- 移動平均加權

產出未來 10 天的預測價格 + 上下界
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from app.services.data_fetcher import fetch_stock_price


def predict_price(stock_id: str, days_history: int = 120, days_forecast: int = 10) -> dict:
    """
    輕量預測：線性回歸 + 布林通道

    Returns:
        {
            "current_price": 590.0,
            "history": [{"date": "2026-06-01", "price": 580.0}, ...],
            "predictions": [
                {"day": 1, "price": 592.0, "upper": 600.0, "lower": 584.0},
                ...
            ],
            "trend": "上升" / "下降" / "盤整",
            "confidence": 0.72,
        }
    """
    df = fetch_stock_price(stock_id, days=days_history)
    if len(df) < 30:
        return {"error": "資料不足"}

    close = df["close"].astype(float).values
    dates = df["date"].values
    n = len(close)

    # 取最近 60 天做預測基礎
    lookback = min(60, n)
    recent = close[-lookback:]

    # 線性回歸（趨勢方向）
    X = np.arange(lookback).reshape(-1, 1)
    y = recent
    model = LinearRegression()
    model.fit(X, y)

    # R² 作為信心值
    confidence = round(max(0, model.score(X, y)), 2)

    # 預測未來 N 天
    future_X = np.arange(lookback, lookback + days_forecast).reshape(-1, 1)
    trend_predictions = model.predict(future_X)

    # 布林通道（用近 20 天的標準差作為波動率）
    std_20 = float(np.std(close[-20:]))
    volatility = std_20 * 1.5  # 預測波動放大 1.5 倍

    # 加入均值回歸修正（避免趨勢過度外推）
    ma20 = float(np.mean(close[-20:]))
    ma60 = float(np.mean(close[-lookback:]))
    current_price = float(close[-1])

    predictions = []
    for i in range(days_forecast):
        # 趨勢預測 + 均值回歸（越遠越接近均線）
        trend_price = float(trend_predictions[i])
        reversion_factor = min(0.3, i * 0.03)  # 每天增加 3% 的均值回歸力道
        adjusted_price = trend_price * (1 - reversion_factor) + ma20 * reversion_factor

        # 確保價格合理（不超過 ±10% 波動）
        max_change = current_price * 0.10
        adjusted_price = max(current_price - max_change, min(current_price + max_change, adjusted_price))

        # 信賴區間隨時間擴大
        interval = volatility * (1 + i * 0.15)

        predictions.append({
            "day": i + 1,
            "price": round(adjusted_price, 2),
            "upper": round(adjusted_price + interval, 2),
            "lower": round(adjusted_price - interval, 2),
        })

    # 判斷趨勢方向
    slope = float(model.coef_[0])
    slope_pct = slope / current_price * 100  # 每日漲跌幅

    if slope_pct > 0.1:
        trend = "上升"
    elif slope_pct < -0.1:
        trend = "下降"
    else:
        trend = "盤整"

    # 歷史資料（最近 30 天）
    history = []
    for i in range(-30, 0):
        idx = n + i
        if idx >= 0:
            history.append({
                "date": str(pd.Timestamp(dates[idx]).date()),
                "close": float(close[idx]),
            })

    # 預測資料（加上日期，相容 PredictionChart 格式）
    from datetime import timedelta
    last_date = pd.Timestamp(dates[-1])
    predictions_formatted = []
    for p in predictions:
        pred_date = last_date + timedelta(days=p["day"])
        predictions_formatted.append({
            "date": str(pred_date.date()),
            "close": p["price"],
            "upper": p["upper"],
            "lower": p["lower"],
        })

    return {
        "current_price": current_price,
        "history": history,
        "predictions": predictions_formatted,
        "trend": trend,
        "confidence": confidence,
        "method": "linear_regression",
    }
