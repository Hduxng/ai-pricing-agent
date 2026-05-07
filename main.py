from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from typing import Any, Callable

from analyzer import analyze_and_recommend
from config import SETTINGS, PricingSettings, load_settings
from database import PricingDatabase
from guardrails import validate_price_detailed
from price_updater import PriceUpdater
from scraper import search_market_price

logger = logging.getLogger(__name__)

MarketSearcher = Callable[[str], dict[str, Any]]
Analyzer = Callable[[dict[str, Any], list[dict[str, Any]], dict[str, Any]], dict[str, Any]]


def configure_logging(log_file: str = "agent.log") -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_file, encoding="utf-8")],
    )


def persist_market_prices(db: PricingDatabase, sku: str, market_data: dict[str, Any]) -> int:
    count = 0
    for item in market_data.get("prices", []):
        db.save_competitor_price(
            sku,
            item.get("source", "unknown"),
            item.get("price", 0),
            item.get("url", ""),
            raw_payload=item,
        )
        count += 1
    return count


def build_notification_message(
    sku_info: dict[str, Any],
    new_price: int,
    recommendation: dict[str, Any],
    guardrail_errors: list[str],
) -> str:
    current = int(sku_info["current_price"])
    change_pct = (new_price - current) / current * 100
    direction = "Tăng" if change_pct > 0 else "Giảm" if change_pct < 0 else "Giữ"
    guardrail_note = ""
    if guardrail_errors:
        guardrail_note = "\nGuardrails: " + "; ".join(guardrail_errors)
    return (
        f"{direction} giá [{sku_info['sku']}] {sku_info['name']}\n"
        f"{current:,}đ -> {new_price:,}đ ({change_pct:+.1f}%)\n"
        f"Độ tin cậy: {recommendation['confidence']}\n"
        f"Lý do: {recommendation['reason']}"
        f"{guardrail_note}"
    )


def process_sku(
    sku_info: dict[str, Any],
    *,
    settings: PricingSettings = SETTINGS,
    db: PricingDatabase,
    updater: PriceUpdater,
    market_searcher: MarketSearcher = search_market_price,
    analyzer: Analyzer = analyze_and_recommend,
) -> dict[str, Any]:
    sku = sku_info["sku"]
    logger.info("[%s] OBSERVE - collecting market prices for %s", sku, sku_info["name"])
    market_data = market_searcher(sku_info["name"])
    saved_prices = persist_market_prices(db, sku, market_data)

    logger.info("[%s] ORIENT - loading recent history", sku)
    history = db.get_price_history(sku, days=7)

    logger.info("[%s] DECIDE - requesting AI recommendation", sku)
    recommendation = analyzer(sku_info, history, market_data)
    recommended_price = int(recommendation["recommended_price"])

    guardrail_result = validate_price_detailed(
        sku_info,
        recommended_price,
        price_floor_percent=settings.price_floor_percent,
        price_ceiling_percent=settings.price_ceiling_percent,
        max_daily_change_percent=settings.max_daily_change_percent,
        min_margin_percent=settings.min_margin_percent,
        price_rounding=settings.price_rounding,
    )
    new_price = guardrail_result.adjusted_price
    if guardrail_result.errors:
        logger.warning("[%s] Guardrails adjusted %s -> %s: %s", sku, recommended_price, new_price, guardrail_result.errors)

    status = "hold"
    approved = False
    if new_price != int(sku_info["current_price"]):
        status = "pending_approval" if settings.require_approval else "ready_to_apply"

    decision_id = db.save_decision(
        sku,
        sku_info["current_price"],
        new_price,
        recommendation["reason"],
        recommendation["confidence"],
        recommended_price=recommended_price,
        action=recommendation["action"],
        market_position=recommendation["market_position"],
        expected_margin_percent=recommendation["expected_margin_percent"],
        guardrail_errors=guardrail_result.errors,
        approved=approved,
        status=status,
    )

    if status == "hold":
        logger.info("[%s] ACT - holding current price", sku)
    elif settings.require_approval:
        message = build_notification_message(sku_info, new_price, recommendation, guardrail_result.errors)
        updater.send_notification(f"Đề xuất thay đổi giá:\n{message}")
        logger.info("[%s] ACT - waiting for approval", sku)
    else:
        logger.info("[%s] ACT - updating price", sku)
        if updater.update_price(sku, new_price):
            db.mark_decision_applied(decision_id)
            db.save_price_history(sku, new_price, source="agent")
            status = "applied"
        else:
            db.mark_decision_failed(decision_id)
            status = "update_failed"

    return {
        "sku": sku,
        "decision_id": decision_id,
        "status": status,
        "old": int(sku_info["current_price"]),
        "recommended": recommended_price,
        "new": new_price,
        "saved_market_prices": saved_prices,
        "guardrail_errors": guardrail_result.errors,
    }


def run_pricing_cycle(
    *,
    settings: PricingSettings = SETTINGS,
    db: PricingDatabase | None = None,
    updater: PriceUpdater | None = None,
    market_searcher: MarketSearcher = search_market_price,
    analyzer: Analyzer = analyze_and_recommend,
) -> list[dict[str, Any]]:
    db = db or PricingDatabase(settings.db_path)
    updater = updater or PriceUpdater.from_settings(settings)
    db.init_db()

    logger.info("=" * 60)
    logger.info("Starting pricing cycle - %s", datetime.now().isoformat(timespec="seconds"))
    logger.info("=" * 60)

    results: list[dict[str, Any]] = []
    for sku_info in settings.tracked_skus:
        try:
            result = process_sku(
                sku_info,
                settings=settings,
                db=db,
                updater=updater,
                market_searcher=market_searcher,
                analyzer=analyzer,
            )
            logger.info("[%s] Result: %s", sku_info["sku"], json.dumps(result, ensure_ascii=False))
            results.append(result)
        except Exception as exc:
            logger.error("[%s] Cycle failed: %s", sku_info["sku"], exc, exc_info=True)

    logger.info("Cycle complete. Processed %s/%s SKU", len(results), len(settings.tracked_skus))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Dynamic Pricing Agent")
    parser.add_argument("--once", action="store_true", help="Run one pricing cycle and exit")
    parser.add_argument("--schedule", action="store_true", help="Run immediately, then keep scheduling")
    args = parser.parse_args(argv)

    settings = load_settings()
    configure_logging()
    run_pricing_cycle(settings=settings)

    if args.schedule:
        from apscheduler.schedulers.blocking import BlockingScheduler

        scheduler = BlockingScheduler(timezone=settings.timezone)
        scheduler.add_job(
            lambda: run_pricing_cycle(settings=settings),
            "interval",
            hours=settings.check_interval_hours,
        )
        logger.info("Scheduler enabled: every %s hours", settings.check_interval_hours)
        scheduler.start()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
