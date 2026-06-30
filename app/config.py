"""
應用程式設定檔
"""
import os
from dotenv import load_dotenv

load_dotenv()

# FinMind API 設定
FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN", "")  # 免費方案可不填

# 預設股票代碼
DEFAULT_STOCK_ID = "2330"

# CORS 設定（從環境變數取得前端網址）
_frontend_url = os.getenv("FRONTEND_URL", "")
CORS_ORIGINS = [
    "http://localhost:5173",  # Vite 開發伺服器
    "http://localhost:3000",
]
if _frontend_url:
    CORS_ORIGINS.append(_frontend_url)
# 也允許所有 vercel.app 子網域（用 allow_origin_regex）
CORS_ALLOW_REGEX = r"https://.*\.vercel\.app"

# 伺服器設定
HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", "8000"))
