"""
盤中即時掃描器（強化版）
每 2 分鐘掃描全市場，推播：
1. 飆股警報（漲>3% + 突破近期高點 + 量能放大）
2. 板塊異動通知（板塊平均漲幅 ≥ 2% 或 ≤ -2%）
3. 關鍵價位突破（突破 MA60 或近期前高）
"""
import asyncio
import os
import time
import discord
from datetime import datetime, timezone, timedelta
from discord.ext import tasks

# 台灣時區
TW_TZ = timezone(timedelta(hours=8))


CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))

# 記錄已推播過的項目（避免重複推播）
_notified_today: set = set()           # 飆股
_notified_sectors_today: set = set()   # 板塊異動
_notified_breakout_today: set = set()  # 關鍵價位突破
_last_reset_date: str = ""


def setup_realtime_scanner(bot):
    """設定盤中即時掃描任務"""

    @tasks.loop(minutes=2)
    async def scan_market():
        """每 2 分鐘掃描市場"""
        global _notified_today, _notified_sectors_today, _notified_breakout_today, _last_reset_date

        now = datetime.now(TW_TZ)

        # 每天重設已通知列表
        today_str = now.strftime("%Y-%m-%d")
        if today_str != _last_reset_date:
            _notified_today = set()
            _notified_sectors_today = set()
            _notified_breakout_today = set()
            _last_reset_date = today_str

        # 只在盤中時間掃描（9:05~13:30）
        hour = now.hour
        minute = now.minute
        if hour < 9 or (hour == 9 and minute < 5):
            return
        if hour > 13 or (hour == 13 and minute >= 30):
            return

        channels = _get_push_channels(bot)
        if not channels:
            return

        # ── 1. 飆股掃描 ──
        try:
            hot_stocks = _scan_for_hot_stocks()
            for stock in hot_stocks:
                if stock["stock_id"] not in _notified_today:
                    _notified_today.add(stock["stock_id"])
                    embed = _build_hot_stock_embed(stock)
                    for channel in channels:
                        try:
                            await channel.send(embed=embed)
                        except Exception:
                            pass
                    print(f"[掃描] 飆股推播：{stock['stock_id']} {stock['name']} +{stock['change_pct']:.1f}%")
                    await asyncio.sleep(1)
        except Exception as e:
            print(f"[掃描] 飆股掃描失敗: {e}")

        # ── 2. 板塊異動掃描 ──
        try:
            sector_alerts = _scan_sector_movement()
            for sector in sector_alerts:
                sector_key = f"{sector['name']}_{sector['direction']}"
                if sector_key not in _notified_sectors_today:
                    _notified_sectors_today.add(sector_key)
                    embed = _build_sector_alert_embed(sector)
                    for channel in channels:
                        try:
                            await channel.send(embed=embed)
                        except Exception:
                            pass
                    print(f"[掃描] 板塊異動：{sector['name']} {sector['direction']} {sector['change_pct']:.1f}%")
                    await asyncio.sleep(1)
        except Exception as e:
            print(f"[掃描] 板塊異動掃描失敗: {e}")

        # ── 3. 關鍵價位突破掃描 ──
        try:
            breakouts = _scan_price_breakout()
            for stock in breakouts:
                breakout_key = f"{stock['stock_id']}_{stock['breakout_type']}"
                if breakout_key not in _notified_breakout_today:
                    _notified_breakout_today.add(breakout_key)
                    embed = _build_breakout_embed(stock)
                    for channel in channels:
                        try:
                            await channel.send(embed=embed)
                        except Exception:
                            pass
                    print(f"[掃描] 價位突破：{stock['stock_id']} {stock['name']} — {stock['breakout_type']}")
                    await asyncio.sleep(1)
        except Exception as e:
            print(f"[掃描] 價位突破掃描失敗: {e}")

    @scan_market.before_loop
    async def before_scan():
        await bot.wait_until_ready()

    scan_market.start()
    return scan_market


# ══════════════════════════════════════════════════════
# 1. 飆股掃描（原有功能）
# ══════════════════════════════════════════════════════

