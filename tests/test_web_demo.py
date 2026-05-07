import json

from web_demo import (
    DEFAULT_DEMO_PRODUCTS,
    DifyWorkflowClient,
    DemoAgent,
    DemoStore,
    extract_agent_results,
    run_dify_and_apply,
)


class FakeDifyResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeDifySession:
    def __init__(self, payload):
        self.payload = payload
        self.post_calls = []

    def post(self, *args, **kwargs):
        self.post_calls.append((args, kwargs))
        return FakeDifyResponse(self.payload)


def test_demo_store_upserts_products_and_records_price_events(tmp_path):
    store = DemoStore(str(tmp_path / "demo.db"))
    store.init_db(seed=False)
    product = store.upsert_product(
        {
            "sku": "sku-new",
            "name": "Pin demo",
            "description": "Demo",
            "base_cost": "2.000.000",
            "current_price": "3.200.000",
            "keywords": "pin demo",
            "inventory": "0",
        }
    )

    assert product["sku"] == "SKU-NEW"
    assert product["current_price"] == 3_200_000
    assert product["inventory"] == 0

    event = store.record_price_event(
        "SKU-NEW",
        old_price=3_200_000,
        new_price=3_350_000,
        action="increase",
        reason="Thị trường tăng nhẹ.",
        confidence="medium",
    )

    assert event["new_price"] == 3_350_000
    assert store.get_product("SKU-NEW")["current_price"] == 3_350_000
    assert store.list_events()[0]["sku"] == "SKU-NEW"


def test_demo_agent_runs_guardrails_and_creates_pending_proposal(tmp_path):
    store = DemoStore(str(tmp_path / "demo.db"))
    store.init_db(seed=False)
    store.upsert_product(
        {
            "sku": "SKU001",
            "name": "Pin lithium 12V 100Ah",
            "description": "Pin dân dụng",
            "base_cost": 2_000_000,
            "current_price": 3_200_000,
            "keywords": "pin lithium",
            "inventory": 12,
        }
    )
    agent = DemoAgent(store, use_real_market_search=False)

    result = agent.run_one("SKU001")

    assert result["sku"] == "SKU001"
    assert result["event"]["action"] in {"increase", "decrease", "hold"}
    assert result["event"]["status"] == "pending"
    assert store.get_product("SKU001")["current_price"] == 3_200_000
    assert result["event"]["market_data"]["prices"]


def test_demo_agent_uses_injected_real_market_searcher(tmp_path):
    store = DemoStore(str(tmp_path / "demo.db"))
    store.init_db(seed=False)
    store.upsert_product(
        {
            "sku": "AA2000",
            "name": "Pin Sạc AA 1.2V Ni-MH 2000mAh",
            "description": "Pin BESTON",
            "base_cost": 51_000,
            "current_price": 80_000,
            "keywords": "beston aa2000",
            "inventory": 12,
        }
    )
    queries = []

    def fake_market_searcher(query):
        queries.append(query)
        return {
            "product": "AA2000",
            "prices": [
                {
                    "source": "pinbeston.com",
                    "price": 80_000,
                    "url": "https://pinbeston.com/pin-sac-aa-1-2v-nimh-2000",
                    "title": "Pin Sạc AA 1.2V NIMH 2000mAh",
                }
            ],
            "average_price": 80_000,
            "lowest_price": 80_000,
            "highest_price": 80_000,
            "note": "real",
        }

    agent = DemoAgent(store, market_searcher=fake_market_searcher)
    result = agent.run_one("AA2000")

    assert queries and "AA2000" in queries[0]
    assert result["market_data"]["source_type"] == "real_market_search"
    assert result["market_data"]["prices"][0]["source"] == "pinbeston.com"


def test_apply_agent_result_creates_pending_product_proposal(tmp_path):
    store = DemoStore(str(tmp_path / "demo.db"))
    store.init_db(seed=False)

    product = store.apply_agent_result(
        {
            "sku": "SKU999",
            "name": "Inverter demo",
            "old_price": 10_000_000,
            "new_price": 10_800_000,
            "action": "increase",
            "reason": "Kết quả từ Dify.",
            "confidence": "medium",
            "guardrail_note": "OK",
        }
    )

    assert product["sku"] == "SKU999"
    assert product["current_price"] == 10_000_000
    assert product["last_event"]["source"] == "dify_webhook"
    assert product["last_event"]["status"] == "pending"


