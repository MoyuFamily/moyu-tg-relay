import unittest
from types import SimpleNamespace
from unittest.mock import patch

import moyu_tg_relay.app as relay_app
from moyu_tg_relay.providers.base import ProviderDecision
from moyu_tg_relay.store import PendingOtpStore


class FakeProvider:
    name = "custom"

    def evaluate(self, message, request):
        if message.text == "custom-code":
            return ProviderDecision.code_ready("ABC-42")
        return ProviderDecision.ignore()


class FakeEvent:
    raw_text = "custom-code"
    buttons = []

    async def get_sender(self):
        return SimpleNamespace(id=999, username="custom_bot")


class ProviderRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_core_routes_active_request_to_registered_provider(self):
        store = PendingOtpStore()
        request = store.create("123", provider="custom")

        with (
            patch.object(relay_app, "store", store),
            patch.object(relay_app, "TELEGRAM_ACCOUNT_ID", "123"),
            patch.object(relay_app, "providers", {"custom": FakeProvider()}),
        ):
            await relay_app._handle_telegram_message(FakeEvent())

        self.assertEqual(store.get(request.request_id).status, "ready")
        self.assertEqual(store.consume(request.request_id), "ABC-42")

    def test_create_request_accepts_any_registered_provider(self):
        store = PendingOtpStore()
        payload = relay_app.CreateRequest(provider="custom", account="123")

        with (
            patch.object(relay_app, "store", store),
            patch.object(relay_app, "TELEGRAM_ACCOUNT_ID", "123"),
            patch.object(relay_app, "providers", {"custom": FakeProvider()}),
        ):
            response = relay_app.create_request(payload)

        self.assertEqual(store.get(response.request_id).provider, "custom")


if __name__ == "__main__":
    unittest.main()
