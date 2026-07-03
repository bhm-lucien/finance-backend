"""
AI 持倉健檢服務

分析使用者持倉的：
1. 集中度風險（單一個股/產業占比過高）
2. 產業曝險（各產業配置比例）
3. AI 建議調整（呼叫 OpenAI 生成建議）
"""
import os
import time
from openai import OpenAI
from app.services.data_fetcher import fetch_stock_price
from app.services.realtime import fetch_realtime_price
from app.services.stock_list import fetch_all_stocks
from app.services.industry import fetch_industry_classification


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

_health_cache: dict[str, dict] = {}
CACHE_TTL = 300  # 5 分鐘快取


def analyze_portfolio_health(holdings: list[dict]) -> dict:
    """
    分析持倉健康度

    Args:
        holdings: [{"stock_id": "2330", "shares": 1000, "cost": 580.0}, ...]
            - stock_id: 股票代碼
            - shares: 持股股數
            - cost: 每股成本

    Returns:
        {
            "total_value": float,           # 持倉總市值
            "total_cost": float,            # 持倉總成本
            "total_pnl": float,             # 總損益
            "total_pnl_pct": float,         # 總報酬率(%)
            "concentration_risk": {...},    # 集中度風險
            "industry_exposure": [...],     # 產業曝險
            "stock_details": [...],         # 各股明細
            "risk_score": int,              # 風險分數 0~100
            "ai_advice": str,              # AI 建議
        }
    """
    if not holdings:
        return {"error": "持倉資料為空"}

    all_stocks = fetch_all_stocks()

    # 取得產業分類
    industry_data = fetch_industry_classification()
    stock_industry_map = _build_industry_map(industry_data)

    # 計算各股明細
    stock_details = []
    total_value = 0.0
    total_cost = 0.0

    for h in holdings:
        sid = h.get("stock_id", "")
        shares = h.get("shares", 0)
        cost = h.get("cost", 0)

        if not sid or shares <= 0:
            continue

        # 取得即時價格
        try:
            rt = fetch_realtime_price(sid)
            current_price = rt.get("price", 0)
            change_pct = rt.get("change_pct", 0)
        except Exception:
            current_price = 0
            change_pct = 0

        if current_price <= 0:
            # 用歷史收盤價
            try:
                df = fetch_stock_price(sid, days=5)
                if len(df) > 0:
                    current_price = float(df["close"].iloc[-1])
            except Exception:
                continue

        market_value = current_price * shares
        cost_value = cost * shares
        pnl = market_value - cost_value
        pnl_pct = (pnl / cost_value * 100) if cost_value > 0 else 0

        total_value += market_value
        total_cost += cost_value

        stock_details.append({
            "stock_id": sid,
            "name": all_stocks.get(sid, sid),
            "shares": shares,
            "cost": cost,
            "current_price": round(current_price, 2),
            "market_value": round(market_value, 0),
            "pnl": round(pnl, 0),
            "pnl_pct": round(pnl_pct, 2),
            "change_pct": change_pct,
            "industry": stock_industry_map.get(sid, "其他"),
            "weight": 0,  # 後面計算
        })

    # 計算權重
    for detail in stock_details:
        detail["weight"] = round(detail["market_value"] / total_value * 100, 1) if total_value > 0 else 0

    # 排序（按市值大到小）
    stock_details.sort(key=lambda x: x["market_value"], reverse=True)

    # 集中度風險分析
    concentration_risk = _analyze_concentration(stock_details)

    # 產業曝險分析
    industry_exposure = _analyze_industry_exposure(stock_details)

    # 風險評分
    risk_score = _calculate_risk_score(concentration_risk, industry_exposure, stock_details)

    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

    result = {
        "total_value": round(total_value, 0),
        "total_cost": round(total_cost, 0),
        "total_pnl": round(total_pnl, 0),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "concentration_risk": concentration_risk,
        "industry_exposure": industry_exposure,
        "stock_details": stock_details,
        "risk_score": risk_score,
        "ai_advice": "",
    }

    # AI 建議（非同步，可能較慢）
    try:
        result["ai_advice"] = _generate_ai_advice(result)
    except Exception as e:
        result["ai_advice"] = f"AI 建議生成失敗：{str(e)[:100]}"

    return result


