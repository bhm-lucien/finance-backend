"""
AI 預測 API 路由
"""
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/predict", tags=["predict"])

# 嘗試匯入 LSTM 預測器（如果 torch 不存在則跳過）
try:
    from app.models.lstm_predictor import get_predictor
    LSTM_AVAILABLE = True
except ImportError:
    LSTM_AVAILABLE = False


@router.post("/train/{stock_id}")
async def train_model(stock_id: str, epochs: int = 80):
    """
    訓練 LSTM 預測模型（第一次預測時會自動訓練，也可手動觸發）
    """
    if not LSTM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LSTM 模組未安裝（缺少 PyTorch）")
    try:
        predictor = get_predictor(stock_id)
        result = predictor.train(stock_id, epochs=epochs, days=365)
        return {"status": "success", "stock_id": stock_id, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"訓練失敗：{str(e)}")


@router.get("/forecast/{stock_id}")
async def get_forecast(stock_id: str):
    """
    取得 LSTM 股價預測結果（未來 10 天）
    若尚未訓練，會自動訓練 50 輪
    """
    if not LSTM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LSTM 模組未安裝（缺少 PyTorch）")
    try:
        predictor = get_predictor(stock_id)
        result = predictor.predict(stock_id)
        return {"status": "success", "stock_id": stock_id, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"預測失敗：{str(e)}")
