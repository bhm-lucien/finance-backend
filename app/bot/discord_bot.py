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


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """全域指令錯誤處理"""
    import traceback
    print(f"[Discord Bot] 指令錯誤: {error}")
    traceback.print_exception(type(error), error, error.__traceback__)
    # 嘗試回覆錯誤，失敗就靜默
    try:
        if interaction.response.is_done():
            await interaction.followup.send(f"❌ {str(error)[:200]}", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ {str(error)[:200]}", ephemeral=True)
    except Exception:
        pass


@bot.event
async def on_ready():
    """Bot 啟動完成"""
    print(f"[Discord Bot] 已登入：{bot.user} (ID: {bot.user.id})")
    print(f"[Discord Bot] 已連接 {len(bot.guilds)} 個伺服器")
    print(f"[Discord Bot] 已註冊的指令: {[cmd.name for cmd in bot.tree.get_commands()]}")
    # 全域同步斜線指令（所有伺服器都能用）
    try:
        synced = await bot.tree.sync()
        print(f"[Discord Bot] 已全域同步 {len(synced)} 個斜線指令")
    except Exception as e:
        print(f"[Discord Bot] 指令同步失敗: {e}")

    # 啟動定時排程和盤中掃描
    try:
        from app.bot.scheduler import setup_scheduler
        from app.bot.realtime_scanner import setup_realtime_scanner
        setup_scheduler(bot)
        setup_realtime_scanner(bot)
        print("[Discord Bot] 定時排程和盤中掃描已啟動")
    except Exception as e:
        print(f"[Discord Bot] 排程啟動失敗: {e}")


@bot.tree.command(name="stock", description="查詢個股 AI 操盤建議")
@app_commands.describe(stock_id="股票代碼或名稱（如 2330 或 台積電）")
async def stock_command(interaction: discord.Interaction, stock_id: str):
    """
    /stock 指令 — 查詢個股 AI 操盤建議
    支援代碼（2330）或名稱（台積電）
    """
    await interaction.response.defer(thinking=True)

    try:
        # 如果輸入的不是純數字，嘗試用名稱查找代碼
        actual_id = stock_id.strip()
        if not actual_id.isdigit():
            actual_id = _find_stock_id_by_name(actual_id)
            if not actual_id:
                await interaction.followup.send(f"❌ 找不到「{stock_id}」對應的股票，請確認名稱或直接輸入代碼")
                return

        # 呼叫分析函式
        from app.indicators.trading_advice import generate_trading_advice
        from app.services.realtime import fetch_realtime_price
        from app.indicators.kline_pattern import analyze_kline_patterns

        # 取得即時報價
        rt = fetch_realtime_price(actual_id)
        price = rt.get("price", 0)
        change = rt.get("change", 0)
        change_pct = rt.get("change_pct", 0)
        name = rt.get("name", actual_id)

        # 取得 AI 操盤建議
        advice = generate_trading_advice(actual_id)
        if advice.get("error"):
            await interaction.followup.send(f"❌ 無法分析 {actual_id}：{advice['error']}")
            return

        # 取得 K 線型態
        kline = analyze_kline_patterns(actual_id)

        # 組裝 Embed 訊息
        embed = _build_stock_embed(actual_id, name, price, change, change_pct, advice, kline)
        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"❌ 分析 {stock_id} 時發生錯誤：{str(e)[:200]}")


@bot.tree.command(name="setup", description="設定目前頻道為推播頻道（管理者限定）")
async def setup_command(interaction: discord.Interaction):
    """設定推播頻道"""
    # 權限檢查：只有管理者能設定
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("❌ 只有伺服器管理者才能設定推播頻道", ephemeral=True)
        return

    from app.bot.guild_settings import set_push_channel
    set_push_channel(interaction.guild_id, interaction.channel_id)

    await interaction.response.send_message(
        f"✅ 已將 **#{interaction.channel.name}** 設為推播頻道！\n"
        f"之後的盤前報告、AI 日報、盤中掃描都會推送到這裡。",
        ephemeral=False,
    )


