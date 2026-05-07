from database import PricingDatabase


def test_competitor_price_round_trip(tmp_path):
    db = PricingDatabase(str(tmp_path / "pricing.db"))
    db.init_db()

    db.save_competitor_price(
        "SKU001",
        "Shopee",
        3100000,
        "https://example.com",
        raw_payload={"title": "Pin"},
    )

    history = db.get_price_history("SKU001", days=7)
    assert len(history) == 1
    assert history[0]["competitor"] == "Shopee"
    assert history[0]["price"] == 3100000


def test_decision_lifecycle(tmp_path):
    db = PricingDatabase(str(tmp_path / "pricing.db"))
    db.init_db()

    decision_id = db.save_decision(
        "SKU001",
        3200000,
        3300000,
        "Thị trường tăng nhẹ",
        "medium",
        guardrail_errors=["adjusted"],
    )

    pending = db.get_pending_decisions()
    assert [item["id"] for item in pending] == [decision_id]
    assert pending[0]["guardrail_errors"] == ["adjusted"]

    db.approve_decision(decision_id)
    assert db.get_decision(decision_id)["status"] == "approved"

    db.mark_decision_applied(decision_id)
    decision = db.get_decision(decision_id)
    assert decision["status"] == "applied"
    assert decision["approved"] == 1


def test_price_history_round_trip(tmp_path):
    db = PricingDatabase(str(tmp_path / "pricing.db"))
    db.init_db()

    row_id = db.save_price_history("SKU001", 3300000, source="test")

    with db.connect() as conn:
        row = conn.execute("SELECT * FROM price_history WHERE id = ?", (row_id,)).fetchone()
    assert row["sku"] == "SKU001"
    assert row["source"] == "test"
