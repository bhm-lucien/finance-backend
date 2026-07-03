"""
每日 AI 日報生成模組
盤後 14:30 推播完整市場日報

內容包含：
1. 大盤總結（今日漲跌、成交量變化）
2. 板塊輪動分析（資金流入/流出板塊）
3. 強弱股表現排行
4. 籌碼面重點（外資/投信動向）
5. 明日展望預測（由 OpenAI 生成）
"""
import os
import discord
from datetime import datetime
from openai import OpenAI


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


def _get_openai_client() -> OpenAI | None:
    """取得 OpenAI 客戶端"""
    if not OPENAI_API_KEY:
        print("[AI 日報] 未設定 OPENAI_API_KEY，跳過 AI 生成")
        return None
    return OpenAI(api_key=OPENAI_API_KEY)


async def generate_daily_report(bot) -> list[discord.Embed]:
    """
    生成每日 AI 日報的所有 Embed

    Returns:
        list[discord.Embed] — 多個 Embed 組成完整日報
    """
    embeds = []
    market_data = {}

    # ── 1. 大盤總結 ──
    try:
        taiex_embed, taiex_summary = _build_market_summary()
        embeds.append(taiex_embed)
        market_data["market"] = taiex_summary
    except Exception as e:
        print(f"[AI 日報] 大盤總結失敗: {e}")

    # ── 2. 板塊輪動分析 ──
    try:
        sector_embed, sector_summary = _build_sector_analysis()
        embeds.append(sector_embed)
        market_data["sectors"] = sector_summary
    except Exception as e:
        print(f"[AI 日報] 板塊分析失敗: {e}")

    # ── 3. 強弱股排行 ──
    try:
        stock_embed, stock_summary = _build_strong_weak_stocks()
        embeds.append(stock_embed)
        market_data["stocks"] = stock_summary
    except Exception as e:
        print(f"[AI 日報] 強弱股排行失敗: {e}")

    # ── 4. 籌碼面重點 ──
    try:
        chip_embed, chip_summary = _build_chip_summary()
        embeds.append(chip_embed)
        market_data["chips"] = chip_summary
    except Exception as e:
        print(f"[AI 日報] 籌碼分析失敗: {e}")

    # ── 5. AI 明日展望 ──
    try:
        outlook_embed = await _build_ai_outlook(market_data)
        embeds.append(outlook_embed)
    except Exception as e:
        print(f"[AI 日報] AI 展望生成失敗: {e}")

    return embeds


def _build_market_summary() -> tuple[discord.Embed, str]:
    """大盤總結"""
    from app.services.market_index import fetch_market_indices
    from app.services.futures import fetch_taiwan_futures

    indices = fetch_market_indices()
    futures = fetch_taiwan_futures()

    embed = discord.Embed(
        title="📊 大盤總結",
        color=0x00D4FF,
        timestamp=datetime.now(),
    )

    summary_text = ""

    # 加權指數
    taiex = next((i for i in indices if i["key"] == "taiex_futures"), None)
    if taiex and taiex["price"] > 0:
        arrow = "▲" if taiex["change"] >= 0 else "▼"
        color_emoji = "🔴" if taiex["change"] >= 0 else "🟢"
        embed.add_field(
            name="🇹🇼 加權指數",
            value=f"{color_emoji} **{taiex['price']:,.0f}** {arrow}{abs(taiex['change']):,.0f} ({abs(taiex['change_pct']):.2f}%)",
            inline=True,
        )
        summary_text += f"加權指數 {taiex['price']:,.0f} {arrow}{abs(taiex['change_pct']):.2f}%。"

    # 台指期
    if futures["price"] > 0:
        arrow = "▲" if futures["change"] >= 0 else "▼"
        embed.add_field(
            name="📈 台指期",
            value=f"**{futures['price']:,.0f}** {arrow}{abs(futures['change']):,.0f} ({abs(futures['change_pct']):.2f}%)",
            inline=True,
        )
        summary_text += f"台指期 {futures['price']:,.0f} {arrow}{abs(futures['change_pct']):.2f}%。"

    # 美股（前一日收盤）
    us_indices = [i for i in indices if i["key"] in ("dow_jones", "sp500", "nasdaq", "sox")]
    if us_indices:
        us_text = ""
        for idx in us_indices:
            if idx["price"] > 0:
                arrow = "▲" if idx["change_pct"] >= 0 else "▼"
                us_text += f"**{idx['name']}** {idx['price']:,.0f} {arrow}{abs(idx['change_pct']):.2f}%\n"
                summary_text += f"{idx['name']} {arrow}{abs(idx['change_pct']):.2f}%。"
        if us_text:
            embed.add_field(name="🇺🇸 美股概況", value=us_text, inline=False)

    embed.set_footer(text="ECF-AI 每日日報")
    return embed, summary_text


