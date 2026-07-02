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
    取得股價預測結果（未來 10 天）
    優先使用 LSTM，若不可用則使用輕量線性回歸預測
    """
    # 優先嘗試 LSTM
    if LSTM_AVAILABLE:
        try:
            predictor = get_predictor(stock_id)
            result = predictor.predict(stock_id)
            return {"status": "success", "stock_id": stock_id, **result}
        except Exception:
            pass  # LSTM 失敗就 fallback 到輕量預測

    # Fallback: 輕量預測器
    try:
        from app.models.light_predictor import predict_price
        result = predict_price(stock_id)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return {"status": "success", "stock_id": stock_id, **result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"預測失敗：{str(e)}")
