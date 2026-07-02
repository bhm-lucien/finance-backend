"""
富果（Fugle）WebSocket 即時報價服務

負責：
1. 連接富果 MarketData WebSocket，接收即時報價推播
2. 管理股票訂閱（訂閱/取消訂閱/閒置超時自動退訂）
3. 維護即時報價快取（供 realtime.py 讀取）
4. 斷線自動重連
5. 通知前端 WebSocket 客戶端報價更新
"""
import asyncio
import time
import logging
from typing import Optional, Callable

from app.config import FUGLE_API_KEY

logger = logging.getLogger(__name__)

# 即時報價快取：{stock_id: {報價資料}}
_fugle_quote_cache: dict[str, dict] = {}

# 訂閱管理：{stock_id: last_access_time}
_subscriptions: dict[str, float] = {}

# 閒置超時（秒）— 超過此時間沒人查詢就自動取消訂閱
IDLE_TIMEOUT = 300  # 5 分鐘

# WebSocket 管理器單例
_ws_manager: Optional["FugleWebSocketManager"] = None

# 前端客戶端通知回呼
_client_notify_callback: Optional[Callable] = None


def set_client_notify_callback(callback: Callable):
    """設定當報價更新時通知前端客戶端的回呼函式"""
    global _client_notify_callback
    _client_notify_callback = callback


def get_fugle_quote(stock_id: str) -> Optional[dict]:
    """
    從富果快取取得即時報價

    Returns:
        dict 報價資料，如果沒有則回傳 None
    """
    if stock_id in _fugle_quote_cache:
        # 更新最後存取時間（維持訂閱）
        _subscriptions[stock_id] = time.time()
        return _fugle_quote_cache[stock_id]
    return None


async def subscribe_stock(stock_id: str):
    """訂閱一檔股票的即時報價"""
    global _ws_manager
    if _ws_manager is None:
        logger.warning("[Fugle WS] 管理器尚未初始化，無法訂閱")
        return

    _subscriptions[stock_id] = time.time()
    await _ws_manager.subscribe(stock_id)


async def unsubscribe_stock(stock_id: str):
    """取消訂閱一檔股票"""
    global _ws_manager
    if _ws_manager is None:
        return

    _subscriptions.pop(stock_id, None)
    _fugle_quote_cache.pop(stock_id, None)
    await _ws_manager.unsubscribe(stock_id)