def test_approve_and_reject_pending_events(tmp_path):
    store = DemoStore(str(tmp_path / "demo.db"))
    store.init_db(seed=False)
    product = store.upsert_product(
        {
            "sku": "SKU001",
            "name": "Pin demo",
            "base_cost": 2_000_000,
            "current_price": 3_200_000,
        }
    )
    event = store.record_price_event(
        product["sku"],
        old_price=3_200_000,
        new_price=3_350_000,
        action="increase",
        reason="Proposal.",
        confidence="medium",
        status="pending",
        apply_price=False,
    )

    approved = store.approve_event(event["id"])

    assert approved["current_price"] == 3_350_000
    assert approved["last_event"]["status"] == "applied"

    second_event = store.record_price_event(
        product["sku"],
        old_price=3_350_000,
        new_price=3_100_000,
        action="decrease",
        reason="Second proposal.",
        confidence="medium",
        status="pending",
        apply_price=False,
    )

    rejected = store.reject_event(second_event["id"])

    assert rejected["current_price"] == 3_350_000
    assert rejected["last_event"]["status"] == "rejected"


def test_dify_workflow_client_sends_products_json_input():
    session = FakeDifySession(
        {
            "workflow_run_id": "run-1",
            "data": {
                "status": "succeeded",
                "outputs": {"result": []},
            },
        }
    )
    client = DifyWorkflowClient(api_key="app-test", session=session)

    client.run_products(
        [
            {
                "sku": "SKU001",
                "name": "Pin demo",
                "base_cost": 2_000_000,
                "current_price": 3_200_000,
                "market_data": {
                    "prices": [
                        {
                            "source": "pinbeston.com",
                            "price": 3_180_000,
                            "url": "https://example.test",
                            "title": "Pin demo",
                        }
                    ]
                },
            }
        ]
    )

    args, kwargs = session.post_calls[0]
    assert args[0] == "https://api.dify.ai/v1/workflows/run"
    assert kwargs["headers"]["Authorization"] == "Bearer app-test"
    assert kwargs["json"]["inputs"]["products_count"] == "1"
    assert kwargs["json"]["inputs"]["first_sku"] == "SKU001"
    sent_products = json.loads(kwargs["json"]["inputs"]["products_json"])
    assert sent_products[0]["sku"] == "SKU001"
    assert sent_products[0]["market_data"]["prices"][0]["source"] == "pinbeston.com"


def test_dify_workflow_client_always_sends_products_json_even_with_alias():
    session = FakeDifySession(
        {
            "workflow_run_id": "run-1",
            "data": {
                "status": "succeeded",
                "outputs": {"result": []},
            },
        }
    )
    client = DifyWorkflowClient(api_key="app-test", input_name="legacy_products", session=session)

    client.run_products(
        [
            {
                "sku": "AA2000",
                "name": "Pin Sạc AA BESTON",
                "base_cost": 51_000,
                "current_price": 80_000,
            }
        ]
    )

    inputs = session.post_calls[0][1]["json"]["inputs"]
    assert json.loads(inputs["products_json"])[0]["sku"] == "AA2000"
    assert json.loads(inputs["legacy_products"])[0]["sku"] == "AA2000"


def test_extract_agent_results_accepts_nested_json_string():
    outputs = {
        "result": json.dumps(
            [
                {
                    "sku": "SKU001",
                    "old_price": 3_200_000,
                    "new_price": 3_350_000,
                    "action": "increase",
                }
            ]
        )
    }

    assert extract_agent_results(outputs)[0]["new_price"] == 3_350_000


def test_extract_agent_results_accepts_dify_results_array_of_json_strings():
    outputs = {
        "results": [
            json.dumps(
                {
                    "sku": "SKU001",
                    "name": "Pin lithium 12V 100Ah",
                    "action": "increase",
                    "old_price": 3_200_000,
                    "new_price": 3_520_000,
                    "change_pct": 10.0,
                    "reason": "Mặt bằng giá đối thủ cao hơn.",
                    "confidence": "medium",
                    "guardrail_note": "Cap tang 30% | Cap bien dong 10%",
                },
                ensure_ascii=True,
            ),
            json.dumps(
                {
                    "sku": "SKU002",
                    "name": "Pin năng lượng mặt trời 48V 200Ah",
                    "action": "increase",
                    "old_price": 7_500_000,
                    "new_price": 8_250_000,
                    "change_pct": 10.0,
                    "reason": "Giá thị trường tham khảo cao hơn giá hiện tại.",
                    "confidence": "medium",
                    "guardrail_note": "Cap tang 30% | Cap bien dong 10%",
                },
                ensure_ascii=True,
            ),
        ]
    }

    results = extract_agent_results(outputs)

    assert [item["sku"] for item in results] == ["SKU001", "SKU002"]
    assert results[0]["new_price"] == 3_520_000
    assert "Mặt bằng" in results[0]["reason"]


