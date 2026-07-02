"""
16 種策略回測引擎

每種策略定義進場/出場條件，回測歷史資料計算：
- 勝率、平均報酬、最大回撤、交易次數
- 訓練期 vs 驗證期分割
"""
import time
import numpy as np
import pandas as pd
from app.services.data_fetcher import fetch_stock_price
from app.indicators.technical import calculate_rsi, calculate_macd, calculate_moving_averages


_backtest_cache: dict[str, dict] = {}
CACHE_TTL = 3600  # 1 小時快取


# 16 種策略定義
STRATEGIES = [
    {"id": "kd_golden", "name": "KD 黃金交叉", "category": "動能", "holding_days": 5},
    {"id": "kd_death", "name": "KD 死亡交叉放空", "category": "動能", "holding_days": 5},
    {"id": "macd_bull", "name": "MACD 翻多", "category": "動能", "holding_days": 10},
    {"id": "macd_bear", "name": "MACD 翻空放空", "category": "動能", "holding_days": 10},
    {"id": "rsi_oversold", "name": "RSI 超賣反彈", "category": "量價", "holding_days": 5},
    {"id": "rsi_overbought", "name": "RSI 超買放空", "category": "量價", "holding_days": 5},
    {"id": "ma_bullish", "name": "均線多頭排列", "category": "趨勢", "holding_days": 10},
    {"id": "below_ma20", "name": "跌破 MA20 放空", "category": "趨勢", "holding_days": 10},
    {"id": "bollinger_lower", "name": "布林下軌反彈", "category": "趨勢", "holding_days": 5},
    {"id": "bollinger_upper", "name": "布林上軌突破", "category": "趨勢", "holding_days": 5},
    {"id": "vol_price_up", "name": "量價齊揚", "category": "量價", "holding_days": 5},
    {"id": "ibs_low", "name": "IBS 低檔反彈", "category": "量價", "holding_days": 3},
    {"id": "ibs_high", "name": "IBS 高檔出場", "category": "量價", "holding_days": 3},
    {"id": "breakout_20d", "name": "突破 20 日高點", "category": "突破", "holding_days": 10},
    {"id": "foreign_buy", "name": "外資連買 3 日", "category": "籌碼", "holding_days": 10},
    {"id": "composite", "name": "綜合多條件", "category": "綜合", "holding_days": 5},
]


def get_strategy_list() -> list[dict]:
    """回傳所有可用策略列表"""
    return STRATEGIES


def run_backtest(stock_id: str, strategy_id: str, days: int = 365) -> dict:
    """
    對單支股票執行策略回測

    Args:
        stock_id: 股票代碼
        strategy_id: 策略 ID
        days: 回測天數

    Returns:
        {
            "strategy": {"id", "name", "category"},
            "stock_id": "2330",
            "period": "2025-07-01 ~ 2026-07-01",
            "total_trades": 15,
            "win_rate": 66.7,
            "avg_return": 1.8,
            "max_drawdown": -5.2,
            "total_return": 27.0,
            "profit_factor": 2.1,
            "trades": [{"date", "type", "price", "exit_date", "exit_price", "return_pct"}],
            "train_result": {...},  # 前 70% 期間
            "test_result": {...},   # 後 30% 期間
        }
    """
    cache_key = f"bt_{stock_id}_{strategy_id}_{days}"
    if cache_key in _backtest_cache:
        entry = _backtest_cache[cache_key]
        if time.time() - entry["time"] < CACHE_TTL:
            return entry["data"]

    # 取得歷史資料
    df = fetch_stock_price(stock_id, days=days)
    if len(df) < 60:
        return {"error": f"資料不足（需要至少 60 天，目前只有 {len(df)} 天）"}

    # 找到策略定義
    strategy = next((s for s in STRATEGIES if s["id"] == strategy_id), None)
    if not strategy:
        return {"error": f"未知策略: {strategy_id}"}

    holding_days = strategy["holding_days"]

    # 產生進場訊號
    signals = _generate_signals(df, strategy_id)

    # 執行回測
    trades = _execute_trades(df, signals, holding_days)

    if not trades:
        result = {
            "strategy": strategy,
            "stock_id": stock_id,
            "period": f"{df['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df['date'].iloc[-1].strftime('%Y-%m-%d')}",
            "total_trades": 0,
            "win_rate": 0,
            "avg_return": 0,
            "max_drawdown": 0,
            "total_return": 0,
            "profit_factor": 0,
            "trades": [],
            "train_result": None,
            "test_result": None,
        }
        _backtest_cache[cache_key] = {"data": result, "time": time.time()}
        return result

    # 計算績效
    returns = [t["return_pct"] for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]

    win_rate = round(len(wins) / len(returns) * 100, 1) if returns else 0
    avg_return = round(np.mean(returns), 2) if returns else 0
    total_return = round(sum(returns), 2)
    max_drawdown = round(min(returns), 2) if returns else 0
    profit_factor = round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) != 0 else 999

    # 訓練/驗證分割（70/30）
    split_idx = int(len(trades) * 0.7)
    train_trades = trades[:split_idx] if split_idx > 0 else trades
    test_trades = trades[split_idx:] if split_idx < len(trades) else []

    train_result = _calc_stats(train_trades) if train_trades else None
    test_result = _calc_stats(test_trades) if test_trades else None

    result = {
        "strategy": strategy,
        "stock_id": stock_id,
        "period": f"{df['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df['date'].iloc[-1].strftime('%Y-%m-%d')}",
        "total_trades": len(trades),
        "win_rate": win_rate,
        "avg_return": avg_return,
        "max_drawdown": max_drawdown,
        "total_return": total_return,
        "profit_factor": profit_factor,
        "trades": trades[-20:],  # 只回傳最近 20 筆
        "train_result": train_result,
        "test_result": test_result,
    }

    _backtest_cache[cache_key] = {"data": result, "time": time.time()}
    return result