def _analyze_concentration(stock_details: list[dict]) -> dict:
    """集中度風險分析"""
    if not stock_details:
        return {"level": "低", "score": 0, "top1_weight": 0, "top3_weight": 0, "description": "無持倉"}

    weights = [s["weight"] for s in stock_details]
    top1 = weights[0] if weights else 0
    top3 = sum(weights[:3])

    # 判斷集中度
    if top1 >= 50:
        level = "高"
        score = 90
        desc = f"單一持股佔比 {top1:.1f}%，集中度過高，建議分散"
    elif top1 >= 30:
        level = "中高"
        score = 70
        desc = f"最大持股佔比 {top1:.1f}%，略為集中"
    elif top3 >= 70:
        level = "中"
        score = 50
        desc = f"前三大持股合計 {top3:.1f}%，集中度中等"
    else:
        level = "低"
        score = 20
        desc = "持倉分散良好"

    return {
        "level": level,
        "score": score,
        "top1_weight": round(top1, 1),
        "top3_weight": round(top3, 1),
        "stock_count": len(stock_details),
        "description": desc,
    }


def _analyze_industry_exposure(stock_details: list[dict]) -> list[dict]:
    """產業曝險分析"""
    industry_map: dict[str, float] = {}

    for s in stock_details:
        industry = s.get("industry", "其他")
        industry_map[industry] = industry_map.get(industry, 0) + s["weight"]

    exposure = [
        {"industry": ind, "weight": round(w, 1)}
        for ind, w in industry_map.items()
    ]
    exposure.sort(key=lambda x: x["weight"], reverse=True)

    # 加上風險標記
    for exp in exposure:
        if exp["weight"] >= 50:
            exp["risk"] = "高"
        elif exp["weight"] >= 30:
            exp["risk"] = "中"
        else:
            exp["risk"] = "低"

    return exposure


def _calculate_risk_score(concentration: dict, exposure: list[dict], details: list[dict]) -> int:
    """計算綜合風險分數 0~100"""
    score = 0

    # 集中度（40%權重）
    score += concentration.get("score", 0) * 0.4

    # 產業集中度（30%權重）
    if exposure:
        max_industry_weight = exposure[0]["weight"]
        if max_industry_weight >= 60:
            score += 90 * 0.3
        elif max_industry_weight >= 40:
            score += 60 * 0.3
        elif max_industry_weight >= 25:
            score += 30 * 0.3
        else:
            score += 10 * 0.3

    # 虧損股占比（30%權重）
    loss_count = sum(1 for d in details if d["pnl"] < 0)
    loss_ratio = loss_count / len(details) if details else 0
    score += loss_ratio * 100 * 0.3

    return min(100, max(0, int(score)))


def _generate_ai_advice(portfolio_data: dict) -> str:
    """呼叫 OpenAI 生成持倉建議"""
    if not OPENAI_API_KEY:
        return "未設定 OpenAI API Key，無法生成 AI 建議"

    client = OpenAI(api_key=OPENAI_API_KEY)

    # 組裝資料摘要
    details = portfolio_data.get("stock_details", [])
    concentration = portfolio_data.get("concentration_risk", {})
    exposure = portfolio_data.get("industry_exposure", [])

    holdings_text = ""
    for d in details[:10]:
        holdings_text += f"- {d['stock_id']} {d['name']}：佔比{d['weight']}%，報酬{d['pnl_pct']:.1f}%，產業：{d['industry']}\n"

    exposure_text = ", ".join([f"{e['industry']}{e['weight']}%" for e in exposure[:5]])

    prompt = f"""你是專業的台股投資組合顧問，請根據以下持倉資料，用繁體中文提供精簡的調整建議（150字以內）。

持倉概況：
- 總市值：{portfolio_data['total_value']:,.0f} 元
- 總報酬：{portfolio_data['total_pnl_pct']:.1f}%
- 風險分數：{portfolio_data['risk_score']}/100
- 集中度：{concentration.get('description', '')}

持股明細：
{holdings_text}

產業分布：{exposure_text}

請提供：
1. 主要風險點
2. 建議調整方向（加碼/減碼/換股）
3. 一句話總結

直接回覆建議內容。"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "你是專業的台股投資組合分析師。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=400,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"AI 建議生成失敗：{str(e)[:100]}"


def _build_industry_map(industry_data: dict) -> dict[str, str]:
    """建立 stock_id → 產業名稱 的映射"""
    stock_map = {}
    categories = industry_data.get("categories", [])
    for cat in categories:
        for stock in cat.get("stocks", []):
            stock_map[stock["id"]] = cat["name"]
    return stock_map
