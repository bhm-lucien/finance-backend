"""
財經新聞服務 — 從 Yahoo Finance + Google News RSS 取得即時新聞
"""
import time
import feedparser
import requests
from datetime import datetime

_news_cache: dict[str, dict] = {}
CACHE_TTL = 300  # 5 分鐘快取


def fetch_finance_news(stock_id: str = "", limit: int = 15) -> list:
    """
    取得台股相關財經新聞

    Args:
        stock_id: 股票代碼（如有，會加入該股票的相關新聞）
        limit: 最多回傳幾筆

    Returns:
        list of {"title", "link", "source", "time", "category"}
    """
    cache_key = f"news_{stock_id}"
    if cache_key in _news_cache:
        entry = _news_cache[cache_key]
        if time.time() - entry["time"] < CACHE_TTL:
            return entry["data"]

    all_news = []

    # 1. Yahoo 台股新聞 RSS
    try:
        yahoo_url = "https://tw.stock.yahoo.com/rss?category=tw-market"
        feed = feedparser.parse(yahoo_url)
        for entry in feed.entries[:8]:
            all_news.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "source": "Yahoo奇摩",
                "time": _parse_time(entry.get("published", "")),
                "category": "台股",
            })
    except Exception:
        pass

    # 2. Google News 台股 RSS
    try:
        google_url = "https://news.google.com/rss/search?q=台股+股市&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        feed = feedparser.parse(google_url)
        for entry in feed.entries[:8]:
            all_news.append({
                "title": entry.get("title", "").split(" - ")[0],  # 去掉來源
                "link": entry.get("link", ""),
                "source": _extract_source(entry.get("title", "")),
                "time": _parse_time(entry.get("published", "")),
                "category": "台股",
            })
    except Exception:
        pass

    # 3. 如果有指定個股，搜尋該股票的新聞
    if stock_id:
        try:
            from app.services.stock_list import fetch_all_stocks
            stocks = fetch_all_stocks()
            stock_name = stocks.get(stock_id, stock_id)

            stock_url = f"https://news.google.com/rss/search?q={stock_name}+股票&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
            feed = feedparser.parse(stock_url)
            for entry in feed.entries[:5]:
                all_news.append({
                    "title": entry.get("title", "").split(" - ")[0],
                    "link": entry.get("link", ""),
                    "source": _extract_source(entry.get("title", "")),
                    "time": _parse_time(entry.get("published", "")),
                    "category": stock_name,
                })
        except Exception:
            pass

    # 4. 國際財經新聞
    try:
        intl_url = "https://news.google.com/rss/search?q=美股+fed+半導體&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        feed = feedparser.parse(intl_url)
        for entry in feed.entries[:5]:
            all_news.append({
                "title": entry.get("title", "").split(" - ")[0],
                "link": entry.get("link", ""),
                "source": _extract_source(entry.get("title", "")),
                "time": _parse_time(entry.get("published", "")),
                "category": "國際",
            })
    except Exception:
        pass

    # 5. 經濟日報 RSS
    try:
        udn_feeds = [
            ("https://money.udn.com/rssfeed/news/1001/5588?ch=money", "台股"),
            ("https://money.udn.com/rssfeed/news/1001/5590?ch=money", "國際"),
            ("https://money.udn.com/rssfeed/news/1001/12017?ch=money", "產業"),
        ]
        for feed_url, category in udn_feeds:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:4]:
                all_news.append({
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "source": "經濟日報",
                    "time": _parse_time(entry.get("published", "")),
                    "category": category,
                })
    except Exception:
        pass

    # 6. 工商日報 RSS
    try:
        ctee_feeds = [
            ("https://ctee.com.tw/feed", "財經"),
        ]
        for feed_url, category in ctee_feeds:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:6]:
                title = entry.get("title", "")
                # 只取財經/股市相關
                if any(kw in title for kw in ["股", "台", "半導體", "AI", "營收", "漲", "跌", "法人", "外資", "投信"]):
                    all_news.append({
                        "title": title,
                        "link": entry.get("link", ""),
                        "source": "工商時報",
                        "time": _parse_time(entry.get("published", "")),
                        "category": category,
                    })
    except Exception:
        pass

    # 去重和排序（依時間排序，最新在前）
    seen_titles = set()
    unique_news = []
    for news in all_news:
        short_title = news["title"][:20]
        if short_title not in seen_titles and news["title"]:
            seen_titles.add(short_title)
            unique_news.append(news)

    unique_news.sort(key=lambda x: x.get("time", ""), reverse=True)
    result = unique_news[:limit]

    _news_cache[cache_key] = {"data": result, "time": time.time()}
    return result


def _parse_time(time_str: str) -> str:
    """解析 RSS 時間格式"""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(time_str)
        return dt.strftime("%m/%d %H:%M")
    except Exception:
        return ""


def _extract_source(title: str) -> str:
    """從 Google News 標題提取來源"""
    parts = title.split(" - ")
    return parts[-1].strip() if len(parts) > 1 else "Google News"