def _build_sector_analysis() -> tuple[discord.Embed, str]:
    """板塊輪動分析"""
    from app.services.sector_flow import fetch_sector_flow

    flow_data = fetch_sector_flow()
    sectors = flow_data.get("sectors", [])
    summary = flow_data.get("summary", {})

    embed = discord.Embed(
        title="🏭 板塊輪動分析",
        color=0xFFA502,
    )

    summary_text = ""

    # 統計
    rising = summary.get("rising", 0)
    falling = summary.get("falling", 0)
    embed.add_field(
        name="📈 市場氛圍",
        value=f"漲潮：{rising} 板塊 | 退潮：{falling} 板塊 | 輪動：{summary.get('rotating', 0)} | 觀望：{summary.get('watching', 0)}",
        inline=False,
    )
    summary_text += f"漲潮板塊{rising}個，退潮板塊{falling}個。"

    # 漲最多的板塊（前 3）
    top_sectors = [s for s in sectors if s["change_pct"] > 0][:3]
    if top_sectors:
        top_text = ""
        for s in top_sectors:
            top_stocks_str = ", ".join([f"{st['name']}+{st['change_pct']:.1f}%" for st in s["top_stocks"][:2]])
            top_text += f"**{s['name']}** +{s['change_pct']:.2f}%（{top_stocks_str}）\n"
            summary_text += f"強勢板塊：{s['name']}+{s['change_pct']:.2f}%。"
        embed.add_field(name="🔥 資金流入板塊", value=top_text, inline=False)

    # 跌最多的板塊（後 3）
    bottom_sectors = [s for s in sectors if s["change_pct"] < 0][-3:]
    bottom_sectors.reverse()
    if bottom_sectors:
        bottom_text = ""
        for s in bottom_sectors:
            bottom_text += f"**{s['name']}** {s['change_pct']:.2f}%\n"
            summary_text += f"弱勢板塊：{s['name']}{s['change_pct']:.2f}%。"
        embed.add_field(name="💧 資金流出板塊", value=bottom_text, inline=False)

    return embed, summary_text


def _build_strong_weak_stocks() -> tuple[discord.Embed, str]:
    """強弱股排行"""
    from app.services.stock_screener import screen_strong_stocks

    embed = discord.Embed(
        title="💪 強弱股排行",
        color=0xFF4757,
    )

    summary_text = ""

    # 強勢股 TOP 5
    strong = screen_strong_stocks(top_n=5)
    if strong:
        strong_text = ""
        for i, s in enumerate(strong, 1):
            strong_text += f"{i}. **{s['stock_id']} {s['name']}** {s['price']}（+{s['change_pct']:.1f}%）\n"
            strong_text += f"   └ {' | '.join(s['reasons'][:2])}\n"
            summary_text += f"強勢股：{s['stock_id']}{s['name']}+{s['change_pct']:.1f}%。"
        embed.add_field(name="🏆 今日強勢 TOP 5", value=strong_text, inline=False)
    else:
        embed.add_field(name="🏆 今日強勢", value="今日無明顯強勢股", inline=False)

    return embed, summary_text


