from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


def _load_local_env_file(path: Path | None = None) -> None:
    env_path = path or Path(__file__).resolve().parent / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - python-dotenv is optional for tests
    _load_local_env_file()


class ConfigError(ValueError):
    """Raised when environment configuration is invalid."""


DEFAULT_TRACKED_SKUS: list[dict[str, Any]] = [
    {
        "sku": "AA1200",
        "name": "Pin Sạc AA 1.2V Ni-MH 1200mAh",
        "base_cost": 33_000,
        "current_price": 52_000,
    },
    {
        "sku": "AA2000",
        "name": "Pin Sạc AA 1.2V Ni-MH 2000mAh",
        "base_cost": 51_000,
        "current_price": 80_000,
    },
    {
        "sku": "BTCSC24-C8022B",
        "name": "Sạc Pin AA & AAA 1.2V Ni-MH 4 Khe C8022B",
        "base_cost": 29_000,
        "current_price": 46_000,
    },
    {
        "sku": "BTCSCA-C9012",
        "name": "Sạc Pin AA & AAA 1.2V Ni-MH 4 Khe C9012",
        "base_cost": 90_000,
        "current_price": 140_000,
    },
    {
        "sku": "BTCSCA-C9025L",
        "name": "Sạc Pin AA & AAA 1.2V Ni-MH LCD 12 Khe C9025L",
        "base_cost": 205_000,
        "current_price": 320_000,
    },
]


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value

    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ConfigError(f"Invalid boolean value: {value!r}")


def _parse_float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key)
    if raw in (None, ""):
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number") from exc
    if value <= 0:
        raise ConfigError(f"{key} must be greater than 0")
    return value


def _parse_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer") from exc
    if value <= 0:
        raise ConfigError(f"{key} must be greater than 0")
    return value


def _validate_sku(raw_sku: Mapping[str, Any]) -> dict[str, Any]:
    required = {"sku", "name", "base_cost", "current_price"}
    missing = required - set(raw_sku)
    if missing:
        raise ConfigError(f"Tracked SKU missing fields: {sorted(missing)}")

    sku = str(raw_sku["sku"]).strip()
    name = str(raw_sku["name"]).strip()
    if not sku or not name:
        raise ConfigError("SKU and name must not be empty")

    try:
        base_cost = int(raw_sku["base_cost"])
        current_price = int(raw_sku["current_price"])
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"SKU {sku}: base_cost/current_price must be integers") from exc

    if base_cost <= 0 or current_price <= 0:
        raise ConfigError(f"SKU {sku}: base_cost/current_price must be greater than 0")

    return {
        "sku": sku,
        "name": name,
        "base_cost": base_cost,
        "current_price": current_price,
    }


def parse_tracked_skus(env: Mapping[str, str]) -> list[dict[str, Any]]:
    raw = env.get("TRACKED_SKUS_JSON")
    if not raw:
        return [dict(item) for item in DEFAULT_TRACKED_SKUS]

    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError("TRACKED_SKUS_JSON must be valid JSON") from exc

    if not isinstance(decoded, list) or not decoded:
        raise ConfigError("TRACKED_SKUS_JSON must be a non-empty list")

    return [_validate_sku(item) for item in decoded]


def _validate_percentages(settings: "PricingSettings") -> None:
    if not 0 < settings.price_floor_percent <= 1:
        raise ConfigError("PRICE_FLOOR_PERCENT must be > 0 and <= 1")
    if settings.price_ceiling_percent < 1:
        raise ConfigError("PRICE_CEILING_PERCENT must be >= 1")
    if not 0 < settings.max_daily_change_percent <= 1:
        raise ConfigError("MAX_DAILY_CHANGE_PERCENT must be > 0 and <= 1")
    if not 0 < settings.min_margin_percent < 1:
        raise ConfigError("MIN_MARGIN_PERCENT must be > 0 and < 1")