def _scan_for_hot_stocks() -> list[dict]:
    """
    掃描符合飆股條件的個股
    條件：漲幅 > 3% + 突破近期高點 + 量能放大
    """
    from app.services.stock_list import fetch_all_stocks
    from app.services.realtime import fetch_realtime_price
    from app.services.data_fetcher import fetch_stock_price

    hot_stocks = []

    try:
        all_stocks = fetch_all_stocks()
        stocks = [
            {"id": sid, "name": sname}
            for sid, sname in all_stocks.items()
            if len(sid) == 4 and sid.isdigit()
        ][:50]

        for stock in stocks:
            try:
                rt = fetch_realtime_price(stock["id"])
                if rt.get("price", 0) <= 0:
                    continue

                change_pct = rt.get("change_pct", 0)
                if change_pct < 3:
                    continue

                df = fetch_stock_price(stock["id"], days=20)
                if len(df) < 10:
                    continue

                price = rt["price"]
                high_20d = float(df["high"].tail(20).max())

                if price < high_20d * 0.98:
                    continue

                vol_today = rt.get("volume", 0)
                vol_avg = float(df["volume"].tail(20).mean())
                vol_ratio = vol_today / vol_avg if vol_avg > 0 else 0

                if vol_ratio < 1.3:
                    continue

                hot_stocks.append({
                    "stock_id": stock["id"],
                    "name": stock.get("name", stock["id"]),
                    "price": price,
                    "change_pct": change_pct,
                    "vol_ratio": round(vol_ratio, 1),
                    "high_20d": round(high_20d, 2),
                })

            except Exception:
                continue

            time.sleep(0.5)

    except Exception:
        pass

    return hot_stocks


def _build_hot_stock_embed(stock: dict) -> discord.Embed:
    """組裝飆股通知 Embed"""
    embed = discord.Embed(
        title=f"🚀 飆股警報！{stock['stock_id']} {stock['name']}",
        description=f"**漲幅 +{stock['change_pct']:.1f}%** 突破近期高點！",
        color=0xFF4757,
        timestamp=datetime.now(TW_TZ),
    )
    embed.add_field(name="目前價", value=f"{stock['price']:.2f}", inline=True)
    embed.add_field(name="量比", value=f"{stock['vol_ratio']}x", inline=True)
    embed.add_field(name="20日高", value=f"{stock['high_20d']}", inline=True)
    embed.add_field(
        name="觸發條件",
        value="✅ 漲幅 > 3%\n✅ 突破近20日高點\n✅ 量能放大",
        inline=False,
    )
    embed.add_field(
        name="💡 建議",
        value=f"使用 `/stock {stock['stock_id']}` 查看完整分析",
        inline=False,
    )
    embed.set_footer(text="⚠️ 飆股警報僅供參考 | ECF-AI")
    return embed


# ══════════════════════════════════════════════════════
# 2. 板塊異動掃描（新功能）
# ══════════════════════════════════════════════════════

def _scan_sector_movement() -> list[dict]:
    """
    掃描板塊異動
    條件：板塊平均漲幅 ≥ 2% 或 ≤ -2%
    """
    from app.services.sector_flow import fetch_sector_flow

    alerts = []

    try:
        flow_data = fetch_sector_flow()
        sectors = flow_data.get("sectors", [])

        for sector in sectors:
            change_pct = sector.get("change_pct", 0)

            if change_pct >= 2:
                alerts.append({
                    "name": sector["name"],
                    "change_pct": change_pct,
                    "direction": "大漲",
                    "status": sector.get("status", ""),
                    "stock_count": sector.get("stock_count", 0),
                    "top_stocks": sector.get("top_stocks", [])[:3],
                    "flow_amount": sector.get("flow_amount", 0),
                })
            elif change_pct <= -2:
                alerts.append({
                    "name": sector["name"],
                    "change_pct": change_pct,
                    "direction": "大跌",
                    "status": sector.get("status", ""),
                    "stock_count": sector.get("stock_count", 0),
                    "top_stocks": sector.get("top_stocks", [])[:3],
                    "flow_amount": sector.get("flow_amount", 0),
                })

    except Exception as e:
        print(f"[掃描] 板塊異動取得失敗: {e}")

    return alerts


def _build_sector_alert_embed(sector: dict) -> discord.Embed:
    """組裝板塊異動通知 Embed"""
    is_up = sector["direction"] == "大漲"
    color = 0xFF4757 if is_up else 0x00FF88
    emoji = "🔴" if is_up else "🟢"
    arrow = "▲" if is_up else "▼"

    embed = discord.Embed(
        title=f"{emoji} 板塊異動！{sector['name']} {sector['direction']}",
        description=f"**板塊平均漲幅 {arrow}{abs(sector['change_pct']):.2f}%**",
        color=color,
        timestamp=datetime.now(TW_TZ),
    )

    embed.add_field(name="板塊狀態", value=sector["status"], inline=True)
    embed.add_field(name="成分股數", value=f"{sector['stock_count']} 檔", inline=True)
    embed.add_field(name="成交金額", value=f"{sector['flow_amount']:.1f} 億", inline=True)

    # 板塊內領漲/領跌個股
    top_stocks = sector.get("top_stocks", [])
    if top_stocks:
        if is_up:
            stock_text = "\n".join([f"• {s['name']} +{s['change_pct']:.1f}%" for s in top_stocks])
            embed.add_field(name="🏆 領漲個股", value=stock_text, inline=False)
        else:
            stock_text = "\n".join([f"• {s['name']} {s['change_pct']:.1f}%" for s in top_stocks])
            embed.add_field(name="⚠️ 領跌個股", value=stock_text, inline=False)

    embed.set_footer(text="⚠️ 板塊異動僅供參考 | ECF-AI")
    return embed


