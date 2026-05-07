from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import DB_PATH


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class PricingDatabase:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        parent = Path(self.db_path).expanduser().parent
        if str(parent) not in {"", "."}:
            parent.mkdir(parents=True, exist_ok=True)

        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS competitor_prices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sku TEXT NOT NULL,
                    competitor TEXT NOT NULL,
                    price REAL NOT NULL,
                    url TEXT DEFAULT '',
                    raw_payload TEXT DEFAULT '{}',
                    scraped_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_competitor_prices_sku_time
                    ON competitor_prices (sku, scraped_at DESC);

                CREATE TABLE IF NOT EXISTS price_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sku TEXT NOT NULL,
                    old_price REAL NOT NULL,
                    recommended_price REAL NOT NULL,
                    new_price REAL NOT NULL,
                    reason TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    action TEXT DEFAULT '',
                    market_position TEXT DEFAULT '',
                    expected_margin_percent REAL,
                    guardrail_errors TEXT DEFAULT '[]',
                    approved INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending_approval',
                    decided_at TEXT NOT NULL,
                    applied_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_price_decisions_sku_time
                    ON price_decisions (sku, decided_at DESC);

                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sku TEXT NOT NULL,
                    price REAL NOT NULL,
                    source TEXT DEFAULT 'agent',
                    changed_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_price_history_sku_time
                    ON price_history (sku, changed_at DESC);
                """
            )

    def save_competitor_price(
        self,
        sku: str,
        competitor: str,
        price: float,
        url: str = "",
        raw_payload: dict[str, Any] | None = None,
        scraped_at: str | None = None,
    ) -> int:
        scraped_at = scraped_at or utc_now_iso()
        payload = json.dumps(raw_payload or {}, ensure_ascii=False)
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO competitor_prices
                    (sku, competitor, price, url, raw_payload, scraped_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (sku, competitor, float(price), url, payload, scraped_at),
            )
            return int(cur.lastrowid)

    def get_price_history(self, sku: str, days: int = 7) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT competitor, price, url, scraped_at
                FROM competitor_prices
                WHERE sku = ?
                  AND datetime(scraped_at) >= datetime('now', ?)
                ORDER BY datetime(scraped_at) DESC
                """,
                (sku, f"-{int(days)} days"),
            ).fetchall()
        return [
            {
                "competitor": row["competitor"],
                "price": row["price"],
                "url": row["url"],
                "time": row["scraped_at"],
            }
            for row in rows
        ]

    def save_decision(
        self,
        sku: str,
        old_price: float,
        new_price: float,
        reason: str,
        confidence: str,
        *,
        recommended_price: float | None = None,
        action: str = "",
        market_position: str = "",
        expected_margin_percent: float | None = None,
        guardrail_errors: list[str] | None = None,
        approved: bool = False,
        status: str = "pending_approval",
        decided_at: str | None = None,
    ) -> int:
        decided_at = decided_at or utc_now_iso()
        recommended_price = new_price if recommended_price is None else recommended_price
        errors = json.dumps(guardrail_errors or [], ensure_ascii=False)
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO price_decisions (
                    sku, old_price, recommended_price, new_price, reason,
                    confidence, action, market_position, expected_margin_percent,
                    guardrail_errors, approved, status, decided_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sku,
                    float(old_price),
                    float(recommended_price),
                    float(new_price),
                    reason,
                    confidence,
                    action,
                    market_position,
                    expected_margin_percent,
                    errors,
                    1 if approved else 0,
                    status,
                    decided_at,
                ),
            )
            return int(cur.lastrowid)

    def get_decision(self, decision_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM price_decisions WHERE id = ?",
                (decision_id,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["guardrail_errors"] = json.loads(result.get("guardrail_errors") or "[]")
        return result

    def get_pending_decisions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM price_decisions
                WHERE status = 'pending_approval'
                ORDER BY datetime(decided_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        results = []
        for row in rows:
            result = dict(row)
            result["guardrail_errors"] = json.loads(result.get("guardrail_errors") or "[]")
            results.append(result)
        return results

    def approve_decision(self, decision_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE price_decisions
                SET approved = 1, status = 'approved'
                WHERE id = ?
                """,
                (decision_id,),
            )

    def mark_decision_applied(self, decision_id: int, applied_at: str | None = None) -> None:
        applied_at = applied_at or utc_now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE price_decisions
                SET approved = 1, status = 'applied', applied_at = ?
                WHERE id = ?
                """,
                (applied_at, decision_id),
            )

    def mark_decision_failed(self, decision_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE price_decisions
                SET status = 'update_failed'
                WHERE id = ?
                """,
                (decision_id,),
            )

    def save_price_history(
        self,
        sku: str,
        price: float,
        *,
        source: str = "agent",
        changed_at: str | None = None,
    ) -> int:
        changed_at = changed_at or utc_now_iso()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO price_history (sku, price, source, changed_at)
                VALUES (?, ?, ?, ?)
                """,
                (sku, float(price), source, changed_at),
            )
            return int(cur.lastrowid)


_default_db = PricingDatabase()


def init_db(db_path: str = DB_PATH) -> None:
    PricingDatabase(db_path).init_db()


def save_competitor_price(sku: str, competitor: str, price: float, url: str = "") -> int:
    return _default_db.save_competitor_price(sku, competitor, price, url)


def get_price_history(sku: str, days: int = 7) -> list[dict[str, Any]]:
    return _default_db.get_price_history(sku, days)


def save_decision(sku: str, old_price: float, new_price: float, reason: str, confidence: str) -> int:
    return _default_db.save_decision(sku, old_price, new_price, reason, confidence)
