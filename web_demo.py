from __future__ import annotations

import argparse
import errno
import json
import logging
import mimetypes
import os
import re
import sqlite3
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from config import DB_PATH, OPENAI_API_KEY
from database import utc_now_iso
from guardrails import validate_price_detailed
from scraper import search_market_price


ROOT_DIR = Path(__file__).resolve().parent
STATIC_DIR = ROOT_DIR / "web_static"
DEFAULT_DIFY_API_BASE_URL = "https://api.dify.ai/v1"
logger = logging.getLogger(__name__)
MarketSearcher = Callable[[str], dict[str, Any]]


def load_local_env(path: Path = ROOT_DIR / ".env") -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except ValueError:
        return default


load_local_env()

DEMO_SINGLE_SOURCE_PROPOSALS = env_bool("DEMO_SINGLE_SOURCE_PROPOSALS", True)
DEMO_AUTO_APPLY_ON_RUN = env_bool("DEMO_AUTO_APPLY_ON_RUN", False)
DEMO_RESET_ON_START = env_bool("DEMO_RESET_ON_START", True)
DEMO_FORCE_VISIBLE_CHANGES = env_bool("DEMO_FORCE_VISIBLE_CHANGES", True)
DEMO_PROPOSAL_CHANGE_PERCENT = max(
    0.03,
    min(0.30, env_float("DEMO_PROPOSAL_CHANGE_PERCENT", 0.15)),
)
DEMO_PROPOSAL_MAX_CHANGE_PERCENT = max(
    DEMO_PROPOSAL_CHANGE_PERCENT,
    min(0.30, env_float("DEMO_PROPOSAL_MAX_CHANGE_PERCENT", 0.20)),
)

DEFAULT_DEMO_PRODUCTS: list[dict[str, Any]] = [
    {
        "sku": "AA1200",
        "name": "Pin Sạc AA 1.2V Ni-MH 1200mAh",
        "description": (
            "Pin sạc AA BESTON model AA1200, dung lượng 1200mAh, điện áp 1.2V, "
            "phù hợp micro, đồ chơi, chuột, đèn flash và thiết bị gia dụng."
        ),
        "base_cost": 33_000,
        "current_price": 52_000,
        "keywords": "beston aa1200 pin sac aa nimh 1200mah 1.2v combo 4 pin",
        "inventory": 240,
    },
    {
        "sku": "AA2000",
        "name": "Pin Sạc AA 1.2V Ni-MH 2000mAh",
        "description": (
            "Pin sạc AA BESTON model AA2000, dung lượng 2000mAh, điện áp 1.2V, "
            "tự xả thấp và có thể sạc lại nhiều chu kỳ cho thiết bị cần năng lượng cao."
        ),
        "base_cost": 51_000,
        "current_price": 80_000,
        "keywords": "beston aa2000 pin sac aa nimh 2000mah 1.2v combo 4 pin",
        "inventory": 180,
    },
    {
        "sku": "BTCSC24-C8022B",
        "name": "Sạc Pin AA & AAA 1.2V Ni-MH 4 Khe C8022B",
        "description": (
            "Sạc pin BESTON C8022B 4 khe, công suất 5W, cổng USB-A, hỗ trợ AA/AAA "
            "1.2V Ni-MH với bảo vệ quá tải, quá dòng và ngắn mạch."
        ),
        "base_cost": 29_000,
        "current_price": 46_000,
        "keywords": "beston c8022b sac pin aa aaa nimh 4 khe usb-a",
        "inventory": 96,
    },
    {
        "sku": "BTCSCA-C9012",
        "name": "Sạc Pin AA & AAA 1.2V Ni-MH 4 Khe C9012",
        "description": (
            "Sạc pin BESTON C9012 4 khe, đầu vào 5V/2A, sạc nhanh QC2.0, "
            "đèn báo LED và tương thích pin AA/AAA 1.2V Ni-MH."
        ),
        "base_cost": 90_000,
        "current_price": 140_000,
        "keywords": "beston c9012 sac nhanh qc2.0 aa aaa nimh 4 khe",
        "inventory": 64,
    },
    {
        "sku": "BTCSCA-C9025L",
        "name": "Sạc Pin AA & AAA 1.2V Ni-MH LCD 12 Khe C9025L",
        "description": (
            "Sạc pin BESTON C9025L 12 khe độc lập, màn hình LCD, sạc nhanh QC2.0, "
            "cổng USB-C/Micro USB và tương thích AA/AAA 1.2V Ni-MH."
        ),
        "base_cost": 205_000,
        "current_price": 320_000,
        "keywords": "beston c9025l sac pin lcd 12 khe aa aaa nimh usb-c",
        "inventory": 42,
    },
]