def _build_chip_summary() -> tuple[discord.Embed, str]:
    """籌碼面重點"""
    from app.services.data_fetcher import fetch_institutional_investors
    from app.services.stock_screener import screen_strong_stocks

    embed = discord.Embed(
        title="🏦 籌碼面重點",
        color=0x7B68EE,
    )

    summary_text = ""

    # 取得強勢股的法人動態作為代表
    strong = screen_strong_stocks(top_n=5)
    chip_info = []

    for s in strong[:5]:
        try:
            inst_df = fetch_institutional_investors(s["stock_id"], days=5)
            if inst_df.empty:
                continue

            # 計算近 5 日各法人淨買賣
            foreign_buy = 0
            trust_buy = 0
            if "name" in inst_df.columns and "buy" in inst_df.columns and "sell" in inst_df.columns:
                foreign = inst_df[inst_df["name"].str.contains("外資", na=False)]
                trust = inst_df[inst_df["name"].str.contains("投信", na=False)]
                if not foreign.empty:
                    foreign_buy = int(foreign["buy"].sum() - foreign["sell"].sum())
                if not trust.empty:
                    trust_buy = int(trust["buy"].sum() - trust["sell"].sum())

            chip_info.append({
                "stock_id": s["stock_id"],
                "name": s["name"],
                "foreign": foreign_buy,
                "trust": trust_buy,
            })
        except Exception:
            continue

    if chip_info:
        chip_text = ""
        for c in chip_info:
            f_arrow = "買" if c["foreign"] > 0 else "賣"
            t_arrow = "買" if c["trust"] > 0 else "賣"
            chip_text += f"**{c['stock_id']} {c['name']}** — 外資{f_arrow}{abs(c['foreign']):,}張 | 投信{t_arrow}{abs(c['trust']):,}張\n"
            summary_text += f"{c['stock_id']}外資{f_arrow}{abs(c['foreign'])}張、投信{t_arrow}{abs(c['trust'])}張。"
        embed.add_field(name="📋 強勢股法人動態（近5日）", value=chip_text, inline=False)
    else:
        embed.add_field(name="📋 法人動態", value="今日無明顯法人動態資料", inline=False)

    return embed, summary_text


async def _build_ai_outlook(market_data: dict) -> discord.Embed:
    """用 OpenAI 生成 AI 明日展望"""
    embed = discord.Embed(
        title="🔮 AI 明日展望",
        color=0x00FF88,
    )

    # 組裝 prompt
    data_text = ""
    if market_data.get("market"):
        data_text += f"大盤狀況：{market_data['market']}\n"
    if market_data.get("sectors"):
        data_text += f"板塊輪動：{market_data['sectors']}\n"
    if market_data.get("stocks"):
        data_text += f"強弱股：{market_data['stocks']}\n"
    if market_data.get("chips"):
        data_text += f"籌碼面：{market_data['chips']}\n"

    if not data_text:
        embed.description = "今日資料不足，無法生成展望"
        return embed

    # 呼叫 OpenAI
    client = _get_openai_client()
    if not client:
        embed.description = "未設定 OpenAI API Key，無法生成 AI 分析"
        return embed

    try:
        prompt = f"""你是專業的台股分析師，根據以下今日市場數據，用繁體中文撰寫一段精簡的明日展望分析（200字以內）。

要求：
1. 判斷明日大盤可能走勢（偏多/偏空/盤整）
2. 點出值得關注的板塊或個股
3. 提供操作建議（積極/保守/觀望）
4. 語氣專業但易懂

今日市場數據：
{data_text}

請直接回覆分析內容，不要加標題或前綴。"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "你是專業的台股市場分析師，擅長根據當日數據預測隔日走勢。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
            temperature=0.7,
        )

        ai_text = response.choices[0].message.content.strip()
        embed.description = ai_text

    except Exception as e:
        print(f"[AI 日報] OpenAI 呼叫失敗: {e}")
        embed.description = f"AI 分析生成失敗：{str(e)[:100]}"

    embed.set_footer(text="⚠️ AI 生成內容僅供參考，不構成投資建議 | ECF-AI")
    return embed
