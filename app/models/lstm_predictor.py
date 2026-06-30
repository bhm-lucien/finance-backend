"""
LSTM 股價預測模型
使用歷史 OHLCV + 技術指標，預測未來 3/5/10 日收盤價走勢
"""
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.preprocessing import MinMaxScaler
from app.services.data_fetcher import fetch_stock_price
from app.indicators.technical import calculate_rsi, calculate_macd, calculate_kd


# ── LSTM 模型定義 ─────────────────────────────────────

class StockLSTM(nn.Module):
    """多層 LSTM 股價預測網路"""

    def __init__(self, input_size: int, hidden_size: int = 64, num_layers: int = 2, output_size: int = 10):
        super().__init__()
        self.hidden_size = hidden_size
        self.num_layers = num_layers

        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=0.2,
        )
        self.fc = nn.Sequential(
            nn.Linear(hidden_size, 32),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(32, output_size),
        )

    def forward(self, x):
        # x shape: (batch, seq_len, features)
        out, _ = self.lstm(x)
        # 取最後一個時間步的輸出
        out = out[:, -1, :]
        out = self.fc(out)
        return out


# ── 資料準備 ──────────────────────────────────────────

def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    從原始 OHLCV 資料準備模型特徵

    特徵包含：收盤價變化率、成交量變化率、RSI、MACD、KD
    """
    features = pd.DataFrame()

    # 價格相關特徵
    features["close_pct"] = df["close"].pct_change()
    features["high_low_pct"] = (df["high"] - df["low"]) / df["close"]
    features["open_close_pct"] = (df["close"] - df["open"]) / df["open"]

    # 成交量變化率
    features["volume_pct"] = df["volume"].pct_change()

    # 技術指標
    features["rsi"] = calculate_rsi(df, period=14) / 100.0  # 正規化到 0~1

    macd = calculate_macd(df)
    features["macd"] = macd["macd"]
    features["macd_hist"] = macd["histogram"]

    kd = calculate_kd(df)
    features["k"] = kd["k"] / 100.0
    features["d"] = kd["d"] / 100.0

    # 均線相對位置
    features["ma5_ratio"] = df["close"] / df["close"].rolling(5).mean() - 1
    features["ma20_ratio"] = df["close"] / df["close"].rolling(20).mean() - 1

    # 去除 NaN
    features = features.dropna()

    return features


def create_sequences(data: np.ndarray, targets: np.ndarray, seq_len: int = 30):
    """
    建立時序序列資料

    Args:
        data: 特徵矩陣 (samples, features)
        targets: 目標值 (samples, output_days)
        seq_len: 回看天數

    Returns:
        X, y 張量
    """
    X, y = [], []
    for i in range(seq_len, len(data) - len(targets[0]) + 1):
        X.append(data[i - seq_len:i])
        if i < len(targets):
            y.append(targets[i])

    return np.array(X), np.array(y)


# ── 訓練與預測 ────────────────────────────────────────

class LSTMPredictor:
    """LSTM 預測器，封裝訓練與預測邏輯"""

    def __init__(self, seq_len: int = 30, predict_days: int = 10):
        self.seq_len = seq_len
        self.predict_days = predict_days
        self.model = None
        self.scaler = MinMaxScaler()
        self.price_scaler = MinMaxScaler()
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    def train(self, stock_id: str, epochs: int = 100, days: int = 365) -> dict:
        """
        訓練 LSTM 模型

        Args:
            stock_id: 股票代碼
            epochs: 訓練輪數
            days: 用多少天歷史資料訓練

        Returns:
            訓練結果資訊
        """
        # 取得資料
        df = fetch_stock_price(stock_id, days=days)
        if len(df) < self.seq_len + self.predict_days + 30:
            raise ValueError(f"資料不足，需要至少 {self.seq_len + self.predict_days + 30} 筆")

        # 準備特徵
        features_df = prepare_features(df)
        close_prices = df["close"].iloc[len(df) - len(features_df):].values.reshape(-1, 1)

        # 正規化
        feature_data = self.scaler.fit_transform(features_df.values)
        price_scaled = self.price_scaler.fit_transform(close_prices)

        # 建立目標：未來 N 天的收盤價變化率
        targets = []
        for i in range(len(price_scaled) - self.predict_days):
            future_prices = price_scaled[i + 1:i + 1 + self.predict_days].flatten()
            if len(future_prices) == self.predict_days:
                targets.append(future_prices)
        targets = np.array(targets)

        # 裁剪到相同長度
        min_len = min(len(feature_data), len(targets))
        feature_data = feature_data[:min_len]
        targets = targets[:min_len]

        # 建立序列
        X, y = create_sequences(feature_data, targets, self.seq_len)

        if len(X) == 0:
            raise ValueError("無法建立訓練序列，資料可能不足")

        # 切分訓練/驗證 (80/20)
        split = int(len(X) * 0.8)
        X_train, X_val = X[:split], X[split:]
        y_train, y_val = y[:split], y[split:]

        # 轉 Tensor
        X_train_t = torch.FloatTensor(X_train).to(self.device)
        y_train_t = torch.FloatTensor(y_train).to(self.device)
        X_val_t = torch.FloatTensor(X_val).to(self.device)
        y_val_t = torch.FloatTensor(y_val).to(self.device)

        # 建立模型
        input_size = X_train.shape[2]
        self.model = StockLSTM(
            input_size=input_size,
            hidden_size=64,
            num_layers=2,
            output_size=self.predict_days,
        ).to(self.device)

        # 訓練
        optimizer = torch.optim.Adam(self.model.parameters(), lr=0.001)
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=10, factor=0.5)
        criterion = nn.MSELoss()

        best_val_loss = float("inf")
        train_losses = []

        for epoch in range(epochs):
            self.model.train()
            optimizer.zero_grad()
            output = self.model(X_train_t)
            loss = criterion(output, y_train_t)
            loss.backward()
            optimizer.step()

            # 驗證
            self.model.eval()
            with torch.no_grad():
                val_output = self.model(X_val_t)
                val_loss = criterion(val_output, y_val_t)

            scheduler.step(val_loss)
            train_losses.append(loss.item())

            if val_loss.item() < best_val_loss:
                best_val_loss = val_loss.item()

        return {
            "epochs": epochs,
            "train_samples": len(X_train),
            "val_samples": len(X_val),
            "final_train_loss": train_losses[-1],
            "best_val_loss": best_val_loss,
            "input_features": input_size,
            "device": str(self.device),
        }

    def predict(self, stock_id: str, days: int = 120) -> dict:
        """
        用訓練好的模型預測未來走勢

        Returns:
            dict 包含歷史K線 + 預測路徑
        """
        if self.model is None:
            # 還沒訓練過，先快速訓練
            self.train(stock_id, epochs=50, days=365)

        # 取得最新資料（用跟訓練一樣的天數確保 scaler 一致）
        df = fetch_stock_price(stock_id, days=365)
        features_df = prepare_features(df)
        close_prices = df["close"].iloc[len(df) - len(features_df):].values

        # 正規化（用已有的 scaler）
        feature_data = self.scaler.transform(features_df.values)

        # 取最後 seq_len 天做預測
        last_sequence = feature_data[-self.seq_len:]
        X_pred = torch.FloatTensor(last_sequence).unsqueeze(0).to(self.device)

        # 預測
        self.model.eval()
        with torch.no_grad():
            pred_scaled = self.model(X_pred).cpu().numpy()[0]

        # 反正規化取得預測價格
        pred_prices = self.price_scaler.inverse_transform(pred_scaled.reshape(-1, 1)).flatten()

        # 安全檢查：預測價格不應偏離目前價格超過 20%
        current_price = float(close_prices[-1])
        safe_predictions = []
        for p in pred_prices:
            p = float(p)
            # 如果預測值偏離太多，用合理範圍修正
            if abs(p - current_price) / current_price > 0.2:
                # 用漸進方式：基於最近趨勢做線性外推
                recent_change = (close_prices[-1] - close_prices[-5]) / 5 if len(close_prices) >= 5 else 0
                p = current_price + recent_change * (len(safe_predictions) + 1) * 0.5
            safe_predictions.append(round(p, 2))

        # 最近 20 天歷史 K 線（供前端顯示）
        recent_df = df.tail(20)
        history = [
            {"date": str(row["date"].date()), "close": float(row["close"])}
            for _, row in recent_df.iterrows()
        ]

        # 生成預測日期
        last_date = df["date"].iloc[-1]
        predict_dates = pd.bdate_range(start=last_date + pd.Timedelta(days=1), periods=self.predict_days)

        predictions = [
            {"date": str(d.date()), "close": round(float(p), 2)}
            for d, p in zip(predict_dates, safe_predictions)
        ]

        return {
            "history": history,
            "predictions": predictions,
            "predict_days": self.predict_days,
            "current_price": current_price,
        }


# 全域預測器實例（避免重複訓練）
_predictor_cache: dict[str, LSTMPredictor] = {}


def get_predictor(stock_id: str) -> LSTMPredictor:
    """取得或建立預測器（若切換股票則重新建立）"""
    if stock_id not in _predictor_cache:
        _predictor_cache[stock_id] = LSTMPredictor()
    return _predictor_cache[stock_id]


def clear_predictor(stock_id: str):
    """清除指定股票的預測器快取"""
    if stock_id in _predictor_cache:
        del _predictor_cache[stock_id]
