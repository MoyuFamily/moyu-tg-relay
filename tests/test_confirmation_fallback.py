import unittest
from types import SimpleNamespace
from unittest.mock import patch

import moyu_tg_relay.app as relay_app
from moyu_tg_relay.store import PendingOtpStore


class FakeButton:
    def __init__(self, text="Confirm", error=None, kind="callback"):
        self.text = text
        self.error = error
        self.kind = kind
        self.clicked = 0

    async def click(self):
        self.clicked += 1
        if self.error:
            raise self.error


class FakeEvent:
    def __init__(self, *, sender_id=777000, username="", text="", buttons=None):
        self._sender = SimpleNamespace(id=sender_id, username=username)
        self.raw_text = text
        self.buttons = buttons or []

    async def get_sender(self):
        return self._sender


def create_runner_request(store: PendingOtpStore):
    return store.create(
        "123",
        300,
        context={"source": "renew-provider", "stage": "renew"},
    )


class ConfirmationFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_known_hax_confirmation_is_auto_attempted(self):
        store = PendingOtpStore()
        request = create_runner_request(store)
        button = FakeButton()
        event = FakeEvent(
            text="Confirm login to hax.co.id",
            buttons=[[button]],
        )

        with (
            patch.object(relay_app, "store", store),
            patch.object(relay_app, "TELEGRAM_ACCOUNT_ID", "123"),
            patch.object(relay_app, "HAX_AUTO_CONFIRM", True),
            patch.object(relay_app, "HAX_CONFIRMATION_SENDER_IDS", frozenset({"777000"})),
            patch.object(relay_app, "HAX_CONFIRMATION_MARKERS", ("hax.co.id", "hax")),
            patch.object(relay_app, "HAX_AUTO_CONFIRM_BUTTONS", frozenset({"confirm"})),
        ):
            await relay_app._handle_telegram_message(event)

        self.assertEqual(button.clicked, 1)
        self.assertEqual(store.get(request.request_id).status, "auto_attempted")

    async def test_auto_click_failure_becomes_human_required(self):
        store = PendingOtpStore()
        request = create_runner_request(store)
        event = FakeEvent(
            text="Confirm login to hax.co.id",
            buttons=[[FakeButton(error=RuntimeError("blocked"))]],
        )

        with (
            patch.object(relay_app, "store", store),
            patch.object(relay_app, "TELEGRAM_ACCOUNT_ID", "123"),
            patch.object(relay_app, "HAX_AUTO_CONFIRM", True),
            patch.object(relay_app, "HAX_CONFIRMATION_SENDER_IDS", frozenset({"777000"})),
            patch.object(relay_app, "HAX_CONFIRMATION_MARKERS", ("hax.co.id", "hax")),
            patch.object(relay_app, "HAX_AUTO_CONFIRM_BUTTONS", frozenset({"confirm"})),
        ):
            await relay_app._handle_telegram_message(event)

        item = store.get(request.request_id)
        self.assertEqual(item.status, "human_required")
        self.assertIn("自动点击", item.detail)

    async def test_unknown_button_fails_closed_to_human(self):
        store = PendingOtpStore()
        request = create_runner_request(store)
        event = FakeEvent(
            text="hax.co.id needs your confirmation",
            buttons=[[FakeButton(text="Review")]],
        )

        with (
            patch.object(relay_app, "store", store),
            patch.object(relay_app, "TELEGRAM_ACCOUNT_ID", "123"),
            patch.object(relay_app, "HAX_AUTO_CONFIRM", True),
            patch.object(relay_app, "HAX_CONFIRMATION_SENDER_IDS", frozenset({"777000"})),
            patch.object(relay_app, "HAX_CONFIRMATION_MARKERS", ("hax.co.id", "hax")),
            patch.object(relay_app, "HAX_AUTO_CONFIRM_BUTTONS", frozenset({"confirm"})),
        ):
            await relay_app._handle_telegram_message(event)

        self.assertEqual(store.get(request.request_id).status, "human_required")

    async def test_url_button_is_not_misreported_as_auto_attempted(self):
        store = PendingOtpStore()
        request = create_runner_request(store)
        button = FakeButton(text="Confirm", kind="url")
        event = FakeEvent(
            text="Confirm login to hax.co.id",
            buttons=[[button]],
        )

        with (
            patch.object(relay_app, "store", store),
            patch.object(relay_app, "TELEGRAM_ACCOUNT_ID", "123"),
            patch.object(relay_app, "HAX_AUTO_CONFIRM", True),
            patch.object(relay_app, "HAX_CONFIRMATION_SENDER_IDS", frozenset({"777000"})),
            patch.object(relay_app, "HAX_CONFIRMATION_MARKERS", ("hax.co.id", "hax")),
            patch.object(relay_app, "HAX_AUTO_CONFIRM_BUTTONS", frozenset({"confirm"})),
        ):
            await relay_app._handle_telegram_message(event)

        item = store.get(request.request_id)
        self.assertEqual(button.clicked, 0)
        self.assertEqual(item.status, "human_required")
        self.assertIn("不能由 Relay 安全自动执行", item.detail)

    async def test_untrusted_request_context_cannot_trigger_auto_click(self):
        store = PendingOtpStore()
        request = store.create(
            "123",
            300,
            context={"source": "other-service", "stage": "renew"},
        )
        button = FakeButton()
        event = FakeEvent(
            text="Confirm login to hax.co.id",
            buttons=[[button]],
        )

        with (
            patch.object(relay_app, "store", store),
            patch.object(relay_app, "TELEGRAM_ACCOUNT_ID", "123"),
            patch.object(relay_app, "HAX_AUTO_CONFIRM", True),
            patch.object(relay_app, "HAX_CONFIRMATION_SENDER_IDS", frozenset({"777000"})),
            patch.object(relay_app, "HAX_CONFIRMATION_MARKERS", ("hax.co.id", "hax")),
            patch.object(relay_app, "HAX_AUTO_CONFIRM_BUTTONS", frozenset({"confirm"})),
        ):
            await relay_app._handle_telegram_message(event)

        self.assertEqual(button.clicked, 0)
        self.assertEqual(store.get(request.request_id).status, "pending")


if __name__ == "__main__":
    unittest.main()
