from __future__ import annotations

import math
from dataclasses import dataclass

from config import (
    MAX_DAILY_CHANGE_PERCENT,
    MIN_MARGIN_PERCENT,
    PRICE_CEILING_PERCENT,
    PRICE_FLOOR_PERCENT,
    PRICE_ROUNDING,
)


@dataclass(frozen=True)
class GuardrailResult:
    is_valid: bool
    errors: list[str]
    adjusted_price: int
    lower_bound: int
    upper_bound: int


def _round_to_step(value: float, step: int, mode: str = "nearest") -> int:
    if step <= 1:
        return int(round(value))
    if mode == "up":
        return int(math.ceil(value / step) * step)
    if mode == "down":
        return int(math.floor(value / step) * step)
    return int(round(value / step) * step)


def minimum_price_for_margin(base_cost: float, margin_percent: float = MIN_MARGIN_PERCENT) -> int:
    if base_cost <= 0:
        raise ValueError("base_cost must be greater than 0")
    if not 0 < margin_percent < 1:
        raise ValueError("margin_percent must be between 0 and 1")
    return int(math.ceil(base_cost / (1 - margin_percent)))


def validate_price_detailed(
    sku_info: dict,
    recommended_price: float,
    *,
    price_floor_percent: float = PRICE_FLOOR_PERCENT,
    price_ceiling_percent: float = PRICE_CEILING_PERCENT,
    max_daily_change_percent: float = MAX_DAILY_CHANGE_PERCENT,
    min_margin_percent: float = MIN_MARGIN_PERCENT,
    price_rounding: int = PRICE_ROUNDING,
) -> GuardrailResult:
    errors: list[str] = []
    base_cost = float(sku_info["base_cost"])
    current = float(sku_info["current_price"])

    if current <= 0:
        raise ValueError("current_price must be greater than 0")
    if recommended_price <= 0:
        errors.append(f"Giá đề xuất không hợp lệ: {recommended_price}")

    min_margin_price = _round_to_step(
        minimum_price_for_margin(base_cost, min_margin_percent),
        price_rounding,
        mode="up",
    )
    floor_price = _round_to_step(current * price_floor_percent, price_rounding, mode="up")
    daily_low = _round_to_step(current * (1 - max_daily_change_percent), price_rounding, mode="up")
    lower_bound = max(min_margin_price, floor_price, daily_low)

    ceiling_price = _round_to_step(current * price_ceiling_percent, price_rounding, mode="down")
    daily_high = _round_to_step(current * (1 + max_daily_change_percent), price_rounding, mode="down")
    upper_bound = min(ceiling_price, daily_high)

    if lower_bound > upper_bound:
        errors.append(
            "Ràng buộc an toàn xung đột; ưu tiên giá tối thiểu theo vốn/margin"
        )
        upper_bound = lower_bound

    rounded_recommendation = _round_to_step(float(recommended_price), price_rounding)
    adjusted = rounded_recommendation

    if rounded_recommendation < min_margin_price:
        errors.append(
            f"Dưới margin tối thiểu: {rounded_recommendation:,} < {min_margin_price:,}"
        )
    if rounded_recommendation < floor_price:
        errors.append(f"Dưới sàn giá: {rounded_recommendation:,} < {floor_price:,}")
    if rounded_recommendation < daily_low:
        errors.append(
            f"Vượt giới hạn giảm {max_daily_change_percent:.0%}/ngày: "
            f"{rounded_recommendation:,} < {daily_low:,}"
        )
    if rounded_recommendation > ceiling_price:
        errors.append(f"Vượt trần giá: {rounded_recommendation:,} > {ceiling_price:,}")
    if rounded_recommendation > daily_high:
        errors.append(
            f"Vượt giới hạn tăng {max_daily_change_percent:.0%}/ngày: "
            f"{rounded_recommendation:,} > {daily_high:,}"
        )

    if adjusted < lower_bound:
        adjusted = lower_bound
    if adjusted > upper_bound:
        adjusted = upper_bound

    return GuardrailResult(
        is_valid=len(errors) == 0,
        errors=errors,
        adjusted_price=int(adjusted),
        lower_bound=int(lower_bound),
        upper_bound=int(upper_bound),
    )


def validate_price(sku_info: dict, recommended_price: float) -> tuple[bool, list[str], int]:
    result = validate_price_detailed(sku_info, recommended_price)
    return result.is_valid, result.errors, result.adjusted_price
