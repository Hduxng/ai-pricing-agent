from price_updater import PriceUpdater


class FakeResponse:
    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self):
        self.put_calls = []
        self.post_calls = []

    def put(self, *args, **kwargs):
        self.put_calls.append((args, kwargs))
        return FakeResponse()

    def post(self, *args, **kwargs):
        self.post_calls.append((args, kwargs))
        return FakeResponse()


def test_update_price_dry_run_does_not_call_api():
    session = FakeSession()
    updater = PriceUpdater(dry_run=True, session=session)

    assert updater.update_price("SKU001", 3300000) is True
    assert session.put_calls == []


def test_update_price_calls_website_api():
    session = FakeSession()
    updater = PriceUpdater(
        api_base_url="https://example.com",
        api_key="key",
        dry_run=False,
        session=session,
    )

    assert updater.update_price("SKU001", 3300000) is True

    args, kwargs = session.put_calls[0]
    assert args[0] == "https://example.com/api/products/SKU001/price"
    assert kwargs["json"] == {"price": 3300000}
    assert kwargs["headers"]["Authorization"] == "Bearer key"


def test_update_price_missing_config_fails_closed():
    updater = PriceUpdater(api_base_url="", api_key=None, dry_run=False)

    assert updater.update_price("SKU001", 3300000) is False


def test_send_notification_calls_telegram():
    session = FakeSession()
    updater = PriceUpdater(
        telegram_bot_token="token",
        telegram_chat_id="chat",
        dry_run=False,
        session=session,
    )

    assert updater.send_notification("hello") is True

    args, kwargs = session.post_calls[0]
    assert args[0] == "https://api.telegram.org/bottoken/sendMessage"
    assert kwargs["json"]["chat_id"] == "chat"
