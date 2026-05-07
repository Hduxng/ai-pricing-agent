from config import PricingSettings
from database import PricingDatabase
from main import process_sku, run_pricing_cycle
from price_updater import PriceUpdater


SKU = {
    "sku": "SKU001",
    "name": "Pin lithium 12V 100Ah",
    "base_cost": 2_000_000,
    "current_price": 3_200_000,
}


class FakeUpdater(PriceUpdater):
    def __init__(self):
        super().__init__(dry_run=True)
        self.notifications = []
        self.updates = []

    def send_notification(self, message):
        self.notifications.append(message)
        return True

    def update_price(self, sku, new_price):
        self.updates.append((sku, new_price))
        return True


def fake_market_searcher(product_name):
    return {
        "product": product_name,
        "prices": [
            {
                "source": "Shopee",
                "price": 3300000,
                "url": "https://example.com/pin",
                "title": "Pin lithium",
            }
        ],
        "average_price": 3300000,
        "lowest_price": 3300000,
        "highest_price": 3300000,
        "note": "Dữ liệu ổn định",
    }


def fake_analyzer(sku_info, history, market_data):
    return {
        "recommended_price": 3300000,
        "confidence": "medium",
        "reason": "Giá thị trường cao hơn nhẹ.",
        "action": "increase",
        "market_position": "below_market",
        "expected_margin_percent": 39.4,
    }


def test_process_sku_waits_for_approval(tmp_path):
    settings = PricingSettings(require_approval=True, dry_run=True, tracked_skus=[SKU])
    db = PricingDatabase(str(tmp_path / "pricing.db"))
    db.init_db()
    updater = FakeUpdater()

    result = process_sku(
        SKU,
        settings=settings,
        db=db,
        updater=updater,
        market_searcher=fake_market_searcher,
        analyzer=fake_analyzer,
    )

    assert result["status"] == "pending_approval"
    assert updater.notifications
    assert updater.updates == []
    assert db.get_decision(result["decision_id"])["status"] == "pending_approval"
    assert len(db.get_price_history("SKU001")) == 1


def test_process_sku_applies_when_approval_disabled(tmp_path):
    settings = PricingSettings(require_approval=False, dry_run=True, tracked_skus=[SKU])
    db = PricingDatabase(str(tmp_path / "pricing.db"))
    db.init_db()
    updater = FakeUpdater()

    result = process_sku(
        SKU,
        settings=settings,
        db=db,
        updater=updater,
        market_searcher=fake_market_searcher,
        analyzer=fake_analyzer,
    )

    assert result["status"] == "applied"
    assert updater.updates == [("SKU001", 3300000)]
    assert db.get_decision(result["decision_id"])["status"] == "applied"


def test_run_pricing_cycle_processes_all_skus(tmp_path):
    settings = PricingSettings(require_approval=True, dry_run=True, tracked_skus=[SKU])
    db = PricingDatabase(str(tmp_path / "pricing.db"))
    updater = FakeUpdater()

    results = run_pricing_cycle(
        settings=settings,
        db=db,
        updater=updater,
        market_searcher=fake_market_searcher,
        analyzer=fake_analyzer,
    )

    assert [item["sku"] for item in results] == ["SKU001"]
