from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from config import (
    DRY_RUN,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    WEBSITE_API_BASE_URL,
    WEBSITE_API_KEY,
    PricingSettings,
)

logger = logging.getLogger(__name__)


@dataclass
class PriceUpdater:
    api_base_url: str = WEBSITE_API_BASE_URL
    api_key: str | None = WEBSITE_API_KEY
    telegram_bot_token: str | None = TELEGRAM_BOT_TOKEN
    telegram_chat_id: str | None = TELEGRAM_CHAT_ID
    dry_run: bool = DRY_RUN
    session: Any | None = None
    timeout: int = 10

    @classmethod
    def from_settings(
        cls,
        settings: PricingSettings,
        *,
        session: Any | None = None,
    ) -> "PriceUpdater":
        return cls(
            api_base_url=settings.website_api_base_url,
            api_key=settings.website_api_key,
            telegram_bot_token=settings.telegram_bot_token,
            telegram_chat_id=settings.telegram_chat_id,
            dry_run=settings.dry_run,
            session=session,
        )

    def _http(self):
        if self.session is not None:
            return self.session
        import requests

        return requests

    def update_price(self, sku: str, new_price: int) -> bool:
        if new_price <= 0:
            logger.error("SKU %s: invalid new price %s", sku, new_price)
            return False
        if self.dry_run:
            logger.info("[DRY_RUN] SKU %s: would update price to %s", sku, f"{new_price:,}đ")
            return True
        if not self.api_base_url or not self.api_key:
            logger.error("Missing website API configuration; cannot update SKU %s", sku)
            return False

        url = f"{self.api_base_url.rstrip('/')}/api/products/{sku}/price"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            resp = self._http().put(
                url,
                json={"price": int(new_price)},
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            logger.info("SKU %s: updated price to %s", sku, f"{new_price:,}đ")
            return True
        except Exception as exc:
            logger.error("SKU %s: update failed - %s", sku, exc)
            return False

    def send_notification(self, message: str) -> bool:
        if self.dry_run:
            logger.info("[DRY_RUN] Telegram notification: %s", message)
            return True
        if not self.telegram_bot_token or not self.telegram_chat_id:
            logger.warning("Missing Telegram configuration; notification skipped")
            return False

        url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
        try:
            resp = self._http().post(
                url,
                json={
                    "chat_id": self.telegram_chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return True
        except Exception as exc:
            logger.error("Telegram notification failed - %s", exc)
            return False