def test_run_dify_and_apply_creates_pending_proposals_from_outputs(tmp_path):
    store = DemoStore(str(tmp_path / "demo.db"))
    store.init_db(seed=False)
    store.upsert_product(
        {
            "sku": "SKU001",
            "name": "Pin demo",
            "base_cost": 2_000_000,
            "current_price": 3_200_000,
        }
    )
    session = FakeDifySession(
        {
            "workflow_run_id": "run-1",
            "data": {
                "status": "succeeded",
                "outputs": {
                    "result": [
                        {
                            "sku": "SKU001",
                            "old_price": 3_200_000,
                            "new_price": 3_350_000,
                            "action": "increase",
                            "reason": "Dify output.",
                            "confidence": "medium",
                        }
                    ]
                },
            },
        }
    )
    client = DifyWorkflowClient(api_key="app-test", session=session)

    result = run_dify_and_apply(
        store,
        client,
        store.list_products(),
        {
            "SKU001": {
                "source_type": "real_market_search",
                "prices": [
                    {
                        "source": "pinbeston.com",
                        "price": 3_180_000,
                        "url": "https://example.test/sku001",
                        "title": "Pin demo",
                    }
                ],
                "average_price": 3_180_000,
                "lowest_price": 3_180_000,
                "highest_price": 3_180_000,
                "note": "real",
            }
        },
    )

    assert result["mode"] == "dify"
    assert result["applied_count"] == 1
    assert result["proposal_count"] == 1
    product = store.get_product("SKU001")
    assert product["current_price"] == 3_200_000
    assert product["last_event"]["status"] == "pending"
    assert product["last_event"]["new_price"] == 3_350_000
    assert product["last_event"]["market_data"]["source_type"] == "real_market_search"
    assert product["last_event"]["market_data"]["prices"][0]["source"] == "pinbeston.com"


def test_run_dify_and_apply_ignores_outputs_for_unrequested_skus(tmp_path):
    store = DemoStore(str(tmp_path / "demo.db"))
    store.init_db(seed=False)
    store.upsert_product(
        {
            "sku": "AA2000",
            "name": "Pin Sạc AA BESTON",
            "base_cost": 51_000,
            "current_price": 80_000,
        }
    )
    session = FakeDifySession(
        {
            "workflow_run_id": "run-1",
            "data": {
                "status": "succeeded",
                "outputs": {
                    "result": [
                        {
                            "sku": "SKU001",
                            "old_price": 3_200_000,
                            "new_price": 3_350_000,
                            "action": "increase",
                        }
                    ]
                },
            },
        }
    )
    client = DifyWorkflowClient(api_key="app-test", session=session)

    result = run_dify_and_apply(store, client, store.list_products())

    assert result["proposal_count"] == 0
    assert result["ignored_count"] == 1
    assert result["ignored_skus"] == ["SKU001"]
    assert store.get_product("SKU001") is None


def test_run_dify_and_apply_polishes_single_source_demo_proposal(tmp_path):
    store = DemoStore(str(tmp_path / "demo.db"))
    store.init_db(seed=False)
    store.upsert_product(
        {
            "sku": "AA1200",
            "name": "Pin Sạc AA 1.2V Ni-MH 1200mAh",
            "base_cost": 33_000,
            "current_price": 52_000,
        }
    )
    session = FakeDifySession(
        {
            "workflow_run_id": "run-1",
            "data": {
                "status": "succeeded",
                "outputs": {
                    "result": [
                        {
                            "sku": "AA1200",
                            "old_price": 52_000,
                            "new_price": 52_000,
                            "action": "hold",
                            "confidence": "medium",
                            "guardrail_note": "Cần ít nhất 2 nguồn giá đối thủ hợp lệ",
                            "market_data": {
                                "prices": [
                                    {
                                        "source": "giadungnhaviet.com",
                                        "price": 140_000,
                                        "url": "https://giadungnhaviet.test/pin-aa-1200",
                                        "title": "Pin AA 1200mAh",
                                    }
                                ],
                                "market_anchor": 0,
                            },
                        }
                    ]
                },
            },
        }
    )
    client = DifyWorkflowClient(api_key="app-test", session=session)

    result = run_dify_and_apply(store, client, store.list_products())
    product = store.get_product("AA1200")

    assert result["demo_single_source_proposals"] is True
    assert product["current_price"] == 52_000
    assert product["last_event"]["status"] == "pending"
    assert product["last_event"]["action"] == "increase"
    assert product["last_event"]["new_price"] == 60_000
    assert product["last_event"]["source"] == "dify_tavily_demo"
    assert product["last_event"]["market_data"]["demo_policy"] == "single_source_pending_proposal"


