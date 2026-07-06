"""
AI 個股研究報告生成服務

提供基本面角度的深度分析（DCF 估值、三情境預測、風險矩陣）
與 Dashboard 的技術面/籌碼面/短線操作建議互補
"""
import os
import time
from openai import OpenAI
from app.services.data_fetcher import fetch_stock_price
from app.services.realtime import fetch_realtime_price
from app.services.stock_list import fetch_all_stocks


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

_report_cache: dict[str, dict] = {}
CACHE_TTL = 1800  # 30 分鐘快取（研報不需要太即時）


def generate_stock_report(stock_id: str) -> dict:
    """
    生成 AI 個股研究報告

    Returns:
        {
            "stock_id": str,
            "name": str,
            "report": {
                "company_overview": str,
                "revenue_analysis": str,
                "dcf_valuation": str,
                "scenarios": str,
                "risk_matrix": str,
                "investment_rating": str,
            },
            "metrics": {...},
            "update_time": str,
        }
    """
    cache_key = f"report_{stock_id}"
    if cache_key in _report_cache:
        entry = _report_cache[cache_key]
        if time.time() - entry["time"] < CACHE_TTL:
            return entry["data"]

    # 收集資料
    all_stocks = fetch_all_stocks()
    name = all_stocks.get(stock_id, stock_id)

    # 歷史股價
    try:
        df = fetch_stock_price(stock_id, days=365)
        if len(df) < 20:
            return {"error": "歷史資料不足，無法生成報告"}
    except Exception as e:
        return {"error": f"無法取得歷史資料：{str(e)[:100]}"}

    # 計算基本指標
    closes = df["close"].values
    current_price = float(closes[-1])
    high_52w = float(df["close"].max())
    low_52w = float(df["close"].min())
    avg_volume = float(df["volume"].tail(20).mean())

    # 計算報酬率
    if len(closes) >= 5:
        ret_5d = (closes[-1] / closes[-5] - 1) * 100
    else:
        ret_5d = 0
    if len(closes) >= 20:
        ret_20d = (closes[-1] / closes[-20] - 1) * 100
    else:
        ret_20d = 0
    if len(closes) >= 60:
        ret_60d = (closes[-1] / closes[-60] - 1) * 100
    else:
        ret_60d = 0

    # 即時報價
    try:
        rt = fetch_realtime_price(stock_id)
        current_price = rt.get("price", current_price) or current_price
        change_pct = rt.get("change_pct", 0)
    except Exception:
        change_pct = 0

    metrics = {
        "current_price": round(current_price, 2),
        "high_52w": round(high_52w, 2),
        "low_52w": round(low_52w, 2),
        "avg_volume": int(avg_volume),
        "return_5d": round(ret_5d, 2),
        "return_20d": round(ret_20d, 2),
        "return_60d": round(ret_60d, 2),
        "change_pct": round(change_pct, 2),
        "position_52w": round((current_price - low_52w) / (high_52w - low_52w) * 100, 1) if high_52w > low_52w else 50,
    }

    # 呼叫 OpenAI 生成報告
    report = _generate_report_with_ai(stock_id, name, metrics)

    result = {
        "stock_id": stock_id,
        "name": name,
        "report": report,
        "metrics": metrics,
        "update_time": time.strftime("%Y-%m-%d %H:%M"),
    }

    _report_cache[cache_key] = {"data": result, "time": time.time()}
    return result


def _generate_report_with_ai(stock_id: str, name: str, metrics: dict) -> dict:
    """用 OpenAI 生成各區塊報告"""
    if not OPENAI_API_KEY:
        return _fallback_report(stock_id, name, metrics)

    client = OpenAI(api_key=OPENAI_API_KEY)

    prompt = f"""你是專業的台股投資研究分析師，請根據以下資料，用繁體中文為「{stock_id} {name}」撰寫一份深度個股研究報告。

目前數據：
- 目前股價：{metrics['current_price']}
- 52 週高點：{metrics['high_52w']}
- 52 週低點：{metrics['low_52w']}
- 近 5 日報酬：{metrics['return_5d']:.1f}%
- 近 20 日報酬：{metrics['return_20d']:.1f}%
- 近 60 日報酬：{metrics['return_60d']:.1f}%
- 52 週位置：{metrics['position_52w']:.0f}%（0=最低，100=最高）
- 平均成交量：{metrics['avg_volume']:,} 股

請嚴格按以下 JSON 格式回覆，每個欄位的內容為一段文字（100-200字）：

{{
  "company_overview": "公司概況：產業定位、主要產品/服務、競爭優勢、市場地位",
  "revenue_analysis": "營收成長性：根據股價走勢推估近期營運動能、成長趨勢判斷",
  "dcf_valuation": "估值分析：根據股價歷史區間，給出合理價位區間（便宜價/合理價/昂貴價），並說明估值邏輯",
  "scenarios": "三情境目標價：樂觀/中性/悲觀情境各自的目標價和觸發條件",
  "risk_matrix": "風險矩陣：列出 3-4 個主要風險（產業風險、營運風險、總經風險等）及其影響程度",
  "investment_rating": "投資評等：給出長線投資評等（強力買進/買進/中性/減碼/賣出）和一句話總結理由"
}}

注意：只回覆 JSON，不要加任何其他文字。"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "你是專業的台股投資研究分析師，擅長基本面分析和估值。回覆格式必須是純 JSON。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1500,
            temperature=0.7,
        )

        import json
        text = response.choices[0].message.content.strip()
        # 移除可能的 markdown code block
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]

        report = json.loads(text)
        return report

    except Exception as e:
        print(f"[個股研報] OpenAI 呼叫失敗: {e}")
        return _fallback_report(stock_id, name, metrics)


def _fallback_report(stock_id: str, name: str, metrics: dict) -> dict:
    """OpenAI 不可用時的規則型 fallback"""
    price = metrics["current_price"]
    pos = metrics["position_52w"]

    if pos > 80:
        zone = "偏高"
        rating = "中性"
    elif pos > 50:
        zone = "中高"
        rating = "買進"
    elif pos > 20:
        zone = "合理"
        rating = "買進"
    else:
        zone = "偏低"
        rating = "強力買進"

    cheap = round(metrics["low_52w"] * 1.05, 2)
    fair = round((metrics["high_52w"] + metrics["low_52w"]) / 2, 2)
    expensive = round(metrics["high_52w"] * 0.95, 2)

    return {
        "company_overview": f"{stock_id} {name} — 目前股價 {price}，位於 52 週區間的 {pos:.0f}% 位置（{zone}區）。",
        "revenue_analysis": f"近 5 日報酬 {metrics['return_5d']:.1f}%，近 20 日 {metrics['return_20d']:.1f}%，近 60 日 {metrics['return_60d']:.1f}%。",
        "dcf_valuation": f"根據歷史股價區間估算：便宜價 {cheap}｜合理價 {fair}｜昂貴價 {expensive}。目前位於{zone}區。",
        "scenarios": f"樂觀：{expensive}（突破前高）｜中性：{fair}（維持區間）｜悲觀：{cheap}（回測低檔）",
        "risk_matrix": "需要 OpenAI API Key 才能生成完整風險分析。",
        "investment_rating": f"長線評等：{rating}（基於 52 週位置 {pos:.0f}%）。注意：此為規則型簡易評等，非 AI 深度分析。",
    }
