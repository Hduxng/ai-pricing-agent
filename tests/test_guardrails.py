from guardrails import minimum_price_for_margin, validate_price, validate_price_detailed


SKU = {"sku": "SKU001", "base_cost": 2_000_000, "current_price": 3_200_000}


def test_minimum_price_uses_true_margin_formula():
    assert minimum_price_for_margin(2_000_000, 0.15) == 2_352_942


def test_valid_price_passes_and_rounds():
    result = validate_price_detailed(SKU, 3_240_500)

    assert result.is_valid is True
    assert result.adjusted_price == 3_240_000


def test_price_below_margin_is_adjusted_up():
    result = validate_price_detailed(SKU, 2_100_000)

    assert result.is_valid is False
    assert result.adjusted_price >= 2_353_000
    assert any("margin" in error for error in result.errors)


def test_daily_change_caps_large_increase():
    result = validate_price_detailed(SKU, 4_500_000)

    assert result.is_valid is False
    assert result.adjusted_price == 3_520_000
    assert any("tăng" in error for error in result.errors)


def test_legacy_validate_price_tuple_shape():
    is_valid, errors, adjusted = validate_price(SKU, 4_500_000)

    assert is_valid is False
    assert errors
    assert adjusted == 3_520_000
