"""
產業分類服務
從 TWSE（證交所）官方取得台股上市公司產業分類及其成分股
"""
import time
import requests


# ── TWSE 產業代碼對照表 ──
INDUSTRY_CODE_MAP = {
    "01": "水泥工業",
    "02": "食品工業",
    "03": "塑膠工業",
    "04": "紡織纖維",
    "05": "電機機械",
    "06": "電器電纜",
    "07": "化學工業",
    "08": "生技醫療",
    "09": "玻璃陶瓷",
    "10": "造紙工業",
    "11": "鋼鐵工業",
    "12": "橡膠工業",
    "13": "汽車工業",
    "14": "半導體業",
    "15": "電腦及週邊設備業",
    "16": "光電業",
    "17": "通信網路業",
    "18": "電子零組件業",
    "19": "電子通路業",
    "20": "資訊服務業",
    "21": "其他電子業",
    "22": "建材營造業",
    "23": "航運業",
    "24": "觀光餐旅",
    "25": "金融保險業",
    "26": "貿易百貨業",
    "27": "油電燃氣業",
    "28": "綜合",
    "29": "其他業",
    "30": "居家生活",
    "31": "電子商務",
    "32": "數位雲端",
    "33": "運動休閒",
    "34": "綠能環保",
}


# ── 快取 ──
_industry_cache: dict[str, dict] = {}
CACHE_TTL = 86400  # 24 小時


def _get_cache(key: str):
    if key in _industry_cache:
        entry = _industry_cache[key]
        if time.time() - entry["time"] < CACHE_TTL:
            return entry["data"]
        del _industry_cache[key]
    return None


def _set_cache(key: str, data):
    _industry_cache[key] = {"data": data, "time": time.time()}


def fetch_industry_classification() -> dict:
    """
    從 TWSE OpenAPI 取得所有上市公司產業分類

    Returns:
        {
            "categories": [
                {
                    "name": "半導體業",
                    "count": 48,
                    "stocks": [
                        {"id": "2330", "name": "台積電"},
                        ...
                    ]
                },
                ...
            ],
            "total_industries": 34
        }
    """
    cache_key = "industry_all"
    cached = _get_cache(cache_key)
    if cached is not None:
        return cached

    try:
        # 從 TWSE OpenAPI 取得上市公司基本資料
        url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }

        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()

        if not data:
            return {"categories": [], "total_industries": 0}

        # 解析資料
        categories_map: dict[str, list] = {}

        for item in data:
            industry_code = item.get("產業別", "")
            stock_id = item.get("公司代號", "")
            stock_name = item.get("公司簡稱", "")

            if not industry_code or not stock_id:
                continue

            # 過濾非一般股票（只保留 4 位數代碼）
            if not stock_id.isdigit() or len(stock_id) != 4:
                continue

            # 將代碼轉為產業名稱
            industry_name = INDUSTRY_CODE_MAP.get(industry_code, f"其他({industry_code})")

            if industry_name not in categories_map:
                categories_map[industry_name] = []

            categories_map[industry_name].append({
                "id": stock_id,
                "name": stock_name,
            })

        # 按預定義順序排列（照代碼順序）
        code_order = list(INDUSTRY_CODE_MAP.values())
        categories = []
        for name in code_order:
            if name in categories_map:
                stocks = categories_map[name]
                stocks.sort(key=lambda x: x["id"])
                categories.append({
                    "name": name,
                    "count": len(stocks),
                    "stocks": stocks,
                })

        # 加入未在對照表中的分類
        for name, stocks in categories_map.items():
            if name not in code_order:
                stocks.sort(key=lambda x: x["id"])
                categories.append({
                    "name": name,
                    "count": len(stocks),
                    "stocks": stocks,
                })

        result = {"categories": categories, "total_industries": len(categories)}
        _set_cache(cache_key, result)
        return result

    except Exception as e:
        return {"categories": [], "total_industries": 0, "error": str(e)}


def get_industry_stocks(industry_name: str) -> list[dict]:
    """
    取得特定產業的成分股

    Args:
        industry_name: 產業名稱（如 "半導體業"）

    Returns:
        list of {"id": "2330", "name": "台積電"}
    """
    data = fetch_industry_classification()
    for cat in data.get("categories", []):
        if cat["name"] == industry_name:
            return cat["stocks"]
    return []
