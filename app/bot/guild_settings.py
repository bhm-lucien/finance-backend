"""
多伺服器設定管理
儲存各 Discord 伺服器的推播頻道設定
使用 JSON 檔案持久化（簡單方案，適合小規模）
"""
import os
import json
from pathlib import Path


SETTINGS_FILE = Path(os.path.dirname(__file__)).parent.parent / "guild_settings.json"


def _load_settings() -> dict:
    """讀取設定檔"""
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_settings(data: dict):
    """存入設定檔"""
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Guild Settings] 儲存失敗: {e}")


def set_push_channel(guild_id: int, channel_id: int):
    """設定某伺服器的推播頻道"""
    settings = _load_settings()
    settings[str(guild_id)] = {
        "channel_id": channel_id,
        "enabled": True,
    }
    _save_settings(settings)


def remove_push_channel(guild_id: int):
    """移除某伺服器的推播設定"""
    settings = _load_settings()
    if str(guild_id) in settings:
        del settings[str(guild_id)]
        _save_settings(settings)


def get_push_channel(guild_id: int) -> int | None:
    """取得某伺服器的推播頻道 ID"""
    settings = _load_settings()
    entry = settings.get(str(guild_id))
    if entry and entry.get("enabled"):
        return entry.get("channel_id")
    return None


def get_all_push_channels() -> list[int]:
    """取得所有已設定推播的頻道 ID 列表"""
    settings = _load_settings()
    channels = []
    for entry in settings.values():
        if entry.get("enabled") and entry.get("channel_id"):
            channels.append(entry["channel_id"])
    return channels


def get_all_guilds_info() -> list[dict]:
    """取得所有伺服器設定資訊"""
    settings = _load_settings()
    return [
        {"guild_id": int(gid), "channel_id": entry["channel_id"], "enabled": entry.get("enabled", True)}
        for gid, entry in settings.items()
    ]