class FugleWebSocketManager:
    """
    富果 WebSocket 連線管理器

    使用 fugle-marketdata SDK 的 WebSocket client 接收即時報價
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._ws_client = None
        self._connected = False
        self._reconnect_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self):
        """啟動 WebSocket 連線與背景維護任務"""
        try:
            from fugle_marketdata import WebSocketClient

            self._ws_client = WebSocketClient(api_key=self.api_key)
            stock_ws = self._ws_client.stock
            stock_ws.on("message", self._on_message)
            stock_ws.on("connect", self._on_connect)
            stock_ws.on("disconnect", self._on_disconnect)
            stock_ws.on("error", self._on_error)

            # 在背景執行 WebSocket 連線（connect 是阻塞式的）
            loop = asyncio.get_event_loop()
            loop.run_in_executor(None, stock_ws.connect)

            # 啟動閒置清理任務
            self._cleanup_task = asyncio.create_task(self._idle_cleanup_loop())

            logger.info("[Fugle WS] WebSocket 連線啟動中...")
        except ImportError:
            logger.error("[Fugle WS] fugle-marketdata 套件未安裝，WebSocket 功能不可用")
        except Exception as e:
            logger.error(f"[Fugle WS] 啟動失敗: {e}")

    async def stop(self):
        """關閉 WebSocket 連線"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
        if self._ws_client:
            try:
                self._ws_client.stock.disconnect()
            except Exception:
                pass
        self._connected = False
        logger.info("[Fugle WS] 已關閉連線")

    async def subscribe(self, stock_id: str):
        """訂閱個股即時報價"""
        if not self._connected:
            logger.warning(f"[Fugle WS] 尚未連線，暫存訂閱 {stock_id}")
            return

        try:
            self._ws_client.stock.subscribe({
                "channel": "trades",
                "symbol": stock_id,
            })
            # 同時訂閱 aggregates（含開高低收量等彙總資訊）
            self._ws_client.stock.subscribe({
                "channel": "aggregates",
                "symbol": stock_id,
            })
            logger.info(f"[Fugle WS] 已訂閱 {stock_id}")
        except Exception as e:
            logger.error(f"[Fugle WS] 訂閱 {stock_id} 失敗: {e}")

    async def unsubscribe(self, stock_id: str):
        """取消訂閱"""
        if not self._connected:
            return

        try:
            self._ws_client.stock.unsubscribe({
                "channel": "trades",
                "symbol": stock_id,
            })
            self._ws_client.stock.unsubscribe({
                "channel": "aggregates",
                "symbol": stock_id,
            })
            logger.info(f"[Fugle WS] 已取消訂閱 {stock_id}")
        except Exception as e:
            logger.error(f"[Fugle WS] 取消訂閱 {stock_id} 失敗: {e}")

    def _on_connect(self):
        """WebSocket 連線成功"""
        self._connected = True
        logger.info("[Fugle WS] ✓ 已連線至富果 WebSocket")

        # 重連後重新訂閱所有活躍的股票
        for stock_id in list(_subscriptions.keys()):
            try:
                self._ws_client.stock.subscribe({
                    "channel": "trades",
                    "symbol": stock_id,
                })
                self._ws_client.stock.subscribe({
                    "channel": "aggregates",
                    "symbol": stock_id,
                })
            except Exception as e:
                logger.error(f"[Fugle WS] 重新訂閱 {stock_id} 失敗: {e}")

    def _on_disconnect(self, code=None, message=None):
        """WebSocket 斷線"""
        self._connected = False
        logger.warning(f"[Fugle WS] 連線中斷 (code={code}, msg={message})，將自動重連...")

    def _on_error(self, error):
        """WebSocket 錯誤"""
        logger.error(f"[Fugle WS] 錯誤: {error}")

    def _on_message(self, message):
        """
        處理從富果 WebSocket 收到的訊息

        trades channel 訊息格式：
        {
            "event": "data",
            "channel": "trades",
            "data": {
                "symbol": "2330",
                "price": 590.0,
                "size": 1,
                "time": 1234567890,
                ...
            }
        }

        aggregates channel 訊息格式：
        {
            "event": "data",
            "channel": "aggregates",
            "data": {
                "symbol": "2330",
                "open": 588.0,
                "high": 592.0,
                "low": 587.0,
                "close": 590.0,
                "volume": 12345,
                ...
            }
        }
        """
        try:
            import json

            # 富果推送的訊息可能是 JSON 字串，需要解析
            if isinstance(message, str):
                message = json.loads(message)

            event = message.get("event")
            if event != "data":
                # 記錄非 data 事件以便除錯
                logger.debug(f"[Fugle WS] 非 data 事件: {message}")
                return

            channel = message.get("channel", "")
            data = message.get("data", {})
            symbol = data.get("symbol", "")

            if not symbol:
                return

            # 初始化快取
            if symbol not in _fugle_quote_cache:
                _fugle_quote_cache[symbol] = {
                    "price": 0,
                    "open": 0,
                    "high": 0,
                    "low": 0,
                    "yesterday_close": 0,
                    "volume": 0,
                    "single_volume": 0,
                    "change": 0,
                    "change_pct": 0,
                    "bid": 0,
                    "ask": 0,
                    "time": "--:--:--",
                    "name": "",
                    "is_realtime": True,
                    "source": "fugle",
                    "updated_at": 0,
                }

            cache = _fugle_quote_cache[symbol]

            if channel == "trades":
                # 逐筆成交資料
                price = float(data.get("price", 0))
                size = int(data.get("size", 0))
                # 富果時間欄位可能是 time, tradeTime, at 等
                trade_time = data.get("time") or data.get("tradeTime") or data.get("at") or 0

                if price > 0:
                    cache["price"] = price
                    cache["single_volume"] = size
                    cache["is_realtime"] = True
                    cache["updated_at"] = time.time()

                    # 更新最高/最低
                    if cache["high"] == 0 or price > cache["high"]:
                        cache["high"] = price
                    if cache["low"] == 0 or price < cache["low"]:
                        cache["low"] = price

                    # 計算漲跌
                    yesterday = cache.get("yesterday_close", 0)
                    if yesterday > 0:
                        cache["change"] = round(price - yesterday, 2)
                        cache["change_pct"] = round(
                            (price - yesterday) / yesterday * 100, 2
                        )

                    # 格式化時間
                    if trade_time:
                        from datetime import datetime
                        try:
                            # Fugle 時間格式可能是 epoch ms 或 ISO string
                            if isinstance(trade_time, (int, float)):
                                dt = datetime.fromtimestamp(trade_time / 1000)
                            else:
                                dt = datetime.fromisoformat(str(trade_time))
                            cache["time"] = dt.strftime("%H:%M:%S")
                        except Exception:
                            pass

            elif channel == "aggregates":
                # 彙總資料（開高低收量）
                cache["open"] = float(data.get("open", cache["open"]) or 0)
                cache["high"] = float(data.get("high", cache["high"]) or 0)
                cache["low"] = float(data.get("low", cache["low"]) or 0)
                cache["volume"] = int(data.get("volume", cache["volume"]) or 0)
                cache["updated_at"] = time.time()

                # close 欄位也可以更新 price
                close_price = float(data.get("close", 0) or 0)
                if close_price > 0:
                    cache["price"] = close_price

                # 如果有昨收
                prev_close = data.get("previousClose") or data.get("prevClose") or data.get("referencePrice")
                if prev_close:
                    cache["yesterday_close"] = float(prev_close)
                    # 重算漲跌
                    if cache["price"] > 0 and cache["yesterday_close"] > 0:
                        cache["change"] = round(
                            cache["price"] - cache["yesterday_close"], 2
                        )
                        cache["change_pct"] = round(
                            cache["change"] / cache["yesterday_close"] * 100, 2
                        )
                    # 計算漲跌停價
                    cache["limit_up"] = round(cache["yesterday_close"] * 1.10, 2)
                    cache["limit_down"] = round(cache["yesterday_close"] * 0.90, 2)

            # 通知前端客戶端
            if _client_notify_callback:
                try:
                    _client_notify_callback(symbol, cache.copy())
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"[Fugle WS] 處理訊息失敗: {e}")

    async def _idle_cleanup_loop(self):
        """定期清理閒置訂閱"""
        while True:
            try:
                await asyncio.sleep(60)  # 每 60 秒檢查一次
                now = time.time()
                to_remove = []

                for stock_id, last_access in list(_subscriptions.items()):
                    if now - last_access > IDLE_TIMEOUT:
                        to_remove.append(stock_id)

                for stock_id in to_remove:
                    await self.unsubscribe(stock_id)
                    _subscriptions.pop(stock_id, None)
                    _fugle_quote_cache.pop(stock_id, None)
                    logger.info(f"[Fugle WS] 閒置超時，已退訂 {stock_id}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Fugle WS] 清理任務錯誤: {e}")

    @property
    def is_connected(self) -> bool:
        return self._connected


async def init_fugle_ws():
    """初始化富果 WebSocket 管理器（由 main.py 呼叫）"""
    global _ws_manager

    if not FUGLE_API_KEY:
        logger.warning("[Fugle WS] FUGLE_API_KEY 未設定，WebSocket 功能不啟用")
        return

    _ws_manager = FugleWebSocketManager(api_key=FUGLE_API_KEY)
    await _ws_manager.start()


async def shutdown_fugle_ws():
    """關閉富果 WebSocket（由 main.py 呼叫）"""
    global _ws_manager
    if _ws_manager:
        await _ws_manager.stop()
        _ws_manager = None


def is_fugle_connected() -> bool:
    """檢查富果 WebSocket 是否已連線"""
    return _ws_manager is not None and _ws_manager.is_connected