# ══════════════════════════════════════════════════════
# 3. 關鍵價位突破掃描（新功能）
# ══════════════════════════════════════════════════════

def _scan_price_breakout() -> list[dict]:
    """
    掃描關鍵價位突破
    條件：
    - 突破 MA60（60日均線）
    - 突破近 60 日前高
    且漲幅 > 1%（過濾假突破）
    """
    from app.services.stock_list import fetch_all_stocks
    from app.services.realtime import fetch_realtime_price
    from app.services.data_fetcher import fetch_stock_price

    breakouts = []

    try:
        all_stocks = fetch_all_stocks()
        stocks = [
            {"id": sid, "name": sname}
            for sid, sname in all_stocks.items()
            if len(sid) == 4 and sid.isdigit()
        ][:80]  # 掃描更多股票

        for stock in stocks:
            try:
                rt = fetch_realtime_price(stock["id"])
                if rt.get("price", 0) <= 0:
                    continue

                price = rt["price"]
                change_pct = rt.get("change_pct", 0)

                # 基本過濾：漲幅需 > 1%
                if change_pct < 1:
                    continue

                df = fetch_stock_price(stock["id"], days=80)
                if len(df) < 60:
                    continue

                # 計算 MA60
                ma60 = float(df["close"].tail(60).mean())
                yesterday_close = float(df["close"].iloc[-1])

                # 突破 MA60：昨日收盤在 MA60 以下，今日站上
                if yesterday_close < ma60 and price > ma60:
                    breakouts.append({
                        "stock_id": stock["id"],
                        "name": stock.get("name", stock["id"]),
                        "price": price,
                        "change_pct": change_pct,
                        "breakout_type": "突破MA60",
                        "key_price": round(ma60, 2),
                        "volume": rt.get("volume", 0),
                    })
                    continue  # 一檔只報一種突破

                # 突破近 60 日前高
                high_60d = float(df["high"].tail(60).max())
                if price > high_60d and yesterday_close <= high_60d:
                    breakouts.append({
                        "stock_id": stock["id"],
                        "name": stock.get("name", stock["id"]),
                        "price": price,
                        "change_pct": change_pct,
                        "breakout_type": "突破60日高",
                        "key_price": round(high_60d, 2),
                        "volume": rt.get("volume", 0),
                    })

            except Exception:
                continue

            time.sleep(0.3)

    except Exception:
        pass

    return breakouts


def _build_breakout_embed(stock: dict) -> discord.Embed:
    """組裝關鍵價位突破通知 Embed"""
    embed = discord.Embed(
        title=f"⚡ 關鍵突破！{stock['stock_id']} {stock['name']}",
        description=f"**{stock['breakout_type']}** — 現價 {stock['price']:.2f}（+{stock['change_pct']:.1f}%）",
        color=0xFFD700,
        timestamp=datetime.now(TW_TZ),
    )

    embed.add_field(name="突破類型", value=stock["breakout_type"], inline=True)
    embed.add_field(name="關鍵價位", value=f"{stock['key_price']}", inline=True)
    embed.add_field(name="目前價格", value=f"{stock['price']:.2f}", inline=True)

    # 根據突破類型給建議
    if stock["breakout_type"] == "突破MA60":
        embed.add_field(
            name="📝 意義",
            value="站上 60 日均線為中期趨勢轉多訊號，關注能否守穩",
            inline=False,
        )
    elif stock["breakout_type"] == "突破60日高":
        embed.add_field(
            name="📝 意義",
            value="突破近兩個月高點，多頭強勢格局確立，留意追高風險",
            inline=False,
        )

    embed.add_field(
        name="💡 建議",
        value=f"使用 `/stock {stock['stock_id']}` 查看完整分析",
        inline=False,
    )
    embed.set_footer(text="⚠️ 價位突破僅供參考 | ECF-AI")
    return embed


# ══════════════════════════════════════════════════════
# Helper：取得所有推播頻道
# ══════════════════════════════════════════════════════

def _get_push_channels(bot) -> list:
    """取得所有需要推播的頻道物件"""
    from app.bot.guild_settings import get_all_push_channels

    channel_ids = get_all_push_channels()

    # 加入舊的 env 設定作為 fallback
    if CHANNEL_ID and CHANNEL_ID not in channel_ids:
        channel_ids.append(CHANNEL_ID)

    channels = []
    for cid in channel_ids:
        ch = bot.get_channel(cid)
        if ch:
            channels.append(ch)

    return channels
