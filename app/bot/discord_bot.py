"""
Discord Bot — AI 股票分析助手
提供 /stock 指令查詢個股操盤建議
"""
import os
import asyncio
import discord
from discord import app_commands
from discord.ext import commands


# Bot 設定
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))

# 建立 Bot 實例
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    """Bot 啟動完成"""
    print(f"[Discord Bot] 已登入：{bot.user} (ID: {bot.user.id})")
    print(f"[Discord Bot] 已連接 {len(bot.guilds)} 個伺服器")
    # 同步斜線指令
    try:
        synced = await bot.tree.sync()
        print(f"[Discord Bot] 已同步 {len(synced)} 個斜線指令")
    except Exception as e:
        print(f"[Discord Bot] 指令同步失敗: {e}")


@bot.tree.command(name="stock", description="查詢個股 AI 操盤建議")
@app_commands.describe(stock_id="股票代碼（如 2330）")
async def stock_command(interaction: discord.Interaction, stock_id: str):
    """
    /stock 指令 — 查詢個股 AI 操盤建議
    """
    await interaction.response.defer(thinking=True)

    try:
        # 呼叫分析函式
        from app.indicators.trading_advice import generate_trading_advice
        from app.services.realtime import fetch_realtime_price
        from app.indicators.kline_pattern import analyze_kline_patterns

        # 取得即時報價
        rt = fetch_realtime_price(stock_id)
        price = rt.get("price", 0)
        change = rt.get("change", 0)
        change_pct = rt.get("change_pct", 0)
        name = rt.get("name", stock_id)

        # 取得 AI 操盤建議
        advice = generate_trading_advice(stock_id)
        if advice.get("error"):
            await interaction.followup.send(f"❌ 無法分析 {stock_id}：{advice['error']}")
            return

        # 取得 K 線型態
        kline = analyze_kline_patterns(stock_id)

        # 組裝 Embed 訊息
        embed = _build_stock_embed(stock_id, name, price, change, change_pct, advice, kline)
        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"❌ 分析 {stock_id} 時發生錯誤：{str(e)[:200]}")


@bot.tree.command(name="help", description="顯示 Bot 使用說明")
async def help_command(interaction: discord.Interaction):
    """顯示使用說明"""
    embed = discord.Embed(
        title="📊 AI 股票分析助手",
        description="提供台股即時分析和操盤建議",
        color=0x00D4FF,
    )
    embed.add_field(
        name="指令列表",
        value=(
            "`/stock 2330` — 查詢個股 AI 操盤建議\n"
            "`/help` — 顯示此說明"
        ),
        inline=False,
    )
    embed.set_footer(text="ECF-AI SYSTEM v0.1.0")
    await interaction.response.send_message(embed=embed)


def _build_stock_embed(stock_id: str, name: str, price: float, change: float, change_pct: float, advice: dict, kline: dict) -> discord.Embed:
    """組裝個股分析 Embed"""
    # 漲跌顏色
    color = 0xFF4757 if change >= 0 else 0x00FF88
    arrow = "▲" if change >= 0 else "▼"

    embed = discord.Embed(
        title=f"📈 {stock_id} {name}",
        description=f"**{price:.2f}** {arrow} {abs(change):.2f} ({abs(change_pct):.2f}%)",
        color=color,
    )

    # AI 結論
    strategy = advice.get("best_strategy", {})
    embed.add_field(
        name="🎯 最佳策略",
        value=f"**{strategy.get('strategy', '--')}**\n{strategy.get('logic', '')[:100]}",
        inline=False,
    )

    # 買賣區間
    buy_zone = advice.get("buy_zone", {})
    sell_zone = advice.get("sell_zone", {})
    stop_loss = advice.get("stop_loss", 0)

    embed.add_field(
        name="📗 波段買進",
        value=f"理想：{buy_zone.get('ideal', '--')}\n支撐：{buy_zone.get('support_1', '--')}\n停損：{stop_loss}",
        inline=True,
    )
    embed.add_field(
        name="📕 波段賣出",
        value=f"壓力：{sell_zone.get('resistance', '--')}\n停利：{sell_zone.get('take_profit', '--')}",
        inline=True,
    )

    # 當沖區間
    day_trade = advice.get("day_trade_zone", {})
    if day_trade:
        embed.add_field(
            name="⚡ 當沖",
            value=f"做多：{day_trade.get('buy_entry', '--')} → {day_trade.get('buy_target', '--')}\n做空：{day_trade.get('sell_entry', '--')} → {day_trade.get('sell_target', '--')}",
            inline=False,
        )

    # 風報比
    rr = advice.get("risk_reward", {})
    embed.add_field(
        name="📊 風報比",
        value=f"{rr.get('buy_rr', '--')} ({rr.get('rating', '--')})",
        inline=True,
    )

    # K 線型態
    kline_summary = kline.get("summary", "")
    if kline_summary:
        embed.add_field(
            name="🕯️ K線型態",
            value=kline_summary[:100],
            inline=False,
        )

    # 預測
    predictions = advice.get("predictions", {})
    if predictions:
        pre = predictions.get("pre_market", {})
        intra = predictions.get("intraday", {})
        after = predictions.get("after_market", {})
        embed.add_field(
            name="🔮 預測",
            value=f"盤前：{pre.get('direction', '--')} | 收盤：{intra.get('est_close', '--')} | 明日：{after.get('tomorrow_direction', '--')}",
            inline=False,
        )

    embed.set_footer(text="⚠️ 僅供參考，不構成投資建議 | ECF-AI")
    return embed


async def start_bot():
    """啟動 Discord Bot（在背景執行）"""
    if not DISCORD_TOKEN:
        print("[Discord Bot] 未設定 DISCORD_TOKEN，跳過啟動")
        return

    try:
        await bot.start(DISCORD_TOKEN)
    except Exception as e:
        print(f"[Discord Bot] 啟動失敗: {e}")