@bot.tree.command(name="unsetup", description="取消本伺服器的推播設定（管理者限定）")
async def unsetup_command(interaction: discord.Interaction):
    """取消推播設定"""
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("❌ 只有伺服器管理者才能操作", ephemeral=True)
        return

    from app.bot.guild_settings import remove_push_channel
    remove_push_channel(interaction.guild_id)

    await interaction.response.send_message("✅ 已取消本伺服器的推播設定", ephemeral=False)


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
            "`/top` — 今日全市場強勢股 TOP 5\n"
            "`/strong_industry 半導體` — 特定產業強勢股\n"
            "`/market` — 美股 + 台指期 + 費半前三\n"
            "`/setup` — 設定本頻道為推播頻道\n"
            "`/unsetup` — 取消推播設定\n"
            "`/help` — 顯示此說明"
        ),
        inline=False,
    )
    embed.add_field(
        name="自動推播",
        value=(
            "🌅 每日 8:30 — 盤前分析（夜盤 + 美股 + 強勢股）\n"
            "🚀 盤中即時 — 飆股警報（漲>3% + 突破 + 量增）\n"
            "⚡ 盤中即時 — 關鍵價位突破（MA60 / 60日新高）\n"
            "🔴 盤中即時 — 板塊異動（板塊漲跌 ≥ 2%）\n"
            "🌆 每日 14:00 — 盤後總結\n"
            "📰 每日 14:30 — AI 日報（完整市場分析 + 明日展望）"
        ),
        inline=False,
    )
    embed.set_footer(text="ECF-AI SYSTEM v0.2.0")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="top", description="篩選今日全市場強勢股 TOP 5")
async def top_command(interaction: discord.Interaction):
    """篩選全市場強勢股"""
    print("[Discord /strong] 指令觸發！")
    
    try:
        await interaction.response.defer(thinking=True)
    except Exception:
        pass

    try:
        from app.services.stock_screener import screen_strong_stocks
        stocks = screen_strong_stocks(top_n=5, industry="")

        if not stocks:
            await interaction.followup.send("❌ 目前沒有符合條件的強勢股")
            return

        title = "🔥 今日強勢股 TOP 5"
        embed = discord.Embed(title=title, color=0xFF4757)

        for i, s in enumerate(stocks, 1):
            embed.add_field(
                name=f"{i}. {s['stock_id']} {s['name']} — {s['price']}（+{s['change_pct']:.1f}%）",
                value=f"評分：{s['score']}/100 | {' | '.join(s['reasons'][:3])}",
                inline=False,
            )

        embed.set_footer(text="⚠️ 僅供參考 | ECF-AI")
        await interaction.followup.send(embed=embed)

    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            await interaction.followup.send(f"❌ 篩選失敗：{str(e)[:200]}")
        except Exception:
            pass


@bot.tree.command(name="strong_industry", description="篩選特定產業強勢股")
@app_commands.describe(industry="產業名稱（如：半導體、金融、航運）")
async def strong_industry_command(interaction: discord.Interaction, industry: str):
    """篩選特定產業強勢股"""
    await interaction.response.defer(thinking=True)

    try:
        from app.services.stock_screener import screen_strong_stocks
        stocks = screen_strong_stocks(top_n=5, industry=industry)

        if not stocks:
            await interaction.followup.send(f"❌ 目前「{industry}」沒有符合條件的強勢股")
            return

        title = f"🔥 強勢股篩選 — {industry}"
        embed = discord.Embed(title=title, color=0xFF4757)

        for i, s in enumerate(stocks, 1):
            embed.add_field(
                name=f"{i}. {s['stock_id']} {s['name']} — {s['price']}（+{s['change_pct']:.1f}%）",
                value=f"評分：{s['score']}/100 | {' | '.join(s['reasons'][:3])}",
                inline=False,
            )

        embed.set_footer(text="⚠️ 僅供參考 | ECF-AI")
        await interaction.followup.send(embed=embed)

    except Exception as e:
        import traceback
        print(f"[Discord /strong_industry] 完整錯誤:")
        traceback.print_exc()
        await interaction.followup.send(f"❌ 篩選失敗：{str(e)[:200]}")


