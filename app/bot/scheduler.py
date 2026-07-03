"""
Discord Bot 定時推播排程器
- 盤前 8:30：台指期夜盤 + 美股統整 + 5 檔強勢股
- 盤後 14:00：今日總結
- 盤後 14:30：每日 AI 日報（完整市場分析 + AI 展望）
"""
import asyncio
import discord
from datetime import datetime, time as dt_time
from discord.ext import tasks


# 推播頻道 ID
import os
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))

# 防止同一天重複推播
_sent_today: dict[str, str] = {}  # key: "pre"/"after"/"daily", value: "YYYY-MM-DD"


def setup_scheduler(bot):
    """設定定時任務"""

    @tasks.loop(minutes=1)
    async def check_schedule():
        """每分鐘檢查是否到了推播時間"""
        global _sent_today
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        today_str = now.strftime("%Y-%m-%d")

        if current_time == "08:30" and _sent_today.get("pre") != today_str:
            _sent_today["pre"] = today_str
            await send_pre_market_report(bot)
        elif current_time == "14:30" and _sent_today.get("daily") != today_str:
            _sent_today["daily"] = today_str
            await send_daily_ai_report(bot)

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


async def send_daily_ai_report(bot):
    """盤後 14:30 AI 日報推播"""
    if CHANNEL_ID == 0:
        return

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    try:
        from app.bot.daily_report import generate_daily_report

        # 生成完整日報（多個 Embed）
        embeds = await generate_daily_report(bot)

        if not embeds:
            print("[排程] AI 日報生成為空，跳過推播")
            return

        # 先發一個標題 Embed
        header = discord.Embed(
            title="📰 每日 AI 日報",
            description=f"**{datetime.now().strftime('%Y/%m/%d')}（{_weekday_name()}）盤後完整分析**",
            color=0x00D4FF,
            timestamp=datetime.now(),
        )
        header.set_footer(text="ECF-AI v0.3.0 | 以下為今日完整市場分析")
        await channel.send(embed=header)

        # 逐一發送各模組 Embed
        for embed in embeds:
            await channel.send(embed=embed)
            await asyncio.sleep(0.5)

        print(f"[排程] AI 日報已推送 ({datetime.now().strftime('%H:%M:%S')})")

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[排程] AI 日報推送失敗: {e}")


def _weekday_name() -> str:
    """取得中文星期"""
    names = ["一", "二", "三", "四", "五", "六", "日"]
    return f"週{names[datetime.now().weekday()]}"
