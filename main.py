"""
全方位 AI 股票分析儀表板 — 後端伺服器
"""
import asyncio
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import CORS_ORIGINS, CORS_ALLOW_REGEX, HOST, PORT


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用程式生命週期管理"""
    # 啟動時
    # 背景預訓練 LSTM（如果 torch 可用）
    def _pretrain():
        try:
            import importlib
            if importlib.util.find_spec("torch") is None:
                print("[啟動] PyTorch 未安裝，跳過 LSTM 預訓練")
                return
            from app.models.lstm_predictor import get_predictor
            print("[啟動] 背景預訓練 LSTM 模型 (2330 台積電)...")
            predictor = get_predictor("2330")
            predictor.train("2330", epochs=50, days=365)
            print("[啟動] LSTM 模型預訓練完成 ✓")
        except Exception as e:
            print(f"[啟動] LSTM 預訓練失敗（不影響其他功能）: {e}")

    thread = threading.Thread(target=_pretrain, daemon=True)
    thread.start()

    # 啟動 Discord Bot（在背景 asyncio task）
    bot_task = None
    try:
        from app.bot.discord_bot import start_bot
        bot_task = asyncio.create_task(start_bot())
        print("[啟動] Discord Bot 背景任務已建立")
    except Exception as e:
        print(f"[啟動] Discord Bot 啟動失敗（不影響 API）: {e}")

    yield

    # 關閉時
    if bot_task:
        bot_task.cancel()


app = FastAPI(
    title="AI 股票分析儀表板 API",
    description="提供台股即時分析、技術指標、AI 預測等功能",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS 設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=CORS_ALLOW_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 註冊路由
from app.api.stock import router as stock_router
from app.api.predict import router as predict_router
from app.api.backtest import router as backtest_router

app.include_router(stock_router)
app.include_router(predict_router)
app.include_router(backtest_router)


@app.get("/")
async def root():
    return {"message": "AI 股票分析儀表板 API 運作中", "version": "0.1.0"}


@app.get("/health")
async def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
