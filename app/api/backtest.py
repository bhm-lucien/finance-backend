"""
歷史回測 API
用歷史資料驗證分析模型的準確度
"""
from fastapi import APIRouter, HTTPException, Query
import pandas as pd
import numpy as np
from app.services.data_fetcher import fetch_stock_price
from app.indicators.technical import calculate_rsi, calculate_macd, calculate_kd

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


@router.get("/signal-accuracy/{stock_id}")
async def backtest_signal_accuracy(
    stock_id: str,
    days: int = Query(default=180, ge=60, le=365),
):
    """
    回測預警燈號的準確度
    模擬歷史每一天的燈號判斷，與後續 5 天的漲跌做比對
    """
    try:
        df = fetch_stock_price(stock_id, days=days)
        if len(df) < 30:
            raise ValueError("資料不足")

        results = []
        correct = 0
        total = 0

        for i in range(25, len(df) - 5):
            window = df.iloc[:i+1]
            future = df.iloc[i+1:i+6]

            if len(future) < 5:
                continue

            # 計算當天的簡化指標
            close = window["close"].iloc[-1]
            rsi = calculate_rsi(window).iloc[-1]
            ma20 = window["close"].rolling(20).mean().iloc[-1]
            vol_today = window["volume"].iloc[-1]
            vol_avg = window["volume"].tail(20).mean()
            vol_ratio = vol_today / vol_avg if vol_avg > 0 else 1
            is_high = close >= window["close"].tail(20).quantile(0.85)

            # 判斷燈號
            if is_high and vol_ratio > 1.5:
                signal = "red"  # 主力出貨
            elif rsi > 70:
                signal = "orange"  # 過熱
            elif close < ma20 and vol_ratio > 1.2:
                signal = "black"  # 跌破趨勢
            elif rsi < 45 and vol_ratio > 1.1:
                signal = "green"  # 低檔轉強
            else:
                signal = "neutral"

            # 後續 5 日漲跌
            future_return = (future["close"].iloc[-1] - close) / close * 100

            # 判斷是否正確
            is_correct = False
            if signal == "red" and future_return < 0:
                is_correct = True
            elif signal == "orange" and -2 < future_return < 3:
                is_correct = True
            elif signal == "green" and future_return > 0:
                is_correct = True
            elif signal == "black" and future_return < -1:
                is_correct = True
            elif signal == "neutral":
                is_correct = True  # 中性不計入

            if signal != "neutral":
                total += 1
                if is_correct:
                    correct += 1

            results.append({
                "date": str(window["date"].iloc[-1].date()),
                "signal": signal,
                "future_5d_return": round(float(future_return), 2),
                "correct": is_correct,
            })

        accuracy = round(correct / total * 100, 1) if total > 0 else 0

        # 各燈號統計
        signal_stats = {}
        for sig in ["red", "orange", "green", "black"]:
            sig_results = [r for r in results if r["signal"] == sig]
            if sig_results:
                sig_correct = len([r for r in sig_results if r["correct"]])
                avg_return = np.mean([r["future_5d_return"] for r in sig_results])
                signal_stats[sig] = {
                    "count": len(sig_results),
                    "correct": sig_correct,
                    "accuracy": round(sig_correct / len(sig_results) * 100, 1),
                    "avg_5d_return": round(float(avg_return), 2),
                }

        return {
            "stock_id": stock_id,
            "period_days": days,
            "total_signals": total,
            "correct_signals": correct,
            "accuracy": accuracy,
            "signal_stats": signal_stats,
            "recent_signals": results[-20:],  # 最近 20 筆
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/strategy-pnl/{stock_id}")
async def backtest_strategy_pnl(
    stock_id: str,
    days: int = Query(default=180, ge=60, le=365),
):
    """
    回測簡單策略的損益
    策略：綠燈買進、紅燈賣出、其他持有
    """
    try:
        df = fetch_stock_price(stock_id, days=days)
        if len(df) < 30:
            raise ValueError("資料不足")

        position = 0  # 0=空手, 1=持有
        buy_price = 0.0
        trades = []
        equity_curve = []
        initial_capital = 1000000  # 100 萬
        capital = initial_capital

        for i in range(25, len(df)):
            window = df.iloc[:i+1]
            close = float(window["close"].iloc[-1])
            date = str(window["date"].iloc[-1].date())

            rsi = calculate_rsi(window).iloc[-1]
            ma20 = window["close"].rolling(20).mean().iloc[-1]
            vol_today = window["volume"].iloc[-1]
            vol_avg = window["volume"].tail(20).mean()
            vol_ratio = vol_today / vol_avg if vol_avg > 0 else 1
            is_high = close >= window["close"].tail(20).quantile(0.85)

            # 判斷訊號
            if is_high and vol_ratio > 1.5:
                signal = "red"
            elif rsi < 45 and vol_ratio > 1.1 and close > ma20:
                signal = "green"
            else:
                signal = "hold"

            # 執行交易
            if signal == "green" and position == 0:
                position = 1
                buy_price = close
                shares = int(capital / close)
                trades.append({"date": date, "action": "買進", "price": close, "shares": shares})
            elif signal == "red" and position == 1:
                pnl = (close - buy_price) / buy_price * 100
                shares = int(capital / buy_price)
                capital = shares * close
                position = 0
                trades.append({"date": date, "action": "賣出", "price": close, "pnl_pct": round(pnl, 2)})

            # 權益曲線
            if position == 1:
                current_value = int(capital / buy_price) * close
            else:
                current_value = capital
            equity_curve.append({"date": date, "value": round(current_value, 0)})

        # 計算績效
        final_value = equity_curve[-1]["value"] if equity_curve else initial_capital
        total_return = (final_value - initial_capital) / initial_capital * 100

        # 買入持有績效比較
        buy_hold_return = (float(df["close"].iloc[-1]) - float(df["close"].iloc[25])) / float(df["close"].iloc[25]) * 100

        win_trades = [t for t in trades if t.get("pnl_pct", 0) > 0]
        lose_trades = [t for t in trades if t.get("pnl_pct", 0) < 0]

        return {
            "stock_id": stock_id,
            "period_days": days,
            "strategy": "綠燈買進、紅燈賣出",
            "initial_capital": initial_capital,
            "final_value": round(final_value, 0),
            "total_return_pct": round(total_return, 2),
            "buy_hold_return_pct": round(buy_hold_return, 2),
            "total_trades": len(trades),
            "win_trades": len(win_trades),
            "lose_trades": len(lose_trades),
            "win_rate": round(len(win_trades) / max(1, len(win_trades) + len(lose_trades)) * 100, 1),
            "trades": trades[-10:],  # 最近 10 筆交易
            "equity_curve": equity_curve[::5],  # 每 5 天取一點
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/strategies")
async def get_strategies():
    """取得所有可用的回測策略列表"""
    from app.services.backtest_strategies import get_strategy_list
    return {"strategies": get_strategy_list()}


@router.get("/strategy/{stock_id}/{strategy_id}")
async def run_strategy_backtest(stock_id: str, strategy_id: str, days: int = Query(default=365, ge=60, le=730)):
    """對單支股票執行特定策略回測"""
    from app.services.backtest_strategies import run_backtest
    try:
        result = run_backtest(stock_id, strategy_id, days)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/strategy-all/{stock_id}")
async def run_all_strategies_backtest(stock_id: str, days: int = Query(default=365, ge=60, le=730)):
    """對單支股票跑所有 16 種策略的回測摘要"""
    from app.services.backtest_strategies import run_all_strategies
    try:
        results = run_all_strategies(stock_id, days)
        return {"stock_id": stock_id, "days": days, "strategies": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