def run_all_strategies(stock_id: str, days: int = 365) -> list[dict]:
    """對一支股票跑所有 16 種策略的回測摘要"""
    results = []
    for strategy in STRATEGIES:
        try:
            bt = run_backtest(stock_id, strategy["id"], days)
            if "error" not in bt:
                results.append({
                    "id": strategy["id"],
                    "name": strategy["name"],
                    "category": strategy["category"],
                    "total_trades": bt["total_trades"],
                    "win_rate": bt["win_rate"],
                    "avg_return": bt["avg_return"],
                    "total_return": bt["total_return"],
                    "max_drawdown": bt["max_drawdown"],
                    "profit_factor": bt["profit_factor"],
                })
        except Exception:
            continue
    # 按勝率排序
    results.sort(key=lambda x: x["win_rate"], reverse=True)
    return results


def _generate_signals(df: pd.DataFrame, strategy_id: str) -> list[int]:
    """
    產生進場訊號（1=做多進場，-1=做空進場，0=無訊號）
    """
    n = len(df)
    signals = [0] * n

    close = df["close"].astype(float).values
    high = df["high"].astype(float).values
    low = df["low"].astype(float).values
    volume = df["volume"].astype(float).values

    # 計算技術指標
    ma_df = calculate_moving_averages(df)
    ma5 = ma_df["ma5"].astype(float).values if "ma5" in ma_df else np.zeros(n)
    ma20 = ma_df["ma20"].astype(float).values if "ma20" in ma_df else np.zeros(n)
    ma60 = ma_df["ma60"].astype(float).values if "ma60" in ma_df else np.zeros(n)

    rsi_series = calculate_rsi(df)
    rsi = rsi_series.astype(float).values if not rsi_series.empty else np.full(n, 50)

    macd_data = calculate_macd(df)
    macd_hist = macd_data["histogram"].astype(float).values if "histogram" in macd_data else np.zeros(n)

    # 布林通道
    ma20_arr = pd.Series(close).rolling(20).mean().values
    std20 = pd.Series(close).rolling(20).std().values
    bb_upper = ma20_arr + 2 * std20
    bb_lower = ma20_arr - 2 * std20

    # KD（RSV）
    for i in range(20, n):
        if strategy_id == "kd_golden":
            # K > D 且前一天 K < D
            low_9 = min(low[max(0, i-8):i+1])
            high_9 = max(high[max(0, i-8):i+1])
            rsv = (close[i] - low_9) / (high_9 - low_9) * 100 if (high_9 - low_9) > 0 else 50
            rsv_prev = (close[i-1] - min(low[max(0, i-9):i])) / (max(high[max(0, i-9):i]) - min(low[max(0, i-9):i])) * 100 if (max(high[max(0, i-9):i]) - min(low[max(0, i-9):i])) > 0 else 50
            if rsv > 50 and rsv_prev <= 50:
                signals[i] = 1

        elif strategy_id == "kd_death":
            low_9 = min(low[max(0, i-8):i+1])
            high_9 = max(high[max(0, i-8):i+1])
            rsv = (close[i] - low_9) / (high_9 - low_9) * 100 if (high_9 - low_9) > 0 else 50
            rsv_prev = (close[i-1] - min(low[max(0, i-9):i])) / (max(high[max(0, i-9):i]) - min(low[max(0, i-9):i])) * 100 if (max(high[max(0, i-9):i]) - min(low[max(0, i-9):i])) > 0 else 50
            if rsv < 50 and rsv_prev >= 50:
                signals[i] = -1

        elif strategy_id == "macd_bull":
            if macd_hist[i] > 0 and macd_hist[i-1] <= 0:
                signals[i] = 1

        elif strategy_id == "macd_bear":
            if macd_hist[i] < 0 and macd_hist[i-1] >= 0:
                signals[i] = -1

        elif strategy_id == "rsi_oversold":
            if rsi[i] < 30 and rsi[i-1] >= 30:
                signals[i] = 1

        elif strategy_id == "rsi_overbought":
            if rsi[i] > 70 and rsi[i-1] <= 70:
                signals[i] = -1

        elif strategy_id == "ma_bullish":
            if close[i] > ma5[i] > ma20[i] > ma60[i] and not (close[i-1] > ma5[i-1] > ma20[i-1] > ma60[i-1]):
                signals[i] = 1

        elif strategy_id == "below_ma20":
            if close[i] < ma20[i] and close[i-1] >= ma20[i-1] and ma20[i] > 0:
                signals[i] = -1

        elif strategy_id == "bollinger_lower":
            if not np.isnan(bb_lower[i]) and close[i] <= bb_lower[i] and close[i-1] > bb_lower[i-1]:
                signals[i] = 1

        elif strategy_id == "bollinger_upper":
            if not np.isnan(bb_upper[i]) and close[i] >= bb_upper[i] and close[i-1] < bb_upper[i-1]:
                signals[i] = 1

        elif strategy_id == "vol_price_up":
            vol_avg = np.mean(volume[max(0, i-19):i]) if i >= 20 else volume[i]
            if close[i] > close[i-1] and volume[i] > vol_avg * 1.5:
                signals[i] = 1

        elif strategy_id == "ibs_low":
            ibs = (close[i] - low[i]) / (high[i] - low[i]) if (high[i] - low[i]) > 0 else 0.5
            if ibs <= 0.2:
                signals[i] = 1

        elif strategy_id == "ibs_high":
            ibs = (close[i] - low[i]) / (high[i] - low[i]) if (high[i] - low[i]) > 0 else 0.5
            if ibs >= 0.8:
                signals[i] = -1

        elif strategy_id == "breakout_20d":
            high_20 = max(high[max(0, i-19):i])
            if close[i] > high_20:
                signals[i] = 1

        elif strategy_id == "foreign_buy":
            # 簡化：連續 3 天上漲 + 放量作為代理
            if i >= 3 and all(close[i-j] > close[i-j-1] for j in range(3)):
                vol_avg = np.mean(volume[max(0, i-19):i])
                if volume[i] > vol_avg:
                    signals[i] = 1

        elif strategy_id == "composite":
            # 綜合：RSI < 40 + MACD 翻多 + 站上 MA20
            if rsi[i] < 40 and macd_hist[i] > 0 and close[i] > ma20[i] and ma20[i] > 0:
                signals[i] = 1

    return signals


