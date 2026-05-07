import json
from types import SimpleNamespace

import pytest

from scraper import (
    MarketSearchError,
    normalize_market_data,
    parse_vnd_price,
    search_market_price,
)


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


def test_parse_vnd_price_handles_common_formats():
    assert parse_vnd_price("3.200.000đ") == 3200000
    assert parse_vnd_price("3,2 triệu") == 3200000
    assert parse_vnd_price("Liên hệ") is None


def test_normalize_market_data_recomputes_summary_when_missing():
    payload = {
        "product": "Pin",
        "prices": [
            {"source": "A", "price": 3000000, "url": "u1", "title": "Pin A"},
            {"source": "B", "price": 3500000, "url": "u2", "title": "Pin B"},
        ],
        "average_price": 0,
        "lowest_price": 0,
        "highest_price": 0,
        "note": "ok",
    }

    result = normalize_market_data(payload)

    assert result["average_price"] == 3250000
    assert result["lowest_price"] == 3000000
    assert result["highest_price"] == 3500000


def test_search_market_price_uses_responses_web_search():
    payload = {
        "product": "Pin",
        "prices": [{"source": "Shopee", "price": 3100000, "url": "https://s.vn", "title": "Pin"}],
        "average_price": 3100000,
        "lowest_price": 3100000,
        "highest_price": 3100000,
        "note": "ok",
    }
    client = FakeClient(json.dumps(payload))

    result = search_market_price("Pin lithium", client=client, model="gpt-test")

    assert result["prices"][0]["source"] == "Shopee"
    request = client.responses.request
    assert request["model"] == "gpt-test"
    assert request["tools"][0]["type"] == "web_search"
    assert request["tools"][0]["user_location"]["country"] == "VN"
    assert request["text"]["format"]["type"] == "json_schema"


def test_search_market_price_rejects_bad_json():
    client = FakeClient("not-json")

    with pytest.raises(MarketSearchError):
        search_market_price("Pin lithium", client=client)