def test_reset_demo_data_restores_baseline_catalog(tmp_path):
    db_path = str(tmp_path / "demo.db")
    store = DemoStore(db_path)
    store.init_db(seed=False)
    store.upsert_product(
        {
            "sku": "AA1200",
            "name": "Edited",
            "base_cost": 1,
            "current_price": 999_000,
        }
    )
    store.record_price_event(
        "AA1200",
        old_price=52_000,
        new_price=999_000,
        action="increase",
        reason="Dirty state",
        confidence="medium",
    )

    store.reset_demo_data()
    products = store.list_products()
    baseline = {item["sku"]: item for item in DEFAULT_DEMO_PRODUCTS}

    assert len(products) == len(DEFAULT_DEMO_PRODUCTS)
    assert store.list_events() == []
    assert store.get_product("AA1200")["current_price"] == baseline["AA1200"]["current_price"]


def test_run_dify_and_apply_forces_visible_demo_change_without_sources(tmp_path):
    store = DemoStore(str(tmp_path / "demo.db"))
    store.init_db(seed=False)
    store.upsert_product(
        {
            "sku": "AA2000",
            "name": "Pin Sạc AA 1.2V Ni-MH 2000mAh",
            "base_cost": 51_000,
            "current_price": 80_000,
        }
    )
    session = FakeDifySession(
        {
            "workflow_run_id": "run-1",
            "data": {
                "status": "succeeded",
                "outputs": {
                    "result": [
                        {
                            "sku": "AA2000",
                            "old_price": 80_000,
                            "new_price": 80_000,
                            "action": "hold",
                            "confidence": "low",
                            "reason": "Không tìm thấy dữ liệu giá đối thủ.",
                            "market_data": {"prices": []},
                        }
                    ]
                },
            },
        }
    )
    client = DifyWorkflowClient(api_key="app-test", session=session)

    run_dify_and_apply(store, client, store.list_products())
    product = store.get_product("AA2000")

    assert product["last_event"]["action"] == "increase"
    assert product["last_event"]["new_price"] == 92_000
    assert product["last_event"]["market_data"]["demo_policy"] == "visible_change_fallback"


def test_run_dify_and_apply_marks_changed_output_without_sources_as_ai_only(tmp_path):
    store = DemoStore(str(tmp_path / "demo.db"))
    store.init_db(seed=False)
    store.upsert_product(
        {
            "sku": "AA2000",
            "name": "Pin Sạc AA 1.2V Ni-MH 2000mAh",
            "base_cost": 51_000,
            "current_price": 80_000,
        }
    )
    session = FakeDifySession(
        {
            "workflow_run_id": "run-1",
            "data": {
                "status": "succeeded",
                "outputs": {
                    "result": [
                        {
                            "sku": "AA2000",
                            "old_price": 80_000,
                            "new_price": 72_000,
                            "action": "decrease",
                            "confidence": "medium",
                            "reason": "Wrong generic Dify reason.",
                        }
                    ]
                },
            },
        }
    )
    client = DifyWorkflowClient(api_key="app-test", session=session)

    run_dify_and_apply(store, client, store.list_products())
    product = store.get_product("AA2000")

    assert product["last_event"]["action"] == "decrease"
    assert product["last_event"]["new_price"] == 72_000
    assert product["last_event"]["confidence"] == "low"
    assert product["last_event"]["source"] == "dify_ai_only"
    assert product["last_event"]["market_data"]["demo_policy"] == "ai_only_no_sources"
    assert product["last_event"]["market_data"]["prices"] == []
    assert "Pin Sạc AA 1.2V Ni-MH 2000mAh" in product["last_event"]["reason"]
