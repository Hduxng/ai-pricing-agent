import json

import pytest

from config import ConfigError, load_settings, parse_bool, parse_tracked_skus


def test_parse_bool_accepts_common_values():
    assert parse_bool("true") is True
    assert parse_bool("0") is False
    assert parse_bool(None, default=True) is True


def test_parse_bool_rejects_unknown_value():
    with pytest.raises(ConfigError):
        parse_bool("maybe")


def test_parse_tracked_skus_from_json():
    env = {
        "TRACKED_SKUS_JSON": json.dumps(
            [
                {
                    "sku": "A1",
                    "name": "Sản phẩm A",
                    "base_cost": 100000,
                    "current_price": 150000,
                }
            ],
            ensure_ascii=False,
        )
    }

    assert parse_tracked_skus(env) == [
        {
            "sku": "A1",
            "name": "Sản phẩm A",
            "base_cost": 100000,
            "current_price": 150000,
        }
    ]


def test_load_settings_uses_safe_defaults():
    settings = load_settings({})

    assert settings.require_approval is True
    assert settings.dry_run is True
    assert settings.price_floor_percent == 0.85
    assert settings.tracked_skus


def test_load_settings_validates_percentages():
    with pytest.raises(ConfigError):
        load_settings({"PRICE_CEILING_PERCENT": "0.9"})