def _execute_trades(df: pd.DataFrame, signals: list[int], holding_days: int) -> list[dict]:
    """根據訊號執行交易，固定持有天數後出場"""
    trades = []
    close = df["close"].astype(float).values
    dates = df["date"].values
    n = len(df)
    i = 0

    while i < n:
        if signals[i] != 0:
            entry_price = close[i]
            entry_date = str(pd.Timestamp(dates[i]).date())
            direction = signals[i]  # 1=多, -1=空

            # 出場
            exit_idx = min(i + holding_days, n - 1)
            exit_price = close[exit_idx]
            exit_date = str(pd.Timestamp(dates[exit_idx]).date())

            # 計算報酬
            if direction == 1:
                return_pct = round((exit_price - entry_price) / entry_price * 100, 2)
            else:
                return_pct = round((entry_price - exit_price) / entry_price * 100, 2)

            trades.append({
                "date": entry_date,
                "type": "買入" if direction == 1 else "放空",
                "price": round(entry_price, 2),
                "exit_date": exit_date,
                "exit_price": round(exit_price, 2),
                "return_pct": return_pct,
            })

            i = exit_idx + 1  # 出場後才能再進場
        else:
            i += 1

    return trades


def _calc_stats(trades: list[dict]) -> dict:
    """計算一組交易的統計"""
    if not trades:
        return {"trades": 0, "win_rate": 0, "avg_return": 0, "total_return": 0}

    returns = [t["return_pct"] for t in trades]
    wins = [r for r in returns if r > 0]

    return {
        "trades": len(trades),
        "win_rate": round(len(wins) / len(returns) * 100, 1),
        "avg_return": round(np.mean(returns), 2),
        "total_return": round(sum(returns), 2),
    }
