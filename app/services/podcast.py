"""
Podcast 資料服務
取得游庭皓、股癌等財經 Podcast 的最新集數列表
"""
import time
import feedparser

_podcast_cache: dict[str, dict] = {}
CACHE_TTL = 1800  # 30 分鐘快取

# Podcast RSS 來源
PODCASTS = {
    "gooaye": {
        "name": "股癌 Gooaye",
        "rss": "https://feeds.soundon.fm/podcasts/5d10cece-e6f6-4f65-ac2e-6a2e45c0d2f0.xml",
        "apple_id": "1500839292",
        "notes_base_url": "https://www.jacksu.tw/tool/stock/gooaye-notes",
        "podsight_base_url": None,
    },
    "yuting": {
        "name": "游庭皓的財經皓角",
        "rss": "https://feed.firstory.me/rss/user/ckr4cf1qn2u370870h02o73vu",
        "apple_id": "1488295306",
        "notes_base_url": None,
        "podsight_base_url": "https://podsight.tw/yutinghao",
    },
}


def fetch_podcast_episodes(podcast_id: str = "all", limit: int = 20) -> dict:
    """
    取得 Podcast 集數列表

    Args:
        podcast_id: "gooaye" / "yuting" / "all"
        limit: 每個 Podcast 最多幾集

    Returns:
        {"podcasts": [{"id", "name", "apple_id", "episodes": [...]}]}
    """
    cache_key = f"podcast_{podcast_id}_{limit}"
    if cache_key in _podcast_cache:
        entry = _podcast_cache[cache_key]
        if time.time() - entry["time"] < CACHE_TTL:
            return entry["data"]

    results = []

    targets = PODCASTS if podcast_id == "all" else {podcast_id: PODCASTS.get(podcast_id)}

    for pid, info in targets.items():
        if not info:
            continue

        episodes = []
        try:
            feed = feedparser.parse(info["rss"])
            for entry in feed.entries[:limit]:
                episodes.append({
                    "title": entry.get("title", ""),
                    "date": _parse_date(entry.get("published", "")),
                    "duration": _get_duration(entry),
                    "link": entry.get("link", ""),
                    "description": (entry.get("summary", "") or "")[:200],
                })
        except Exception as e:
            print(f"[Podcast] {pid} RSS 取得失敗: {e}")

        results.append({
            "id": pid,
            "name": info["name"],
            "apple_id": info["apple_id"],
            "notes_base_url": info.get("notes_base_url"),
            "podsight_base_url": info.get("podsight_base_url"),
            "episodes": episodes,
        })

    data = {"podcasts": results}
    _podcast_cache[cache_key] = {"data": data, "time": time.time()}
    return data


def _parse_date(date_str: str) -> str:
    """解析 RSS 日期"""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


def _get_duration(entry) -> str:
    """取得集數時長"""
    # iTunes duration tag
    duration = entry.get("itunes_duration", "")
    if duration:
        return duration
    return ""
