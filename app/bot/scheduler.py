"""
Discord Bot 定時推播排程器
- 盤前 8:30：台指期夜盤 + 美股統整 + 5 檔強勢股
- 盤後 14:00：今日總結 + 明日預測
"""
import asyncio
import discord
from datetime import datetime, time as dt_time
from discord.ext import tasks


# 推播頻道 ID
import os
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))


def setup_scheduler(bot):
    """設定定時任務"""

    @tasks.loop(minutes=1)
    async def check_schedule():
        """每分鐘檢查是否到了推播時間"""
        now = datetime.now()
        current_time = now.strftime("%H:%M")

        if current_time == "08:30":
            await send_pre_market_report(bot)
        elif current_time == "14:00":
            await send_after_market_report(bot)

    @check_schedule.before_loop
    async def before_check():
        await bot.wait_until_ready()

    check_schedule.start()
    return check_schedule


async def send_pre_market_report(bot):
    """盤前 8:30 推播"""
    if CHANNEL_ID == 0:
        return

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    try:
        from app.services.futures import fetch_taiwan_futures
        from app.services.us_market import fetch_us_market_summary
        from app.services.stock_screener import screen_strong_stocks

        # 取得資料
        futures = fetch_taiwan_futures()
        us_market = fetch_us_market_summary()
        strong_stocks = screen_strong_stocks(top_n=5)

        # 組裝 Embed
        embed = discord.Embed(
            title="🌅 盤前分析報告",
            description=f"**{datetime.now().strftime('%Y/%m/%d')} 開盤前分析**",
            color=0x00D4FF,
            timestamp=datetime.now(),
        )

        # 台指期
        if futures["price"] > 0:
            arrow = "▲" if futures["change"] >= 0 else "▼"
            color_emoji = "🔴" if futures["change"] >= 0 else "🟢"
            embed.add_field(
                name="📊 台指期（夜盤）",
                value=f"{color_emoji} **{futures['price']:.0f}** {arrow}{abs(futures['change']):.0f} ({abs(futures['change_pct']):.2f}%)\n盤別：{futures['session']}",
                inline=False,
            )

        # 美股摘要
        if us_market["indices"]:
            us_text = ""
            for idx in us_market["indices"]:
                arrow = "▲" if idx["change_pct"] >= 0 else "▼"
                us_text += f"{idx['name']}：{arrow}{abs(idx['change_pct']):.2f}%\n"
            embed.add_field(
                name="🇺🇸 美股收盤",
                value=us_text,
                inline=True,
            )

        # 科技股重點
        if us_market.get("tech_stocks"):
            tech_text = ""
            for stock in us_market["tech_stocks"][:4]:
                arrow = "▲" if stock["change_pct"] >= 0 else "▼"
                tech_text += f"{stock['name']}：{arrow}{abs(stock['change_pct']):.2f}%\n"
            embed.add_field(
                name="💻 科技股",
                value=tech_text,
                inline=True,
            )

        # 美股結論
        if us_market.get("summary"):
            embed.add_field(
                name="📝 美股結論",
                value=us_market["summary"],
                inline=False,
            )

        # 強勢股
        if strong_stocks:
            stock_text = ""
            for i, s in enumerate(strong_stocks, 1):
                stock_text += f"{i}. **{s['stock_id']} {s['name']}** — {s['price']}（+{s['change_pct']:.1f}%）\n"
                stock_text += f"   └ {' | '.join(s['reasons'][:2])}\n"
            embed.add_field(
                name="🔥 今日強勢股預估",
                value=stock_text,
                inline=False,
            )

        embed.set_footer(text="⚠️ 僅供參考，不構成投資建議 | ECF-AI")

        await channel.send(embed=embed)
        print(f"[排程] 盤前報告已推送 ({datetime.now().strftime('%H:%M:%S')})")

    except Exception as e:
        print(f"[排程] 盤前報告推送失敗: {e}")


async def send_after_market_report(bot):
    """盤後 14:00 推播"""
    if CHANNEL_ID == 0:
        return

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    try:
        from app.services.stock_screener import screen_strong_stocks

        # 今日強勢股（收盤後的實際結果）
        strong_stocks = screen_strong_stocks(top_n=5)

        embed = discord.Embed(
            title="🌆 盤後總結報告",
            description=f"**{datetime.now().strftime('%Y/%m/%d')} 收盤分析**",
            color=0xFFA502,
            timestamp=datetime.now(),
        )

        # 今日表現
        if strong_stocks:
            stock_text = ""
            for i, s in enumerate(strong_stocks, 1):
                stock_text += f"{i}. **{s['stock_id']} {s['name']}** — {s['price']}（+{s['change_pct']:.1f}%）\n"
                stock_text += f"   └ {' | '.join(s['reasons'][:2])}\n"
            embed.add_field(
                name="🏆 今日強勢股",
                value=stock_text,
                inline=False,
            )

        embed.add_field(
            name="🔮 明日展望",
            value="使用 `/stock 代碼` 查詢個股明日預測",
            inline=False,
        )

        embed.set_footer(text="⚠️ 僅供參考，不構成投資建議 | ECF-AI")

        await channel.send(embed=embed)
        print(f"[排程] 盤後報告已推送 ({datetime.now().strftime('%H:%M:%S')})")

    except Exception as e:
        print(f"[排程] 盤後報告推送失敗: {e}")