@bot.tree.command(name="market", description="查詢美股 + 台指期最新資訊")
async def market_command(interaction: discord.Interaction):
    """查詢市場資訊"""
    await interaction.response.defer(thinking=True)

    try:
        from app.services.futures import fetch_taiwan_futures
        from app.services.us_market import fetch_us_market_summary

        futures = fetch_taiwan_futures()
        us_market = fetch_us_market_summary()

        embed = discord.Embed(title="🌐 全球市場概況", color=0x00D4FF)

        # 台指期
        if futures["price"] > 0:
            arrow = "▲" if futures["change"] >= 0 else "▼"
            embed.add_field(
                name="📊 台指期",
                value=f"**{futures['price']:,.0f}** {arrow}{abs(futures['change']):,.0f} ({abs(futures['change_pct']):.2f}%)\n高：{futures['high']:,.0f} ｜ 低：{futures['low']:,.0f}\n盤別：{futures['session']}",
                inline=False,
            )
        else:
            embed.add_field(
                name="📊 台指期",
                value="⚠️ 暫時無法取得資料",
                inline=False,
            )

        # 美股指數（含實際數字）
        if us_market["indices"]:
            us_text = ""
            for idx in us_market["indices"]:
                arrow = "▲" if idx["change_pct"] >= 0 else "▼"
                sign = "+" if idx["change"] >= 0 else ""
                us_text += f"**{idx['name']}**：{idx['price']:,.0f} {arrow}{sign}{idx['change']:,.0f} ({sign}{idx['change_pct']:.2f}%)\n"
            embed.add_field(name="🇺🇸 美股指數", value=us_text, inline=False)

        # 費半成分股漲幅前三名
        sox_top3 = us_market.get("sox_top3", [])
        if sox_top3:
            sox_text = ""
            for i, s in enumerate(sox_top3, 1):
                arrow = "▲" if s["change_pct"] >= 0 else "▼"
                sign = "+" if s["change"] >= 0 else ""
                sox_text += f"{i}. **{s['name']}**（{s['symbol']}）：${s['price']:.1f} {arrow}{sign}{s['change']:.1f} ({sign}{s['change_pct']:.2f}%)\n"
            embed.add_field(name="🔥 費半漲幅前三", value=sox_text, inline=False)

        # 科技股重點
        if us_market.get("tech_stocks"):
            tech_text = ""
            for stock in us_market["tech_stocks"][:6]:
                arrow = "▲" if stock["change_pct"] >= 0 else "▼"
                sign = "+" if stock["change"] >= 0 else ""
                tech_text += f"{stock['name']}：${stock['price']:.1f} {arrow}{sign}{stock['change_pct']:.2f}%\n"
            embed.add_field(name="💻 科技股", value=tech_text, inline=False)

        # 摘要
        if us_market.get("summary"):
            embed.add_field(name="📝 摘要", value=us_market["summary"], inline=False)

        embed.set_footer(text=f"更新：{us_market.get('update_time', '--')} | ECF-AI")
        await interaction.followup.send(embed=embed)

    except Exception as e:
        import traceback
        traceback.print_exc()
        await interaction.followup.send(f"❌ 取得市場資料失敗：{str(e)[:200]}")


def _find_stock_id_by_name(name: str) -> str | None:
    """用股票名稱查找代碼"""
    try:
        from app.services.stock_list import fetch_all_stocks
        stocks = fetch_all_stocks()  # 回傳 {stock_id: stock_name} dict

        # 精確匹配
        for sid, sname in stocks.items():
            if sname == name:
                return sid

        # 部分匹配（名稱包含輸入）
        for sid, sname in stocks.items():
            if name in sname:
                return sid

        # 反向部分匹配（輸入包含名稱）
        for sid, sname in stocks.items():
            if sname in name and len(sname) >= 2:
                return sid

    except Exception:
        pass
    return None


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


@bot.tree.command(name="test_push", description="測試推播功能是否正常")
async def test_push_command(interaction: discord.Interaction):
    """手動測試推播"""
    await interaction.response.defer(thinking=True)

    channel_id = DISCORD_CHANNEL_ID
    channel = bot.get_channel(channel_id)

    if not channel:
        await interaction.followup.send(f"❌ 找不到頻道 ID: {channel_id}")
        return

    from datetime import datetime
    embed = discord.Embed(
        title="🧪 推播測試成功！",
        description="如果你看到這則訊息，代表定時推播功能正常運作。",
        color=0x00D4FF,
        timestamp=datetime.now(),
    )
    embed.add_field(name="頻道", value=f"#{channel.name}", inline=True)
    embed.add_field(name="頻道 ID", value=str(channel_id), inline=True)
    embed.set_footer(text="ECF-AI v0.2.0")

    await channel.send(embed=embed)
    await interaction.followup.send(f"✅ 已成功推播到 #{channel.name}！")


async def start_bot():
    """啟動 Discord Bot（在背景執行）"""
    if not DISCORD_TOKEN:
        print("[Discord Bot] 未設定 DISCORD_TOKEN，跳過啟動")
        return

    try:
        # discord.py 2.4+ 需要在 start 之前確保沒有殘留的 session
        if bot.is_closed():
            # 如果 bot 已經被關閉過，需要重新建立
            pass
        await bot.start(DISCORD_TOKEN)
    except discord.LoginFailure as e:
        print(f"[Discord Bot] 登入失敗（Token 無效？）: {e}")
    except discord.PrivilegedIntentsRequired as e:
        print(f"[Discord Bot] 缺少必要的 Intents 權限: {e}")
    except Exception as e:
        print(f"[Discord Bot] 啟動失敗: {type(e).__name__}: {e}")
