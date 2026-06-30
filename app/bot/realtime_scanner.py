"""
盤中飆股即時掃描器
每 2 分鐘掃描全市場，發現符合條件的飆股立即推播到 Discord

條件：漲幅 > 3% + 突破近期高點 + 量能放大
"""
import asyncio
import os
import time
import discord
from datetime import datetime
from discord.ext import tasks


CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))

# 記錄已推播過的股票（避免重複推播）
_notified_today: set = set()
_last_reset_date: str = ""


def setup_realtime_scanner(bot):
    """設定盤中即時掃描任務"""

    @tasks.loop(minutes=2)
    async def scan_market():
        """每 2 分鐘掃描市場"""
        global _notified_today, _last_reset_date

        now = datetime.now()

        # 每天重設已通知列表
        today_str = now.strftime("%Y-%m-%d")
        if today_str != _last_reset_date:
            _notified_today = set()
            _last_reset_date = today_str

        # 只在盤中時間掃描（9:05~13:25）
        hour = now.hour
        minute = now.minute
        if not (9 <= hour < 13 or (hour == 13 and minute <= 25)):
            return
        if hour == 9 and minute < 5:
            return

        if CHANNEL_ID == 0:
            return

        channel = bot.get_channel(CHANNEL_ID)
        if not channel:
            return

        try:
            hot_stocks = _scan_for_hot_stocks()
            for stock in hot_stocks:
                if stock["stock_id"] not in _notified_today:
                    _notified_today.add(stock["stock_id"])
                    embed = _build_hot_stock_embed(stock)
                    await channel.send(embed=embed)
                    print(f"[掃描] 飆股推播：{stock['stock_id']} {stock['name']} +{stock['change_pct']:.1f}%")
                    await asyncio.sleep(1)  # 避免推太快

        except Exception as e:
            print(f"[掃描] 掃描失敗: {e}")

    @scan_market.before_loop
    async def before_scan():
        await bot.wait_until_ready()

    scan_market.start()
    return scan_market


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
        # 取得股票清單（只掃描主要股票避免 API 超量）
        all_stocks = fetch_all_stocks()
        stocks = [s for s in all_stocks if len(s["id"]) == 4 and s["id"].isdigit()][:50]

        for stock in stocks:
            try:
                rt = fetch_realtime_price(stock["id"])
                if rt.get("price", 0) <= 0:
                    continue

                change_pct = rt.get("change_pct", 0)

                # 條件 1：漲幅 > 3%
                if change_pct < 3:
                    continue

                # 條件 2：取得歷史資料判斷是否突破
                df = fetch_stock_price(stock["id"], days=20)
                if len(df) < 10:
                    continue

                price = rt["price"]
                high_20d = float(df["high"].tail(20).max())

                # 條件 2：突破近 20 日高點
                if price < high_20d * 0.98:
                    continue

                # 條件 3：量能放大
                vol_today = rt.get("volume", 0)
                vol_avg = float(df["volume"].tail(20).mean())
                vol_ratio = vol_today / vol_avg if vol_avg > 0 else 0

                if vol_ratio < 1.3:
                    continue

                # 符合所有條件
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

            # 限制每次掃描的 API 呼叫
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
        timestamp=datetime.now(),
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
