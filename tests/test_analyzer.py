import json
from types import SimpleNamespace

import pytest

from analyzer import AnalysisError, analyze_and_recommend, build_analysis_prompt, calculate_margin_percent


SKU = {
    "sku": "SKU001",
    "name": "Pin lithium 12V 100Ah",
    "base_cost": 2_000_000,
    "current_price": 3_200_000,
}


class FakeResponses:
    def __init__(self, output_text):
        self.output_text = output_text
        self.request = None

    def create(self, **kwargs):
        self.request = kwargs
        return SimpleNamespace(output_text=self.output_text)


class FakeClient:
    def __init__(self, output_text):
        self.responses = FakeResponses(output_text)


def test_calculate_margin_percent():
    assert calculate_margin_percent(2_000_000, 3_200_000) == 37.5


def test_build_analysis_prompt_contains_context():
    prompt = build_analysis_prompt(SKU, [], {"average_price": 3100000})

    assert "SKU001" in prompt
    assert "3,200,000đ" in prompt
    assert "average_price" in prompt


def test_analyze_and_recommend_returns_validated_payload():
    payload = {
        "recommended_price": 3250000,
        "confidence": "medium",
        "reason": "Giá thị trường ổn định, nên tăng nhẹ để tối ưu margin.",
        "action": "increase",
        "market_position": "at_market",
        "expected_margin_percent": 38.46,
    }
    client = FakeClient(json.dumps(payload, ensure_ascii=False))

    result = analyze_and_recommend(
        SKU,
        [],
        {"prices": [], "average_price": 0},
        client=client,
        model="gpt-5.5",
        reasoning_effort="low",
    )

    assert result["recommended_price"] == 3250000
    request = client.responses.request
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["reasoning"] == {"effort": "low"}


def test_analyze_and_recommend_omits_reasoning_for_non_gpt5_model():
    payload = {
        "recommended_price": 3200000,
        "confidence": "low",
        "reason": "Dữ liệu yếu nên giữ giá.",
        "action": "hold",
        "market_position": "unknown",
        "expected_margin_percent": 37.5,
    }
    client = FakeClient(json.dumps(payload, ensure_ascii=False))

    analyze_and_recommend(SKU, [], {"prices": []}, client=client, model="gpt-4o")

    assert "reasoning" not in client.responses.request


def test_analyze_and_recommend_rejects_missing_fields():
    client = FakeClient(json.dumps({"recommended_price": 1}))

    with pytest.raises(AnalysisError):
        analyze_and_recommend(SKU, [], {"prices": []}, client=client)
