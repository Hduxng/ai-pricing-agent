from __future__ import annotations

import json
import re
from types import SimpleNamespace
from statistics import mean
from typing import Any

from config import APP_TIMEZONE, OPENAI_API_KEY, OPENAI_SEARCH_MODEL


MARKET_PRICE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "product": {"type": "string"},
        "prices": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "price": {"type": "integer"},
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                },
                "required": ["source", "price", "url", "title"],
                "additionalProperties": False,
            },
        },
        "average_price": {"type": "integer"},
        "lowest_price": {"type": "integer"},
        "highest_price": {"type": "integer"},
        "note": {"type": "string"},
    },
    "required": [
        "product",
        "prices",
        "average_price",
        "lowest_price",
        "highest_price",
        "note",
    ],
    "additionalProperties": False,
}


class MarketSearchError(RuntimeError):
    pass


def _create_openai_client(api_key: str | None = None):
    if not api_key:
        raise MarketSearchError("OPENAI_API_KEY is required for market search")
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - exercised only without dependency
        return _RequestsOpenAIClient(api_key)
    return OpenAI(api_key=api_key)


class _RequestsOpenAIClient:
    def __init__(self, api_key: str):
        self.responses = _RequestsResponses(api_key)


class _RequestsResponses:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def create(self, **kwargs: Any) -> Any:
        try:
            import requests
        except ImportError as exc:  # pragma: no cover - fallback dependency boundary
            raise MarketSearchError("Install requests or openai to use market search") from exc

        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=kwargs,
            timeout=60,
        )
        response.raise_for_status()
        raw = response.json()
        return SimpleNamespace(output_text=_extract_response_text(raw), raw_response=raw)


def _extract_response_text(payload: dict[str, Any]) -> str:
    if payload.get("output_text"):
        return str(payload["output_text"])
    for item in payload.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                return str(content["text"])
    raise MarketSearchError("OpenAI response did not include output text")


def _extract_output_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text
    if isinstance(response, dict) and response.get("output_text"):
        return str(response["output_text"])
    raise MarketSearchError("OpenAI response did not include output_text")


def normalize_market_data(payload: dict[str, Any], *, max_results: int = 10) -> dict[str, Any]:
    product = str(payload.get("product", "")).strip()
    note = str(payload.get("note", "")).strip()
    prices: list[dict[str, Any]] = []

    for item in payload.get("prices", [])[:max_results]:
        parsed_price = int(item.get("price", 0))
        if parsed_price <= 0:
            continue
        prices.append(
            {
                "source": str(item.get("source", "")).strip() or "unknown",
                "price": parsed_price,
                "url": str(item.get("url", "")).strip(),
                "title": str(item.get("title", "")).strip(),
            }
        )

    price_values = [item["price"] for item in prices]
    if price_values:
        average_price = int(mean(price_values))
        lowest_price = min(price_values)
        highest_price = max(price_values)
    else:
        average_price = lowest_price = highest_price = 0

    return {
        "product": product,
        "prices": prices,
        "average_price": int(payload.get("average_price") or average_price),
        "lowest_price": int(payload.get("lowest_price") or lowest_price),
        "highest_price": int(payload.get("highest_price") or highest_price),
        "note": note,
    }


def search_market_price(
    product_name: str,
    *,
    client: Any | None = None,
    model: str = OPENAI_SEARCH_MODEL,
    api_key: str | None = OPENAI_API_KEY,
    max_results: int = 8,
) -> dict[str, Any]:
    """Search Vietnamese marketplaces with OpenAI web search and return normalized JSON."""
    if not product_name.strip():
        raise ValueError("product_name must not be empty")

    client = client or _create_openai_client(api_key)
    prompt = f"""
Tìm giá bán hiện tại của sản phẩm "{product_name}" trên các sàn TMĐT Việt Nam
như Shopee, Lazada, Tiki, Sendo và các website bán lẻ đáng tin cậy.

Yêu cầu:
- Ưu tiên kết quả đúng sản phẩm hoặc rất gần về cấu hình.
- Loại bỏ bài đăng cũ, hết hàng, giá đặt cọc hoặc giá phụ kiện không cùng sản phẩm.
- Giá trả về là số nguyên VND, không kèm ký tự tiền tệ.
- Nếu không đủ dữ liệu đáng tin cậy, để mảng prices rỗng và giải thích ngắn trong note.
"""

    response = client.responses.create(
        model=model,
        tools=[
            {
                "type": "web_search",
                "search_context_size": "low",
                "user_location": {
                    "type": "approximate",
                    "country": "VN",
                    "city": "Ho Chi Minh City",
                    "region": "Ho Chi Minh",
                    "timezone": APP_TIMEZONE,
                },
            }
        ],
        input=prompt,
        text={
            "format": {
                "type": "json_schema",
                "name": "market_price_search",
                "strict": True,
                "schema": MARKET_PRICE_SCHEMA,
            }
        },
    )

    try:
        payload = json.loads(_extract_output_text(response))
    except json.JSONDecodeError as exc:
        raise MarketSearchError("Market search returned invalid JSON") from exc

    return normalize_market_data(payload, max_results=max_results)


def parse_vnd_price(text: str) -> int | None:
    if not text:
        return None
    normalized = text.replace("\xa0", " ").strip().lower()

    million_match = re.search(r"(\d+(?:[,.]\d+)?)\s*(triệu|tr\b)", normalized)
    if million_match:
        number = float(million_match.group(1).replace(",", "."))
        return int(number * 1_000_000)

    digits = re.sub(r"[^\d]", "", normalized)
    if not digits:
        return None
    value = int(digits)
    return value if value > 0 else None


def scrape_price(url: str, price_selector: str = ".product-price") -> int | None:
    import requests
    from bs4 import BeautifulSoup

    headers = {"User-Agent": "Mozilla/5.0 (compatible; AI-Pricing-Agent/1.0)"}
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    element = soup.select_one(price_selector)
    if element is None:
        return None
    return parse_vnd_price(element.get_text(" ", strip=True))


def search_via_serpapi(product_name: str, serpapi_key: str) -> list[dict[str, Any]]:
    import requests

    if not serpapi_key:
        raise ValueError("serpapi_key is required")
    resp = requests.get(
        "https://serpapi.com/search",
        params={
            "q": f"{product_name} giá bán site:shopee.vn OR site:lazada.vn OR site:tiki.vn",
            "api_key": serpapi_key,
            "gl": "vn",
            "hl": "vi",
            "num": 10,
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json().get("organic_results", [])
