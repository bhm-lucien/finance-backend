"""
AI 預測 API 路由
"""
from fastapi import APIRouter, HTTPException
from app.models.lstm_predictor import get_predictor

router = APIRouter(prefix="/api/predict", tags=["predict"])


@router.post("/train/{stock_id}")
async def train_model(stock_id: str, epochs: int = 80):
    """
    訓練 LSTM 預測模型（第一次預測時會自動訓練，也可手動觸發）
    """
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
    try:
        predictor = get_predictor(stock_id)
        result = predictor.predict(stock_id)
        return {"status": "success", "stock_id": stock_id, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"預測失敗：{str(e)}")
