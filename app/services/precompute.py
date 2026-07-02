"""
預計算服務 — 背景預先抓取熱門股票資料

啟動時和每日收盤後自動執行：
1. 抓取熱門股票的歷史 K 線存入快取
2. 計算技術指標存入快取
3. 減少使用者查詢時的 API 延遲
"""
import time
import threading
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# 熱門股票清單（預設抓這些）
HOT_STOCKS = [
    "2330", "2317", "2454", "2308", "2382",  # 權值股
    "2303", "2412", "2881", "2882", "2886",  # 金融 + 電信
    "3711", "2345", "6505", "1301", "1303",  # 傳產
    "3037", "2379", "2357", "3034", "2603",  # 航運 + 電子
]


def start_precompute(daemon: bool = True):
    """
    啟動背景預計算（在 daemon thread 中執行）
    """
    thread = threading.Thread(target=_precompute_worker, daemon=daemon)
    thread.start()
    return thread


def _precompute_worker():
    """預計算工作者"""
    logger.info("[預計算] 開始預計算熱門股票資料...")

    from app.services.data_fetcher import fetch_stock_price

    success = 0
    failed = 0

    for stock_id in HOT_STOCKS:
        try:
            # 抓取 120 天歷史資料（會自動存入快取）
            df = fetch_stock_price(stock_id, days=120)
            if len(df) > 0:
                success += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            logger.debug(f"[預計算] {stock_id} 失敗: {e}")

        # 避免 API 限流
        time.sleep(1)

    logger.info(f"[預計算] 完成：成功 {success} / 失敗 {failed} / 共 {len(HOT_STOCKS)} 支")


def schedule_daily_precompute():
    """
    每日收盤後（15:00）自動重新預計算

    這個函式啟動一個背景 thread 不斷等待，到了 15:00 就重新抓資料
    """
    def _scheduler():
        while True:
            now = datetime.now()
            # 等到 15:00
            if now.hour == 15 and now.minute == 0:
                logger.info("[預計算] 收盤後自動重新預計算")
                _precompute_worker()
                # 避免同一分鐘重複執行
                time.sleep(120)
            else:
                time.sleep(30)

    thread = threading.Thread(target=_scheduler, daemon=True)
    thread.start()
    return thread
