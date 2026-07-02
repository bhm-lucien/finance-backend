"""
SQLite 持久化快取服務

取代純記憶體 dict 快取，優點：
1. 重啟伺服器不遺失資料
2. 可設定過期時間
3. 減少重複的外部 API 呼叫
4. 部署到雲端也能使用
"""
import os
import json
import time
import sqlite3
import threading
from typing import Any, Optional

# 資料庫路徑
DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "cache")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "app_cache.db")

# 執行緒鎖（SQLite 不支援多執行緒同時寫入）
_lock = threading.Lock()

# 連線池（每個執行緒一個連線）
_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """取得當前執行緒的 SQLite 連線"""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH, timeout=10)
        _local.conn.execute("PRAGMA journal_mode=WAL")  # 提升並發效能
        _local.conn.execute("PRAGMA synchronous=NORMAL")
        _init_table(_local.conn)
    return _local.conn


def _init_table(conn: sqlite3.Connection):
    """初始化快取表"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            expires_at REAL NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_expires ON cache(expires_at)")
    conn.commit()


def cache_get(key: str) -> Optional[Any]:
    """
    從快取取得資料

    Args:
        key: 快取鍵值

    Returns:
        資料（自動反序列化），過期或不存在回傳 None
    """
    try:
        conn = _get_conn()
        cursor = conn.execute(
            "SELECT value FROM cache WHERE key = ? AND expires_at > ?",
            (key, time.time())
        )
        row = cursor.fetchone()
        if row:
            return json.loads(row[0])
    except Exception:
        pass
    return None


def cache_set(key: str, value: Any, ttl: int = 3600):
    """
    存入快取

    Args:
        key: 快取鍵值
        value: 資料（自動序列化為 JSON）
        ttl: 過期時間（秒），預設 1 小時
    """
    try:
        with _lock:
            conn = _get_conn()
            now = time.time()
            conn.execute(
                "INSERT OR REPLACE INTO cache (key, value, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (key, json.dumps(value, ensure_ascii=False, default=str), now + ttl, now)
            )
            conn.commit()
    except Exception as e:
        print(f"[Cache] 寫入失敗: {e}")


def cache_delete(key: str):
    """刪除快取"""
    try:
        with _lock:
            conn = _get_conn()
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            conn.commit()
    except Exception:
        pass


def cache_clear_expired():
    """清除所有過期的快取"""
    try:
        with _lock:
            conn = _get_conn()
            conn.execute("DELETE FROM cache WHERE expires_at < ?", (time.time(),))
            conn.commit()
    except Exception:
        pass


def cache_clear_all():
    """清除所有快取"""
    try:
        with _lock:
            conn = _get_conn()
            conn.execute("DELETE FROM cache")
            conn.commit()
    except Exception:
        pass


def cache_stats() -> dict:
    """取得快取統計"""
    try:
        conn = _get_conn()
        total = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
        valid = conn.execute(
            "SELECT COUNT(*) FROM cache WHERE expires_at > ?",
            (time.time(),)
        ).fetchone()[0]
        return {"total_entries": total, "valid_entries": valid, "expired": total - valid}
    except Exception:
        return {"total_entries": 0, "valid_entries": 0, "expired": 0}
