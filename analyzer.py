from __future__ import annotations

import json
from typing import Any

from config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_REASONING_EFFORT


SYSTEM_PROMPT = """Bạn là AI Agent định giá động cho doanh nghiệp TMĐT Việt Nam.

NHIỆM VỤ: Phân tích dữ liệu thị trường và đề xuất giá bán tối ưu.

NGUYÊN TẮC:
1. Giá đề xuất phải cao hơn giá vốn và giữ biên lợi nhuận lành mạnh.
2. Cân bằng giữa cạnh tranh, biên lợi nhuận, tồn kho giả định và rủi ro cuộc đua giảm giá.
3. Nếu đối thủ giảm giá, chỉ đề xuất giảm có kiểm soát và giải thích rủi ro.
4. Nếu dữ liệu thị trường yếu hoặc nhiễu, ưu tiên giữ giá hoặc thay đổi nhỏ.
5. Guardrails kỹ thuật sẽ kiểm tra lại đề xuất; không cố vượt guardrails.

Trả về JSON đúng schema, không thêm lời giải thích ngoài JSON."""


RECOMMENDATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "recommended_price": {"type": "integer"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "reason": {"type": "string"},
        "action": {"type": "string", "enum": ["increase", "decrease", "hold"]},
        "market_position": {
            "type": "string",
            "enum": ["below_market", "at_market", "above_market", "unknown"],
        },
        "expected_margin_percent": {"type": "number"},
    },
    "required": [
        "recommended_price",
        "confidence",
        "reason",
        "action",
        "market_position",
        "expected_margin_percent",
    ],
    "additionalProperties": False,
}


class AnalysisError(RuntimeError):
    pass


def _create_openai_client(api_key: str | None = None):
    if not api_key:
        raise AnalysisError("OPENAI_API_KEY is required for price analysis")
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - exercised only without dependency
        raise AnalysisError("Install the openai package to use price analysis") from exc
    return OpenAI(api_key=api_key)


def _extract_output_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text
    if isinstance(response, dict) and response.get("output_text"):
        return str(response["output_text"])
    raise AnalysisError("OpenAI response did not include output_text")


def calculate_margin_percent(base_cost: float, price: float) -> float:
    if price <= 0:
        return 0.0
    return round((price - base_cost) / price * 100, 2)


def build_analysis_prompt(
    sku_info: dict[str, Any],
    competitor_history: list[dict[str, Any]],
    market_data: dict[str, Any],
) -> str:
    current_margin = calculate_margin_percent(
        sku_info["base_cost"],
        sku_info["current_price"],
    )
    return f"""
=== THÔNG TIN SẢN PHẨM ===
SKU: {sku_info["sku"]}
Tên: {sku_info["name"]}
Giá vốn: {sku_info["base_cost"]:,}đ
Giá bán hiện tại: {sku_info["current_price"]:,}đ
Biên lợi nhuận hiện tại: {current_margin:.1f}%

=== GIÁ ĐỐI THỦ GẦN ĐÂY ===
{json.dumps(competitor_history, ensure_ascii=False, indent=2) if competitor_history else "Chưa có dữ liệu lịch sử"}

=== DỮ LIỆU THỊ TRƯỜNG MỚI NHẤT ===
{json.dumps(market_data, ensure_ascii=False, indent=2)}

Hãy đề xuất giá bán tối ưu cho lần kiểm tra này.
"""


def _supports_reasoning(model: str) -> bool:
    return model.startswith("gpt-5")


def _validate_recommendation(payload: dict[str, Any]) -> dict[str, Any]:
    missing = set(RECOMMENDATION_SCHEMA["required"]) - set(payload)
    if missing:
        raise AnalysisError(f"Recommendation missing fields: {sorted(missing)}")

    payload["recommended_price"] = int(payload["recommended_price"])
    if payload["recommended_price"] <= 0:
        raise AnalysisError("recommended_price must be greater than 0")

    if payload["confidence"] not in {"high", "medium", "low"}:
        raise AnalysisError(f"Invalid confidence: {payload['confidence']}")
    if payload["action"] not in {"increase", "decrease", "hold"}:
        raise AnalysisError(f"Invalid action: {payload['action']}")
    if payload["market_position"] not in {
        "below_market",
        "at_market",
        "above_market",
        "unknown",
    }:
        raise AnalysisError(f"Invalid market_position: {payload['market_position']}")

    payload["expected_margin_percent"] = float(payload["expected_margin_percent"])
    payload["reason"] = str(payload["reason"]).strip()
    if not payload["reason"]:
        raise AnalysisError("reason must not be empty")
    return payload


def analyze_and_recommend(
    sku_info: dict[str, Any],
    competitor_history: list[dict[str, Any]],
    market_data: dict[str, Any],
    *,
    client: Any | None = None,
    model: str = OPENAI_MODEL,
    api_key: str | None = OPENAI_API_KEY,
    reasoning_effort: str = OPENAI_REASONING_EFFORT,
) -> dict[str, Any]:
    """Call OpenAI Responses API and return a validated recommendation dict."""
    client = client or _create_openai_client(api_key)
    text_options: dict[str, Any] = {
        "format": {
            "type": "json_schema",
            "name": "price_recommendation",
            "strict": True,
            "schema": RECOMMENDATION_SCHEMA,
        }
    }
    request: dict[str, Any] = {
        "model": model,
        "input": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_analysis_prompt(sku_info, competitor_history, market_data),
            },
        ],
        "text": text_options,
    }
    if _supports_reasoning(model) and reasoning_effort.lower() != "none":
        request["reasoning"] = {"effort": reasoning_effort}

    response = client.responses.create(**request)
    try:
        payload = json.loads(_extract_output_text(response))
    except json.JSONDecodeError as exc:
        raise AnalysisError("Analysis returned invalid JSON") from exc

    return _validate_recommendation(payload)