@dataclass(frozen=True)
class PricingSettings:
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.5"
    openai_search_model: str = "gpt-5.5"
    openai_reasoning_effort: str = "low"
    db_path: str = "pricing.db"
    price_floor_percent: float = 0.85
    price_ceiling_percent: float = 1.30
    max_daily_change_percent: float = 0.10
    min_margin_percent: float = 0.15
    price_rounding: int = 1_000
    require_approval: bool = True
    dry_run: bool = True
    check_interval_hours: int = 6
    tracked_skus: list[dict[str, Any]] = field(default_factory=list)
    website_api_base_url: str = ""
    website_api_key: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    timezone: str = "Asia/Ho_Chi_Minh"


def load_settings(env: Mapping[str, str] | None = None) -> PricingSettings:
    env = os.environ if env is None else env

    settings = PricingSettings(
        openai_api_key=env.get("OPENAI_API_KEY") or None,
        openai_model=env.get("OPENAI_MODEL", "gpt-5.5"),
        openai_search_model=env.get("OPENAI_SEARCH_MODEL", env.get("OPENAI_MODEL", "gpt-5.5")),
        openai_reasoning_effort=env.get("OPENAI_REASONING_EFFORT", "low"),
        db_path=env.get("DB_PATH", "pricing.db"),
        price_floor_percent=_parse_float(env, "PRICE_FLOOR_PERCENT", 0.85),
        price_ceiling_percent=_parse_float(env, "PRICE_CEILING_PERCENT", 1.30),
        max_daily_change_percent=_parse_float(env, "MAX_DAILY_CHANGE_PERCENT", 0.10),
        min_margin_percent=_parse_float(env, "MIN_MARGIN_PERCENT", 0.15),
        price_rounding=_parse_int(env, "PRICE_ROUNDING", 1_000),
        require_approval=parse_bool(env.get("REQUIRE_APPROVAL"), default=True),
        dry_run=parse_bool(env.get("DRY_RUN"), default=True),
        check_interval_hours=_parse_int(env, "CHECK_INTERVAL_HOURS", 6),
        tracked_skus=parse_tracked_skus(env),
        website_api_base_url=env.get("WEBSITE_API_BASE_URL", "").rstrip("/"),
        website_api_key=env.get("WEBSITE_API_KEY") or None,
        telegram_bot_token=env.get("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=env.get("TELEGRAM_CHAT_ID") or None,
        timezone=env.get("APP_TIMEZONE", "Asia/Ho_Chi_Minh"),
    )
    _validate_percentages(settings)
    return settings


SETTINGS = load_settings()

# Backward-compatible constants for simple scripts and the initial project plan.
OPENAI_API_KEY = SETTINGS.openai_api_key
OPENAI_MODEL = SETTINGS.openai_model
OPENAI_SEARCH_MODEL = SETTINGS.openai_search_model
OPENAI_REASONING_EFFORT = SETTINGS.openai_reasoning_effort
DB_PATH = SETTINGS.db_path
PRICE_FLOOR_PERCENT = SETTINGS.price_floor_percent
PRICE_CEILING_PERCENT = SETTINGS.price_ceiling_percent
MAX_DAILY_CHANGE_PERCENT = SETTINGS.max_daily_change_percent
MIN_MARGIN_PERCENT = SETTINGS.min_margin_percent
PRICE_ROUNDING = SETTINGS.price_rounding
REQUIRE_APPROVAL = SETTINGS.require_approval
DRY_RUN = SETTINGS.dry_run
CHECK_INTERVAL_HOURS = SETTINGS.check_interval_hours
TRACKED_SKUS = SETTINGS.tracked_skus
WEBSITE_API_BASE_URL = SETTINGS.website_api_base_url
WEBSITE_API_KEY = SETTINGS.website_api_key
TELEGRAM_BOT_TOKEN = SETTINGS.telegram_bot_token
TELEGRAM_CHAT_ID = SETTINGS.telegram_chat_id
APP_TIMEZONE = SETTINGS.timezone
