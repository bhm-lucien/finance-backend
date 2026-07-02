"""
WebSocket API 端點 — 提供前端即時報價推播

前端連線後傳送訂閱訊息，後端即時推送報價更新
"""
import asyncio
import json
import logging
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.fugle_ws import (
    subscribe_stock,
    unsubscribe_stock,
    get_fugle_quote,
    set_client_notify_callback,
    is_fugle_connected,
)
from app.services.realtime import fetch_realtime_price

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])

# 管理所有已連線的前端客戶端
_connected_clients: dict[WebSocket, Set[str]] = {}


def _notify_clients(symbol: str, quote_data: dict):
    """
    當富果推送新報價時，通知所有訂閱該股票的前端客戶端

    這個函式會被 fugle_ws.py 透過回呼呼叫
    注意：這是從非 async 上下文呼叫的，需要排入 event loop
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_async_notify_clients(symbol, quote_data))
    except RuntimeError:
        pass


async def _async_notify_clients(symbol: str, quote_data: dict):
    """非同步通知所有訂閱該股票的客戶端"""
    message = json.dumps({
        "type": "quote_update",
        "symbol": symbol,
        "data": quote_data,
    }, ensure_ascii=False)

    disconnected = []
    for ws, subscribed_symbols in _connected_clients.items():
        if symbol in subscribed_symbols:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(ws)

    # 清理斷線的客戶端
    for ws in disconnected:
        _connected_clients.pop(ws, None)


# 註冊通知回呼
set_client_notify_callback(_notify_clients)


@router.websocket("/ws/quotes")
async def websocket_quotes(websocket: WebSocket):
    """
    即時報價 WebSocket 端點

    前端可傳送以下訊息：
    - 訂閱：{"action": "subscribe", "symbol": "2330"}
    - 取消訂閱：{"action": "unsubscribe", "symbol": "2330"}
    - 查詢連線狀態：{"action": "status"}

    後端推送：
    - 報價更新：{"type": "quote_update", "symbol": "2330", "data": {...}}
    - 狀態回應：{"type": "status", "connected": true, "source": "fugle"}
    """
    await websocket.accept()
    _connected_clients[websocket] = set()
    logger.info(f"[WS] 前端客戶端已連線，目前共 {len(_connected_clients)} 個連線")

    try:
        while True:
            # 接收前端訊息
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "無效的 JSON 格式",
                }))
                continue

            action = msg.get("action", "")
            symbol = msg.get("symbol", "")

            if action == "subscribe" and symbol:
                # 訂閱股票
                _connected_clients[websocket].add(symbol)
                await subscribe_stock(symbol)

                # 如果已有快取資料，立即推送一次
                quote = get_fugle_quote(symbol)
                if quote:
                    await websocket.send_text(json.dumps({
                        "type": "quote_update",
                        "symbol": symbol,
                        "data": quote,
                    }, ensure_ascii=False))
                else:
                    # 富果沒資料，用 fallback 先給一次
                    fallback = fetch_realtime_price(symbol)
                    if fallback.get("price", 0) > 0:
                        await websocket.send_text(json.dumps({
                            "type": "quote_update",
                            "symbol": symbol,
                            "data": fallback,
                        }, ensure_ascii=False))

                await websocket.send_text(json.dumps({
                    "type": "subscribed",
                    "symbol": symbol,
                }))

            elif action == "unsubscribe" and symbol:
                # 取消訂閱
                _connected_clients[websocket].discard(symbol)

                # 如果沒有其他客戶端訂閱此股票，才真的取消
                other_subscribing = any(
                    symbol in syms
                    for ws, syms in _connected_clients.items()
                    if ws != websocket
                )
                if not other_subscribing:
                    await unsubscribe_stock(symbol)

                await websocket.send_text(json.dumps({
                    "type": "unsubscribed",
                    "symbol": symbol,
                }))

            elif action == "status":
                # 回報連線狀態
                await websocket.send_text(json.dumps({
                    "type": "status",
                    "fugle_connected": is_fugle_connected(),
                    "subscribed_symbols": list(_connected_clients[websocket]),
                    "total_clients": len(_connected_clients),
                }))

            else:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": f"未知動作: {action}",
                }))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"[WS] 客戶端錯誤: {e}")
    finally:
        # 清理
        subscribed = _connected_clients.pop(websocket, set())
        logger.info(f"[WS] 前端客戶端已斷線，剩餘 {len(_connected_clients)} 個連線")

        # 如果沒有其他客戶端訂閱，取消訂閱
        for symbol in subscribed:
            other_subscribing = any(
                symbol in syms for syms in _connected_clients.values()
            )
            if not other_subscribing:
                await unsubscribe_stock(symbol)