class DemoAPIError(ValueError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class DifyWorkflowError(RuntimeError):
    pass


def parse_positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise DemoAPIError(400, f"{field_name} must be a positive integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        parsed = int(value)
    elif isinstance(value, str):
        if value.strip().startswith("-"):
            raise DemoAPIError(400, f"{field_name} must be a positive integer")
        digits = re.sub(r"[^\d]", "", value)
        if not digits:
            raise DemoAPIError(400, f"{field_name} must be a positive integer")
        parsed = int(digits)
    else:
        raise DemoAPIError(400, f"{field_name} must be a positive integer")
    if parsed <= 0:
        raise DemoAPIError(400, f"{field_name} must be greater than 0")
    return parsed


def parse_non_negative_int(value: Any, field_name: str, default: int = 0) -> int:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        raise DemoAPIError(400, f"{field_name} must be a non-negative integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        parsed = int(value)
    elif isinstance(value, str):
        if value.strip().startswith("-"):
            raise DemoAPIError(400, f"{field_name} must be a non-negative integer")
        digits = re.sub(r"[^\d]", "", value)
        if digits == "":
            raise DemoAPIError(400, f"{field_name} must be a non-negative integer")
        parsed = int(digits)
    else:
        raise DemoAPIError(400, f"{field_name} must be a non-negative integer")
    if parsed < 0:
        raise DemoAPIError(400, f"{field_name} must be greater than or equal to 0")
    return parsed


def normalize_sku(value: Any) -> str:
    sku = str(value or "").strip().upper()
    if not sku:
        raise DemoAPIError(400, "sku is required")
    if not re.fullmatch(r"[A-Z0-9._-]{2,64}", sku):
        raise DemoAPIError(400, "sku may only contain letters, numbers, dot, underscore or dash")
    return sku


def normalize_product_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sku = normalize_sku(payload.get("sku"))
    name = str(payload.get("name") or "").strip()
    if not name:
        raise DemoAPIError(400, "name is required")
    base_cost = parse_positive_int(payload.get("base_cost"), "base_cost")
    current_price = parse_positive_int(payload.get("current_price"), "current_price")
    return {
        "sku": sku,
        "name": name,
        "description": str(payload.get("description") or "").strip(),
        "base_cost": base_cost,
        "current_price": current_price,
        "keywords": str(payload.get("keywords") or "").strip(),
        "inventory": parse_non_negative_int(payload.get("inventory"), "inventory"),
    }


def decode_json_field(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default


def normalize_market_data(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    candidates = [
        payload.get("market_data"),
        payload.get("market_sources"),
        payload.get("sources"),
        payload.get("prices"),
        payload.get("competitors"),
    ]
    for candidate in candidates:
        parsed = decode_json_field(candidate, None)
        if isinstance(parsed, dict):
            if parsed.get("prices") and not parsed.get("source_type"):
                parsed["source_type"] = "dify_tavily"
            return parsed
        if isinstance(parsed, list):
            return {"source_type": "dify_tavily", "prices": parsed}
    return {}


def market_prices(market_data: dict[str, Any]) -> list[dict[str, Any]]:
    prices = market_data.get("prices")
    return [item for item in prices if isinstance(item, dict)] if isinstance(prices, list) else []


def unique_market_urls(prices: list[dict[str, Any]]) -> set[str]:
    urls: set[str] = set()
    for item in prices:
        url = str(item.get("url") or item.get("link") or "").strip()
        if url:
            urls.add(url.split("?", 1)[0].rstrip("/"))
    return urls


def first_market_price(prices: list[dict[str, Any]]) -> int | None:
    for item in prices:
        raw_price = item.get("price") or item.get("value") or item.get("current_price")
        try:
            price = parse_positive_int(raw_price, "market_price")
        except DemoAPIError:
            continue
        if price > 0:
            return price
    return None


class DemoStore:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self, *, seed: bool = True) -> None:
        parent = Path(self.db_path).expanduser().parent
        if str(parent) not in {"", "."}:
            parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS demo_products (
                    sku TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    base_cost INTEGER NOT NULL,
                    current_price INTEGER NOT NULL,
                    keywords TEXT DEFAULT '',
                    inventory INTEGER DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS demo_price_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sku TEXT NOT NULL,
                    old_price INTEGER NOT NULL,
                    new_price INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    guardrail_note TEXT DEFAULT '',
                    source TEXT DEFAULT 'local_agent',
                    status TEXT DEFAULT 'applied',
                    market_data TEXT DEFAULT '{}',
                    resolved_at TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_demo_price_events_sku_time
                    ON demo_price_events (sku, created_at DESC);
                """
            )
            self._ensure_event_columns(conn)
            count = conn.execute("SELECT COUNT(*) AS count FROM demo_products").fetchone()["count"]
        if seed and count == 0:
            for product in DEFAULT_DEMO_PRODUCTS:
                self.upsert_product(product)

    def reset_demo_data(self) -> None:
        """Reset catalog and activity to the BESTON demo baseline."""
        self.init_db(seed=False)
        with self.connect() as conn:
            conn.execute("DELETE FROM demo_price_events")
            conn.execute("DELETE FROM demo_products")
        for product in DEFAULT_DEMO_PRODUCTS:
            self.upsert_product(product)

    @staticmethod
    def _ensure_event_columns(conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(demo_price_events)").fetchall()}
        migrations = {
            "status": "ALTER TABLE demo_price_events ADD COLUMN status TEXT DEFAULT 'applied'",
            "market_data": "ALTER TABLE demo_price_events ADD COLUMN market_data TEXT DEFAULT '{}'",
            "resolved_at": "ALTER TABLE demo_price_events ADD COLUMN resolved_at TEXT",
        }
        for column, statement in migrations.items():
            if column not in columns:
                conn.execute(statement)

    def upsert_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        product = normalize_product_payload(payload)
        updated_at = utc_now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO demo_products (
                    sku, name, description, base_cost, current_price,
                    keywords, inventory, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sku) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    base_cost = excluded.base_cost,
                    current_price = excluded.current_price,
                    keywords = excluded.keywords,
                    inventory = excluded.inventory,
                    updated_at = excluded.updated_at
                """,
                (
                    product["sku"],
                    product["name"],
                    product["description"],
                    product["base_cost"],
                    product["current_price"],
                    product["keywords"],
                    product["inventory"],
                    updated_at,
                ),
            )
        return self.get_product(product["sku"]) or product

    def ensure_product_from_agent_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        sku = normalize_sku(payload.get("sku"))
        existing = self.get_product(sku)
        if existing is not None:
            return existing

        new_price = parse_positive_int(
            payload.get("new_price") or payload.get("price") or payload.get("recommended_price"),
            "new_price",
        )
        old_price = parse_positive_int(payload.get("old_price") or new_price, "old_price")
        base_cost = payload.get("base_cost")
        if base_cost in (None, ""):
            base_cost = int(min(old_price, new_price) * 0.65)
        product_payload = {
            "sku": sku,
            "name": str(payload.get("name") or sku).strip(),
            "description": str(payload.get("description") or "").strip(),
            "base_cost": base_cost,
            "current_price": old_price,
            "keywords": str(payload.get("keywords") or "").strip(),
            "inventory": payload.get("inventory") or 0,
        }
        return self.upsert_product(product_payload)

    def get_product(self, sku: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT p.*,
                       e.id AS event_id,
                       e.old_price AS event_old_price,
                       e.new_price AS event_new_price,
                       e.action AS event_action,
                       e.reason AS event_reason,
                       e.confidence AS event_confidence,
                       e.guardrail_note AS event_guardrail_note,
                       e.source AS event_source,
                       e.status AS event_status,
                       e.market_data AS event_market_data,
                       e.resolved_at AS event_resolved_at,
                       e.created_at AS event_created_at
                FROM demo_products p
                LEFT JOIN demo_price_events e
                    ON e.id = (
                        SELECT id
                        FROM demo_price_events
                        WHERE sku = p.sku
                        ORDER BY datetime(created_at) DESC, id DESC
                        LIMIT 1
                    )
                WHERE p.sku = ?
                """,
                (normalize_sku(sku),),
            ).fetchone()
        return self._row_to_product(row) if row else None

    def list_products(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.*,
                       e.id AS event_id,
                       e.old_price AS event_old_price,
                       e.new_price AS event_new_price,
                       e.action AS event_action,
                       e.reason AS event_reason,
                       e.confidence AS event_confidence,
                       e.guardrail_note AS event_guardrail_note,
                       e.source AS event_source,
                       e.status AS event_status,
                       e.market_data AS event_market_data,
                       e.resolved_at AS event_resolved_at,
                       e.created_at AS event_created_at
                FROM demo_products p
                LEFT JOIN demo_price_events e
                    ON e.id = (
                        SELECT id
                        FROM demo_price_events
                        WHERE sku = p.sku
                        ORDER BY datetime(created_at) DESC, id DESC
                        LIMIT 1
                    )
                ORDER BY p.sku ASC
                """
            ).fetchall()
        return [self._row_to_product(row) for row in rows]

    def delete_product(self, sku: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM demo_products WHERE sku = ?", (normalize_sku(sku),))
            conn.execute("DELETE FROM demo_price_events WHERE sku = ?", (normalize_sku(sku),))
        return cur.rowcount > 0

    def record_price_event(
        self,
        sku: str,
        *,
        old_price: int,
        new_price: int,
        action: str,
        reason: str,
        confidence: str,
        guardrail_note: str = "",
        source: str = "local_agent",
        status: str = "applied",
        market_data: dict[str, Any] | None = None,
        apply_price: bool | None = None,
    ) -> dict[str, Any]:
        sku = normalize_sku(sku)
        if action not in {"increase", "decrease", "hold"}:
            action = "hold"
        if confidence not in {"high", "medium", "low"}:
            confidence = "low"
        if status not in {"pending", "applied", "rejected"}:
            status = "pending"
        apply_price = status == "applied" if apply_price is None else apply_price
        created_at = utc_now_iso()
        resolved_at = created_at if status in {"applied", "rejected"} else None
        market_payload = json.dumps(market_data or {}, ensure_ascii=False)
        with self.connect() as conn:
            if apply_price:
                conn.execute(
                    """
                    UPDATE demo_products
                    SET current_price = ?, updated_at = ?
                    WHERE sku = ?
                    """,
                    (int(new_price), created_at, sku),
                )
            cur = conn.execute(
                """
                INSERT INTO demo_price_events (
                    sku, old_price, new_price, action, reason,
                    confidence, guardrail_note, source, status,
                    market_data, resolved_at, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sku,
                    int(old_price),
                    int(new_price),
                    action,
                    str(reason or "").strip() or "Không có lý do từ agent.",
                    confidence,
                    str(guardrail_note or "").strip() or "OK",
                    source,
                    status,
                    market_payload,
                    resolved_at,
                    created_at,
                ),
            )
            event_id = int(cur.lastrowid)
        return self.get_event(event_id)

    def update_price_from_api(
        self,
        sku: str,
        new_price: int,
        *,
        reason: str = "Website API cập nhật giá từ agent.",
        confidence: str = "medium",
        guardrail_note: str = "External update",
        source: str = "website_api",
    ) -> dict[str, Any]:
        product = self.get_product(sku)
        if product is None:
            raise DemoAPIError(404, f"SKU {sku} not found")
        old_price = int(product["current_price"])
        action = "hold" if old_price == new_price else ("increase" if new_price > old_price else "decrease")
        self.record_price_event(
            sku,
            old_price=old_price,
            new_price=int(new_price),
            action=action,
            reason=reason,
            confidence=confidence,
            guardrail_note=guardrail_note,
            source=source,
        )
        return self.get_product(sku)

    def apply_agent_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        product = self.ensure_product_from_agent_payload(payload)
        old_price = parse_positive_int(payload.get("old_price") or product["current_price"], "old_price")
        new_price = parse_positive_int(
            payload.get("new_price") or payload.get("price") or payload.get("recommended_price"),
            "new_price",
        )
        action = str(payload.get("action") or "").strip().lower()
        if action not in {"increase", "decrease", "hold"}:
            action = "hold" if new_price == old_price else ("increase" if new_price > old_price else "decrease")
        status = str(payload.get("status") or "pending").strip().lower()
        if status not in {"pending", "applied", "rejected"}:
            status = "pending"
        apply_price = payload.get("apply_price")
        if isinstance(apply_price, str):
            apply_price = apply_price.strip().lower() in {"1", "true", "yes", "on"}
        elif apply_price is not None:
            apply_price = bool(apply_price)
        self.record_price_event(
            product["sku"],
            old_price=old_price,
            new_price=new_price,
            action=action,
            reason=str(payload.get("reason") or "Agent đã gửi giá mới về website.").strip(),
            confidence=str(payload.get("confidence") or "medium").strip().lower(),
            guardrail_note=str(payload.get("guardrail_note") or payload.get("guardrails") or "OK").strip(),
            source=str(payload.get("source") or "dify_webhook").strip(),
            status=status,
            market_data=normalize_market_data(payload),
            apply_price=apply_price if apply_price is not None else False,
        )
        return self.get_product(product["sku"])

    def approve_event(self, event_id: int) -> dict[str, Any]:
        event = self.get_event(event_id)
        if event["status"] != "pending":
            raise DemoAPIError(409, f"Event {event_id} is not pending")
        resolved_at = utc_now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE demo_products
                SET current_price = ?, updated_at = ?
                WHERE sku = ?
                """,
                (int(event["new_price"]), resolved_at, event["sku"]),
            )
            conn.execute(
                """
                UPDATE demo_price_events
                SET status = 'applied', resolved_at = ?
                WHERE id = ?
                """,
                (resolved_at, event_id),
            )
        return self.get_product(event["sku"])

    def reject_event(self, event_id: int) -> dict[str, Any]:
        event = self.get_event(event_id)
        if event["status"] != "pending":
            raise DemoAPIError(409, f"Event {event_id} is not pending")
        resolved_at = utc_now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE demo_price_events
                SET status = 'rejected', resolved_at = ?
                WHERE id = ?
                """,
                (resolved_at, event_id),
            )
        return self.get_product(event["sku"])

    def get_event(self, event_id: int) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM demo_price_events WHERE id = ?",
                (event_id,),
            ).fetchone()
        if row is None:
            raise DemoAPIError(404, f"Event {event_id} not found")
        return self._row_to_event(row)

    def list_events(self, limit: int = 30) -> list[dict[str, Any]]:
        limit = min(max(int(limit), 1), 100)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT e.*, p.name
                FROM demo_price_events e
                LEFT JOIN demo_products p ON p.sku = e.sku
                ORDER BY datetime(e.created_at) DESC, e.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> dict[str, Any]:
        event = dict(row)
        event["old_price"] = int(event["old_price"])
        event["new_price"] = int(event["new_price"])
        event["status"] = event.get("status") or "applied"
        event["market_data"] = decode_json_field(event.get("market_data"), {})
        return event

    @staticmethod
    def _row_to_product(row: sqlite3.Row) -> dict[str, Any]:
        product = {
            "sku": row["sku"],
            "name": row["name"],
            "description": row["description"],
            "base_cost": int(row["base_cost"]),
            "current_price": int(row["current_price"]),
            "keywords": row["keywords"],
            "inventory": int(row["inventory"]),
            "updated_at": row["updated_at"],
        }
        event_id = row["event_id"]
        if event_id is not None:
            product["last_event"] = {
                "id": event_id,
                "old_price": int(row["event_old_price"]),
                "new_price": int(row["event_new_price"]),
                "action": row["event_action"],
                "reason": row["event_reason"],
                "confidence": row["event_confidence"],
                "guardrail_note": row["event_guardrail_note"],
                "source": row["event_source"],
                "status": row["event_status"] or "applied",
                "market_data": decode_json_field(row["event_market_data"], {}),
                "resolved_at": row["event_resolved_at"],
                "created_at": row["event_created_at"],
            }
        else:
            product["last_event"] = None
        return product


@dataclass
class DemoAgent:
    store: DemoStore
    market_searcher: MarketSearcher | None = search_market_price
    use_real_market_search: bool = True

    def run_one(self, sku: str) -> dict[str, Any]:
        product = self.store.get_product(sku)
        if product is None:
            raise DemoAPIError(404, f"SKU {sku} not found")

        market_data = self._collect_market_data(product)
        recommended_price, reason, confidence = self._recommend(product, market_data)
        guardrail_result = validate_price_detailed(product, recommended_price)
        new_price = guardrail_result.adjusted_price
        old_price = int(product["current_price"])
        action = "hold" if new_price == old_price else ("increase" if new_price > old_price else "decrease")
        guardrail_note = "OK" if not guardrail_result.errors else " | ".join(guardrail_result.errors)

        event = self.store.record_price_event(
            product["sku"],
            old_price=old_price,
            new_price=new_price,
            action=action,
            reason=reason,
            confidence=confidence,
            guardrail_note=guardrail_note,
            source="local_agent",
            status="pending",
            market_data=market_data,
            apply_price=False,
        )
        return {
            "sku": product["sku"],
            "product": self.store.get_product(product["sku"]),
            "event": event,
            "market_data": market_data,
            "recommended_price": int(recommended_price),
            "guardrail_note": guardrail_note,
        }

    def run_all(self) -> list[dict[str, Any]]:
        return [self.run_one(product["sku"]) for product in self.store.list_products()]

    def collect_market_data(self, product: dict[str, Any]) -> dict[str, Any]:
        return self._collect_market_data(product)

    def _collect_market_data(self, product: dict[str, Any]) -> dict[str, Any]:
        if self.use_real_market_search and self.market_searcher is not None:
            query = self._market_query(product)
            try:
                market_data = self.market_searcher(query)
            except Exception as exc:
                logger.warning("[%s] Real market search failed, using fallback: %s", product["sku"], exc)
                return self._estimate_market(
                    product,
                    note=(
                        "Không lấy được giá thật qua OpenAI web search; đang fallback dữ liệu mô phỏng "
                        f"để demo không bị gián đoạn. Lỗi: {exc}"
                    ),
                    source_type="fallback_simulated",
                )
            if market_data.get("prices"):
                market_data["source_type"] = "real_market_search"
                market_data["query"] = query
                return market_data
            return self._estimate_market(
                product,
                note=(
                    "OpenAI web search chạy thành công nhưng không tìm đủ giá thật đáng tin cậy; "
                    "đang fallback dữ liệu mô phỏng để tạo proposal."
                ),
                source_type="fallback_simulated",
            )
        return self._estimate_market(product)

    @staticmethod
    def _market_query(product: dict[str, Any]) -> str:
        pieces = [
            "BESTON",
            str(product.get("name") or ""),
            str(product.get("sku") or ""),
            str(product.get("keywords") or ""),
        ]
        return " ".join(piece for piece in pieces if piece).strip()

    def _estimate_market(
        self,
        product: dict[str, Any],
        *,
        note: str | None = None,
        source_type: str = "simulated",
    ) -> dict[str, Any]:
        current = int(product["current_price"])
        text = " ".join(
            [
                product.get("name", ""),
                product.get("description", ""),
                product.get("keywords", ""),
            ]
        ).lower()
        signal = 0.0
        if any(term in text for term in ["2000mah", "aa2000", "dung lượng cao", "năng lượng cao"]):
            signal += 0.05
        if any(term in text for term in ["lcd", "12 khe", "c9025l", "usb-c"]):
            signal += 0.07
        if any(term in text for term in ["qc2.0", "sạc nhanh", "sac nhanh", "c9012"]):
            signal += 0.04
        if any(term in text for term in ["usb-a", "c8022b", "4 khe"]):
            signal += 0.02
        if any(term in text for term in ["1200mah", "aa1200", "combo 4 pin"]):
            signal += 0.01
        if any(term in text for term in ["xa kho", "xả kho", "cu", "cũ", "clearance"]):
            signal -= 0.07

        inventory = int(product.get("inventory") or 0)
        if inventory >= 40:
            signal -= 0.04
        elif inventory <= 5:
            signal += 0.03

        deterministic_noise = ((sum(ord(char) for char in product["sku"]) % 9) - 4) / 100
        average_price = max(1_000, int(current * (1 + signal + deterministic_noise)))
        prices = [
            {
                "source": "Shopee",
                "price": int(average_price * 0.96),
                "title": f"{product['name']} - gian hàng đối thủ",
                "url": "https://shopee.vn/search?keyword=demo",
            },
            {
                "source": "Lazada",
                "price": int(average_price * 1.02),
                "title": f"{product['name']} chính hãng",
                "url": "https://www.lazada.vn/catalog/?q=demo",
            },
            {
                "source": "Website bán lẻ",
                "price": int(average_price * 1.05),
                "title": f"Bảng giá {product['name']}",
                "url": "https://example.com/demo-market-price",
            },
        ]
        return {
            "product": product["name"],
            "prices": prices,
            "average_price": int(sum(item["price"] for item in prices) / len(prices)),
            "lowest_price": min(item["price"] for item in prices),
            "highest_price": max(item["price"] for item in prices),
            "source_type": source_type,
            "note": note or "Dữ liệu mô phỏng để demo UI; cấu hình OPENAI_API_KEY để lấy giá thật.",
        }

    def _recommend(self, product: dict[str, Any], market_data: dict[str, Any]) -> tuple[int, str, str]:
        current = int(product["current_price"])
        base_cost = int(product["base_cost"])
        market_avg = int(market_data["average_price"])
        inventory = int(product.get("inventory") or 0)

        target = int(market_avg * 0.98)
        if inventory >= 40:
            target = int(target * 0.97)
        elif inventory <= 5:
            target = int(target * 1.02)

        if target < base_cost:
            target = int(base_cost * 1.25)

        diff_pct = (target - current) / current
        if abs(diff_pct) < 0.025:
            target = current
            reason = (
                "Giá thị trường đang gần giá hiện tại, agent giữ giá để tránh thay đổi không cần thiết. "
                "Biên lợi nhuận vẫn nằm trong vùng an toàn."
            )
            confidence = "medium"
        elif diff_pct > 0:
            reason = (
                "Mặt bằng giá tham chiếu cao hơn giá hiện tại, agent đề xuất tăng có kiểm soát. "
                "Mức tăng vẫn đi qua guardrails để giữ cạnh tranh."
            )
            confidence = "medium" if diff_pct < 0.12 else "high"
        else:
            reason = (
                "Giá tham chiếu thấp hơn giá hiện tại, agent đề xuất giảm nhẹ để cải thiện cạnh tranh. "
                "Guardrails vẫn bảo vệ margin tối thiểu."
            )
            confidence = "medium"

        return target, reason, confidence


@dataclass
class DifyWorkflowClient:
    api_key: str | None = None
    api_base_url: str = DEFAULT_DIFY_API_BASE_URL
    user: str = "pricing-web-demo"
    input_name: str = "products_json"
    input_format: str = "json_string"
    timeout: int = 100
    session: Any | None = None

    @classmethod
    def from_env(cls, *, session: Any | None = None) -> "DifyWorkflowClient":
        load_local_env()
        return cls(
            api_key=os.environ.get("DIFY_API_KEY") or None,
            api_base_url=os.environ.get("DIFY_API_BASE_URL", DEFAULT_DIFY_API_BASE_URL),
            user=os.environ.get("DIFY_USER", "pricing-web-demo"),
            input_name=os.environ.get("DIFY_INPUT_NAME", "products_json"),
            input_format=os.environ.get("DIFY_INPUT_FORMAT", "json_string"),
            timeout=int(os.environ.get("DIFY_TIMEOUT", "100")),
            session=session,
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def run_products(self, products: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.configured:
            raise DifyWorkflowError("DIFY_API_KEY is not configured")
        if not products:
            raise DifyWorkflowError("No products to send to Dify")

        payload = {
            "inputs": self._build_inputs(products),
            "response_mode": "blocking",
            "user": self.user,
        }
        url = f"{self.api_base_url.rstrip('/')}/workflows/run"
        try:
            response = self._http().post(
                url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except Exception as exc:
            raise DifyWorkflowError(f"Dify workflow request failed: {exc}") from exc

        try:
            result = response.json()
        except ValueError as exc:
            raise DifyWorkflowError("Dify returned a non-JSON response") from exc

        data = result.get("data") if isinstance(result, dict) else None
        if isinstance(data, dict) and data.get("status") not in {None, "succeeded"}:
            raise DifyWorkflowError(data.get("error") or f"Dify workflow status: {data.get('status')}")
        return result

    def _build_inputs(self, products: list[dict[str, Any]]) -> dict[str, Any]:
        clean_products = [self._to_dify_product(product) for product in products]
        products_json = json.dumps(clean_products, ensure_ascii=False)
        inputs: dict[str, Any] = {
            "products_json": products_json,
            "products_count": len(clean_products),
            "first_sku": clean_products[0]["sku"] if clean_products else "",
        }
        if self.input_format == "array":
            value: Any = clean_products
        elif self.input_format == "object":
            value = {"products": clean_products}
        else:
            value = products_json
        if self.input_name != "products_json":
            inputs[self.input_name] = value
        return inputs

    def _http(self):
        if self.session is not None:
            return self.session
        import requests

        return requests

    @staticmethod
    def _to_dify_product(product: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "sku": product["sku"],
            "name": product["name"],
            "description": product.get("description", ""),
            "base_cost": int(product["base_cost"]),
            "current_price": int(product["current_price"]),
            "keywords": product.get("keywords", ""),
            "inventory": int(product.get("inventory") or 0),
        }
        if isinstance(product.get("market_data"), dict):
            payload["market_data"] = product["market_data"]
        return payload


def extract_dify_outputs(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data") if isinstance(response, dict) else {}
    outputs = data.get("outputs") if isinstance(data, dict) else {}
    return outputs if isinstance(outputs, dict) else {}


def extract_agent_results(value: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    def visit(candidate: Any) -> None:
        parsed = candidate
        if isinstance(parsed, str):
            stripped = parsed.strip()
            if not stripped:
                return
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return
        if isinstance(parsed, list):
            for item in parsed:
                visit(item)
            return
        if not isinstance(parsed, dict):
            return

        has_price = any(key in parsed for key in ("new_price", "price", "recommended_price"))
        if parsed.get("sku") and has_price:
            results.append(parsed)
            return

        for key in ("results", "result", "products", "items", "data", "output"):
            if key in parsed:
                visit(parsed[key])

    visit(value)
    return results


def run_dify_and_apply(
    store: DemoStore,
    dify_client: DifyWorkflowClient,
    products: list[dict[str, Any]],
    market_data_by_sku: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    response = dify_client.run_products(products)
    outputs = extract_dify_outputs(response)
    agent_results = extract_agent_results(outputs)
    expected_skus = {normalize_sku(product["sku"]) for product in products}
    ignored_results = [
        result for result in agent_results
        if normalize_sku(result.get("sku")) not in expected_skus
    ]
    agent_results = [
        result for result in agent_results
        if normalize_sku(result.get("sku")) in expected_skus
    ]
    enriched_results = [
        attach_fallback_market_data(result, market_data_by_sku or {})
        for result in agent_results
    ]
    products_by_sku = {normalize_sku(product["sku"]): product for product in products}
    enriched_results = [
        mark_demo_auto_apply(
            annotate_unbacked_dify_proposal(
                force_visible_demo_proposal(
                    polish_demo_proposal(result, products_by_sku.get(normalize_sku(result.get("sku")))),
                    products_by_sku.get(normalize_sku(result.get("sku"))),
                ),
                products_by_sku.get(normalize_sku(result.get("sku"))),
            )
        )
        for result in enriched_results
    ]
    proposed_products = [store.apply_agent_result(result) for result in enriched_results]
    return {
        "mode": "dify",
        "products": proposed_products,
        "proposal_count": len(proposed_products),
        "applied_count": len(proposed_products),
        "ignored_count": len(ignored_results),
        "ignored_skus": [normalize_sku(result.get("sku")) for result in ignored_results],
        "market_data_count": len(market_data_by_sku or {}),
        "outputs": outputs,
        "workflow_run_id": response.get("workflow_run_id") or response.get("data", {}).get("id"),
        "raw_status": response.get("data", {}).get("status"),
        "demo_single_source_proposals": DEMO_SINGLE_SOURCE_PROPOSALS,
        "demo_auto_apply_on_run": DEMO_AUTO_APPLY_ON_RUN,
        "demo_force_visible_changes": DEMO_FORCE_VISIBLE_CHANGES,
        "demo_proposal_change_percent": DEMO_PROPOSAL_CHANGE_PERCENT,
    }


def attach_fallback_market_data(
    result: dict[str, Any],
    market_data_by_sku: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if normalize_market_data(result):
        return result
    sku = str(result.get("sku") or "").strip().upper()
    market_data = market_data_by_sku.get(sku)
    if not market_data:
        return result
    merged = dict(result)
    merged["market_data"] = market_data
    return merged


def polish_demo_proposal(result: dict[str, Any], product: dict[str, Any] | None) -> dict[str, Any]:
    """Turn a real single-source market signal into a pending demo proposal.

    Dify remains the source of market evidence. This layer only makes the website
    demo more legible by proposing a guarded draft price when Dify found at least
    one real URL but held because its production threshold requires more sources.
    """
    if not DEMO_SINGLE_SOURCE_PROPOSALS or not product:
        return result

    market_data = normalize_market_data(result)
    prices = market_prices(market_data)
    source_count = len(unique_market_urls(prices))
    if source_count < 1:
        return result

    old_price = parse_positive_int(result.get("old_price") or product["current_price"], "old_price")
    current_new_price = parse_positive_int(
        result.get("new_price") or result.get("price") or result.get("recommended_price") or old_price,
        "new_price",
    )
    current_action = str(result.get("action") or "").strip().lower()
    if current_action in {"increase", "decrease"} and current_new_price != old_price:
        return result

    anchor = parse_non_negative_int(market_data.get("market_anchor"), "market_anchor", default=0)
    if anchor <= 0:
        anchor = first_market_price(prices) or 0
    if anchor <= 0:
        return result

    if anchor > old_price:
        demo_target = int(old_price * (1 + DEMO_PROPOSAL_CHANGE_PERCENT))
    elif anchor < old_price:
        demo_target = int(old_price * (1 - DEMO_PROPOSAL_CHANGE_PERCENT))
    else:
        demo_target = old_price
    blended_target = int(anchor * 0.55 + old_price * 0.45)
    target = demo_target if demo_target != old_price else blended_target
    guardrail = validate_price_detailed(
        product,
        target,
        max_daily_change_percent=DEMO_PROPOSAL_MAX_CHANGE_PERCENT,
    )
    new_price = int(guardrail.adjusted_price)
    if new_price == old_price:
        return result

    action = "increase" if new_price > old_price else "decrease"
    source_word = "URL" if source_count == 1 else "URL"
    note_prefix = (
        f"{source_count} {source_word} giá thật, proposal demo cần duyệt"
        if source_count == 1
        else f"{source_count} {source_word} giá thật"
    )
    guardrail_notes = [note_prefix, *guardrail.errors]
    evidence = prices[0]
    evidence_price = parse_positive_int(
        evidence.get("price") or evidence.get("value") or anchor,
        "market_price",
    )
    reason = (
        f"Dify/Tavily tìm được {source_count} nguồn giá thật. "
        f"Nguồn nổi bật: {evidence.get('source') or 'market'} ở mức {evidence_price:,}đ. "
        "Website tạo proposal pending cho demo; người vận hành vẫn cần approve trước khi áp giá."
    )

    polished_market_data = dict(market_data)
    polished_market_data["market_anchor"] = anchor
    polished_market_data["valid_source_count"] = source_count
    polished_market_data["demo_policy"] = "single_source_pending_proposal"
    polished_market_data["note"] = (
        "Demo mode: 1 nguồn có URL được dùng để tạo proposal pending; không tự áp giá."
        if source_count == 1
        else market_data.get("note") or "Filtered comparable competitor prices from Dify Tavily Search"
    )

    polished = dict(result)
    polished.update(
        {
            "old_price": old_price,
            "new_price": new_price,
            "action": action,
            "confidence": "medium" if source_count == 1 else str(result.get("confidence") or "high").lower(),
            "guardrail_note": " | ".join(guardrail_notes) if guardrail_notes else "OK",
            "reason": reason,
            "source": "dify_tavily_demo",
            "market_data": polished_market_data,
        }
    )
    if DEMO_AUTO_APPLY_ON_RUN:
        polished["status"] = "applied"
        polished["apply_price"] = True
    return polished


def demo_direction_for_sku(sku: str) -> int:
    normalized = normalize_sku(sku)
    if normalized in {"BTCSC24-C8022B", "BTCSCA-C9025L"}:
        return -1
    return 1


def force_visible_demo_proposal(result: dict[str, Any], product: dict[str, Any] | None) -> dict[str, Any]:
    """Create a visible guarded change when Dify returns only hold results.

    This is explicitly demo-only. It keeps the UI dynamic for live presentation
    while the reason and market note make clear that Dify did not provide enough
    structured market evidence for a production-grade recommendation.
    """
    if not DEMO_FORCE_VISIBLE_CHANGES or not product:
        return result

    old_price = parse_positive_int(result.get("old_price") or product["current_price"], "old_price")
    new_price = parse_positive_int(
        result.get("new_price") or result.get("price") or result.get("recommended_price") or old_price,
        "new_price",
    )
    action = str(result.get("action") or "").strip().lower()
    if new_price != old_price and action in {"increase", "decrease"}:
        return result

    market_data = normalize_market_data(result)
    prices = market_prices(market_data)
    source_count = len(unique_market_urls(prices))
    if source_count > 0:
        return result

    direction = demo_direction_for_sku(product["sku"])
    target = int(old_price * (1 + direction * DEMO_PROPOSAL_CHANGE_PERCENT))
    guardrail = validate_price_detailed(
        product,
        target,
        max_daily_change_percent=DEMO_PROPOSAL_MAX_CHANGE_PERCENT,
    )
    visible_price = int(guardrail.adjusted_price)
    if visible_price == old_price:
        return result

    visible_action = "increase" if visible_price > old_price else "decrease"
    demo_market_data = dict(market_data)
    demo_market_data.update(
        {
            "source_type": "dify_tavily_demo",
            "prices": prices,
            "market_anchor": parse_non_negative_int(market_data.get("market_anchor"), "market_anchor", default=0),
            "valid_source_count": source_count,
            "demo_policy": "visible_change_fallback",
            "note": (
                "Demo mode: Dify/Tavily chưa trả đủ nguồn giá có cấu trúc, "
                "website tạo biến động có guardrails để trình diễn approval flow."
            ),
        }
    )
    notes = ["Demo fallback để thấy biến động", *guardrail.errors]
    forced = dict(result)
    forced.update(
        {
            "old_price": old_price,
            "new_price": visible_price,
            "action": visible_action,
            "confidence": "medium",
            "guardrail_note": " | ".join(notes),
            "reason": (
                "Dify chưa trả đủ nguồn giá đối thủ có cấu trúc cho SKU này. "
                "Demo mode tạo một đề xuất có kiểm soát bằng guardrails để người xem thấy rõ luồng Run -> đổi giá -> activity."
            ),
            "source": "dify_tavily_demo",
            "market_data": demo_market_data,
        }
    )
    return forced


def annotate_unbacked_dify_proposal(result: dict[str, Any], product: dict[str, Any] | None) -> dict[str, Any]:
    """Mark AI price changes that do not include structured market URLs.

    Dify may return an increase/decrease even when the workflow output does not
    contain market_data.prices. The website should keep the proposal visible for
    demo, but it must not look like a sourced market recommendation.
    """
    if not product:
        return result

    market_data = normalize_market_data(result)
    if market_data.get("demo_policy") or market_prices(market_data):
        return result

    old_price = parse_positive_int(result.get("old_price") or product["current_price"], "old_price")
    new_price = parse_positive_int(
        result.get("new_price") or result.get("price") or result.get("recommended_price") or old_price,
        "new_price",
    )
    action = str(result.get("action") or "").strip().lower()
    if new_price == old_price or action not in {"increase", "decrease"}:
        return result

    annotated_market_data = dict(market_data)
    annotated_market_data.update(
        {
            "source_type": "dify_output",
            "prices": [],
            "market_anchor": 0,
            "valid_source_count": 0,
            "demo_policy": "ai_only_no_sources",
            "note": (
                "Dify trả đề xuất đổi giá nhưng chưa trả market_data.prices có URL nguồn thật. "
                "Proposal được giữ ở trạng thái pending để demo và cần kiểm tra trước khi approve."
            ),
        }
    )

    guardrail_note = str(result.get("guardrail_note") or "OK").strip()
    if guardrail_note.upper() == "OK":
        guardrail_note = "AI-only, chưa có URL nguồn"
    elif "chưa có URL nguồn" not in guardrail_note:
        guardrail_note = f"AI-only, chưa có URL nguồn | {guardrail_note}"

    annotated = dict(result)
    annotated.update(
        {
            "old_price": old_price,
            "new_price": new_price,
            "action": action,
            "confidence": "low",
            "guardrail_note": guardrail_note,
            "reason": (
                f"Dify đề xuất {'tăng' if action == 'increase' else 'giảm'} giá cho {product['name']} "
                "nhưng chưa kèm URL nguồn giá thị trường có cấu trúc. Website giữ proposal ở pending "
                "để demo luồng duyệt; chỉ approve khi đã kiểm tra nguồn hoặc khi Dify trả market sources."
            ),
            "source": "dify_ai_only",
            "market_data": annotated_market_data,
        }
    )
    return annotated


def mark_demo_auto_apply(result: dict[str, Any]) -> dict[str, Any]:
    if not DEMO_AUTO_APPLY_ON_RUN:
        return result
    try:
        old_price = parse_positive_int(result.get("old_price"), "old_price")
        new_price = parse_positive_int(
            result.get("new_price") or result.get("price") or result.get("recommended_price"),
            "new_price",
        )
    except DemoAPIError:
        return result
    if new_price == old_price:
        return result
    action = str(result.get("action") or "").strip().lower()
    if action not in {"increase", "decrease"}:
        action = "increase" if new_price > old_price else "decrease"
    marked = dict(result)
    marked["action"] = action
    marked["status"] = "applied"
    marked["apply_price"] = True
    marked.setdefault("source", "dify_tavily_demo")
    return marked


class DemoRequestHandler(BaseHTTPRequestHandler):
    server: "DemoHTTPServer"

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_common_headers()
        self.end_headers()

    def do_GET(self) -> None:
        try:
            path = urlparse(self.path).path
            if path == "/api/products":
                self._send_json({"products": self.server.store.list_products()})
                return
            if path == "/api/events":
                self._send_json({"events": self.server.store.list_events()})
                return
            if path == "/api/status":
                self._send_json(
                    {
                        "dify_configured": self.server.dify_client.configured,
                        "dify_base_url": self.server.dify_client.api_base_url,
                        "dify_input_name": self.server.dify_client.input_name,
                        "dify_input_format": self.server.dify_client.input_format,
                        "real_market_search_configured": bool(os.environ.get("OPENAI_API_KEY") or OPENAI_API_KEY),
                        "market_provider": "dify_tavily" if self.server.dify_client.configured else "local_openai",
                        "run_mode": "dify" if self.server.dify_client.configured else "local_demo",
                        "demo_reset_on_start": DEMO_RESET_ON_START,
                        "demo_single_source_proposals": DEMO_SINGLE_SOURCE_PROPOSALS,
                        "demo_auto_apply_on_run": DEMO_AUTO_APPLY_ON_RUN,
                        "demo_force_visible_changes": DEMO_FORCE_VISIBLE_CHANGES,
                        "demo_proposal_change_percent": DEMO_PROPOSAL_CHANGE_PERCENT,
                    }
                )
                return
            self._serve_static(path)
        except DemoAPIError as exc:
            self._send_json({"error": exc.message}, status=exc.status_code)
        except Exception as exc:  # pragma: no cover - defensive HTTP boundary
            self._send_json({"error": str(exc)}, status=500)

    def do_POST(self) -> None:
        try:
            path = urlparse(self.path).path
            if path == "/api/products":
                product = self.server.store.upsert_product(self._read_json())
                self._send_json({"product": product}, status=201)
                return
            if path == "/api/products/run-agent":
                products = self.server.store.list_products()
                if self.server.dify_client.configured:
                    self._send_json(run_dify_and_apply(self.server.store, self.server.dify_client, products))
                else:
                    self._send_json({"mode": "local_demo", "results": self.server.agent.run_all()})
                return
            match = re.fullmatch(r"/api/products/([^/]+)/run-agent", path)
            if match:
                product = self.server.store.get_product(unquote(match.group(1)))
                if product is None:
                    raise DemoAPIError(404, "SKU not found")
                if self.server.dify_client.configured:
                    self._send_json(run_dify_and_apply(self.server.store, self.server.dify_client, [product]))
                else:
                    self._send_json({"mode": "local_demo", "result": self.server.agent.run_one(product["sku"])})
                return
            if path == "/api/agent-results":
                product = self.server.store.apply_agent_result(self._read_json())
                self._send_json({"product": product})
                return
            match = re.fullmatch(r"/api/events/(\d+)/(approve|reject)", path)
            if match:
                event_id = int(match.group(1))
                product = (
                    self.server.store.approve_event(event_id)
                    if match.group(2) == "approve"
                    else self.server.store.reject_event(event_id)
                )
                self._send_json({"product": product})
                return
            raise DemoAPIError(404, "Not found")
        except DemoAPIError as exc:
            self._send_json({"error": exc.message}, status=exc.status_code)
        except DifyWorkflowError as exc:
            self._send_json({"error": str(exc)}, status=502)
        except Exception as exc:  # pragma: no cover - defensive HTTP boundary
            self._send_json({"error": str(exc)}, status=500)

    def do_PUT(self) -> None:
        try:
            path = urlparse(self.path).path
            match = re.fullmatch(r"/api/products/([^/]+)/price", path)
            if not match:
                raise DemoAPIError(404, "Not found")
            self._require_api_key()
            payload = self._read_json()
            price = parse_positive_int(payload.get("price") or payload.get("new_price"), "price")
            product = self.server.store.update_price_from_api(
                unquote(match.group(1)),
                price,
                reason=str(payload.get("reason") or "Agent đã cập nhật giá qua Website API.").strip(),
                confidence=str(payload.get("confidence") or "medium").strip().lower(),
                guardrail_note=str(payload.get("guardrail_note") or "Website API").strip(),
                source=str(payload.get("source") or "website_api").strip(),
            )
            self._send_json({"product": product})
        except DemoAPIError as exc:
            self._send_json({"error": exc.message}, status=exc.status_code)
        except DifyWorkflowError as exc:
            self._send_json({"error": str(exc)}, status=502)
        except Exception as exc:  # pragma: no cover - defensive HTTP boundary
            self._send_json({"error": str(exc)}, status=500)

    def do_DELETE(self) -> None:
        try:
            path = urlparse(self.path).path
            match = re.fullmatch(r"/api/products/([^/]+)", path)
            if not match:
                raise DemoAPIError(404, "Not found")
            deleted = self.server.store.delete_product(unquote(match.group(1)))
            if not deleted:
                raise DemoAPIError(404, "SKU not found")
            self._send_json({"deleted": True})
        except DemoAPIError as exc:
            self._send_json({"error": exc.message}, status=exc.status_code)
        except Exception as exc:  # pragma: no cover - defensive HTTP boundary
            self._send_json({"error": str(exc)}, status=500)

    def log_message(self, format: str, *args: Any) -> None:
        if not self.server.quiet:
            super().log_message(format, *args)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DemoAPIError(400, "Request body must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise DemoAPIError(400, "Request body must be a JSON object")
        return payload

    def _serve_static(self, path: str) -> None:
        if path in {"", "/"}:
            path = "/index.html"
        if path.startswith("/assets/"):
            relative = path.removeprefix("/assets/")
        else:
            relative = path.lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
            raise DemoAPIError(404, "Not found")
        if not target.is_file():
            raise DemoAPIError(404, "Not found")

        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self._send_common_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._send_common_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_common_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key")
        self.send_header("Cache-Control", "no-store")

    def _require_api_key(self) -> None:
        expected = self.server.api_key
        if not expected:
            return
        auth_header = self.headers.get("Authorization", "")
        bearer = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""
        api_key = self.headers.get("X-API-Key", "").strip()
        if expected not in {bearer, api_key}:
            raise DemoAPIError(401, "Invalid or missing API key")


class DemoHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        store: DemoStore,
        agent: DemoAgent,
        dify_client: DifyWorkflowClient,
        api_key: str | None = None,
        quiet: bool = False,
    ):
        super().__init__(server_address, handler_class)
        self.store = store
        self.agent = agent
        self.dify_client = dify_client
        self.api_key = api_key
        self.quiet = quiet


def create_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    db_path: str = DB_PATH,
    api_key: str | None = None,
    quiet: bool = False,
) -> DemoHTTPServer:
    store = DemoStore(db_path)
    store.init_db()
    if DEMO_RESET_ON_START:
        store.reset_demo_data()
    agent = DemoAgent(store)
    dify_client = DifyWorkflowClient.from_env()
    return DemoHTTPServer(
        (host, port),
        DemoRequestHandler,
        store=store,
        agent=agent,
        dify_client=dify_client,
        api_key=api_key,
        quiet=quiet,
    )


def create_server_with_fallback(
    *,
    host: str,
    port: int,
    db_path: str,
    api_key: str | None,
    quiet: bool,
    port_attempts: int = 20,
) -> tuple[DemoHTTPServer, int]:
    attempts = max(1, int(port_attempts))
    last_error: OSError | None = None
    for candidate_port in range(port, port + attempts):
        try:
            server = create_server(
                host=host,
                port=candidate_port,
                db_path=db_path,
                api_key=api_key,
                quiet=quiet,
            )
            return server, candidate_port
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise
            last_error = exc
    raise OSError(
        errno.EADDRINUSE,
        f"No available port in range {port}-{port + attempts - 1}",
    ) from last_error


def main(argv: list[str] | None = None) -> int:
    load_local_env()
    parser = argparse.ArgumentParser(description="AI Pricing Agent web demo")
    parser.add_argument("--host", default=os.environ.get("WEB_DEMO_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("WEB_DEMO_PORT", "8000")))
    parser.add_argument(
        "--port-attempts",
        type=int,
        default=int(os.environ.get("WEB_DEMO_PORT_ATTEMPTS", "20")),
        help="Number of consecutive ports to try when the requested port is busy.",
    )
    parser.add_argument("--db-path", default=os.environ.get("WEB_DEMO_DB_PATH", DB_PATH))
    parser.add_argument("--api-key", default=os.environ.get("DEMO_API_KEY"))
    parser.add_argument("--dify-api-key", default=os.environ.get("DIFY_API_KEY"))
    parser.add_argument("--dify-api-base-url", default=os.environ.get("DIFY_API_BASE_URL", DEFAULT_DIFY_API_BASE_URL))
    parser.add_argument("--dify-user", default=os.environ.get("DIFY_USER", "pricing-web-demo"))
    parser.add_argument("--dify-input-name", default=os.environ.get("DIFY_INPUT_NAME", "products_json"))
    parser.add_argument("--dify-input-format", default=os.environ.get("DIFY_INPUT_FORMAT", "json_string"))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if args.dify_api_key:
        os.environ["DIFY_API_KEY"] = args.dify_api_key
    os.environ["DIFY_API_BASE_URL"] = args.dify_api_base_url
    os.environ["DIFY_USER"] = args.dify_user
    os.environ["DIFY_INPUT_NAME"] = args.dify_input_name
    os.environ["DIFY_INPUT_FORMAT"] = args.dify_input_format

    server, actual_port = create_server_with_fallback(
        host=args.host,
        port=args.port,
        db_path=args.db_path,
        api_key=args.api_key,
        quiet=args.quiet,
        port_attempts=args.port_attempts,
    )
    if actual_port != args.port:
        print(f"Port {args.port} is busy; using {actual_port} instead.")
    print(f"AI Pricing Agent web demo: http://{args.host}:{actual_port}")
    if args.api_key:
        print("Website API auth: Bearer token enabled")
    if args.dify_api_key:
        print(f"Dify workflow API: connected via input '{args.dify_input_name}'")
    else:
        print("Dify workflow API: not configured; using local demo agent")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down web demo")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
