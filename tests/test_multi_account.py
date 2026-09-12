import asyncio
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
import moyu_tg_relay.app as app
from moyu_tg_relay.accounts import AccountConfig, AccountIdentity, AccountRuntime, load_account_configs
from moyu_tg_relay.providers.base import ProviderDecision
from moyu_tg_relay.providers.hax import HaxProvider
from moyu_tg_relay.bootstrap_session import add_account, load_env_file


class Provider:
    name = "custom"
    bot_username = "test_bot"

    def evaluate(self, message, request):
        if message.buttons:
            return ProviderDecision(action="click", button=message.buttons[0])
        return ProviderDecision.code_ready(message.text)


class Message:
    date = None

    def __init__(self, code, buttons=(), sender=None):
        self.raw_text = code
        self.buttons = [buttons] if buttons else []
        self._sender = sender or SimpleNamespace(id=1234, username="test_bot")

    async def get_sender(self):
        return self._sender


def config(uid):
    return AccountConfig(str(uid), 12345, "test-hash", session_string=f"session-{uid}")


class ConfigTests(unittest.TestCase):
    def test_legacy_and_per_account_credentials(self):
        legacy = {"TELEGRAM_ACCOUNT_ID": "101", "TELEGRAM_API_ID": "12345", "TELEGRAM_API_HASH": "hash", "TELEGRAM_SESSION_PATH": "one.session"}
        self.assertEqual(load_account_configs(legacy)[0].account_id, "101")
        rows = [{"account_id": "101", "api_id": 12345, "api_hash": "secret-hash", "session_string": "secret-one"}, {"account_id": "202", "api_id": 12345, "api_hash": "secret-hash", "session_path": "two.session"}]
        loaded = load_account_configs({"TELEGRAM_ACCOUNTS_JSON": json.dumps(rows)})
        self.assertEqual([row.account_id for row in loaded], ["101", "202"])
        self.assertNotIn("secret", repr(loaded))

    def test_malformed_and_duplicate_configuration_rejected(self):
        row = {"account_id": "101", "api_id": 12345, "api_hash": "hash", "session_string": "one"}
        for raw in ("not-json", "[]", "{}", json.dumps([row, row]), json.dumps([row, dict(row, account_id="202")])):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                load_account_configs({"TELEGRAM_ACCOUNTS_JSON": raw})
        rows = [dict(row, session_string="", session_path="same"), dict(row, account_id="202", session_string="", session_path="same.session")]
        with self.assertRaises(ValueError):
            load_account_configs({"TELEGRAM_ACCOUNTS_JSON": json.dumps(rows)})

    def test_add_account_migrates_and_preserves_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("TELEGRAM_ACCOUNT_ID=101\nTELEGRAM_API_ID=12345\nTELEGRAM_API_HASH=old-hash\nTELEGRAM_SESSION_STRING=old-session\nOTP_RELAY_BEARER_TOKEN=original-token\n")
            with patch("moyu_tg_relay.bootstrap_session.bootstrap_string_session", new=AsyncMock(return_value=("new-session", 202))):
                add_account(path, 67890, "new-hash")
            values = load_env_file(str(path))
            rows = load_account_configs(values)
            self.assertEqual([row.account_id for row in rows], ["101", "202"])
            self.assertEqual(rows[0].session_string, "old-session")
            self.assertEqual(values["OTP_RELAY_BEARER_TOKEN"], "original-token")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


class MultiAccountTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.store = app.PendingOtpStore()
        self.clients = {uid: MagicMock() for uid in ("101", "202")}
        self.registry = {}
        for uid, client in self.clients.items():
            client.is_connected.return_value = True
            client.get_messages = AsyncMock(return_value=[Message(f"code-{uid}")])
            self.registry[uid] = AccountRuntime(config(uid), client=client, identity=AccountIdentity(uid, username=f"user_{uid}"))
        for key, value in {"store": self.store, "account_runtimes": self.registry, "accounts": self.registry, "runtimes": self.registry, "providers": {"custom": Provider(), "hax": HaxProvider.from_env()}, "log_store": MagicMock()}.items():
            self.stack.enter_context(patch.object(app, key, value))

    async def test_two_accounts_can_receive_and_consume_independently(self):
        first = app.create_request(app.CreateRequest(provider="custom", account="@USER_101"))
        second = app.create_request(app.CreateRequest(provider="custom", account="202"))
        await app._handle_telegram_message(Message("first-code"), "101")
        self.assertEqual(self.store.get(second.request_id).status, "pending")
        await app._poll_pending_interaction(self.store.get(second.request_id))
        self.clients["101"].get_messages.assert_not_called()
        self.clients["202"].get_messages.assert_awaited_once()
        self.assertEqual(app.consume_request(first.request_id).code, "first-code")
        self.assertEqual(app.consume_request(second.request_id).code, "code-202")
        with self.assertRaises(HTTPException):
            app.consume_request(first.request_id)

    async def test_cancelled_poll_cannot_write_into_replacement(self):
        old = self.store.create("101", provider="custom")
        replacement = self.store.create("101", provider="custom")
        await app._poll_pending_interaction(old)
        self.assertEqual(replacement.status, "pending")
        for method in (self.store.mark_auto_attempted, self.store.mark_human_required):
            self.assertEqual(method(account="101", request_id=old.request_id), "")
        self.assertEqual(self.store.attach_code(account="101", request_id=old.request_id, code="old"), "")

    async def test_concurrent_confirmation_is_clicked_once_and_otp_can_follow(self):
        req = self.store.create("101", provider="custom")
        button = SimpleNamespace(text="Confirm", click=AsyncMock())
        event = Message("confirm", (button,))
        await asyncio.gather(app._handle_telegram_message(event, "101"), app._handle_telegram_message(event, "101"))
        button.click.assert_awaited_once()
        self.assertEqual(req.status, "auto_attempted")
        await app._handle_telegram_message(Message("after-confirm"), "101")
        self.assertEqual(self.store.consume(req.request_id), "after-confirm")

    async def test_hax_base64_code_and_resilient_routing(self):
        # Request created under 101, but message from HaxTG_bot received on 202
        req = self.store.create("101", provider="hax")
        b64_msg = (
            "Your Code is \n"
            "ODgxMjQ0MTY3Nzo6OjMxZDJjNGU2MDM2Zjg0YmUxZjQwMmFkMjdlOTE3NDA3"
        )
        event = Message(b64_msg, sender=SimpleNamespace(username="HaxTG_bot", id=1967189265))
        await app._handle_telegram_message(event, "202")
        self.assertEqual(self.store.get(req.request_id).status, "ready")
        self.assertEqual(
            self.store.consume(req.request_id),
            "ODgxMjQ0MTY3Nzo6OjMxZDJjNGU2MDM2Zjg0YmUxZjQwMmFkMjdlOTE3NDA3",
        )

    def test_unknown_and_ambiguous_aliases_rejected(self):
        self.registry["101"].identity = AccountIdentity("101", username="shared")
        self.registry["202"].identity = AccountIdentity("202", username="shared")
        for name, expected in (("shared", 409), ("unknown", 403)):
            with self.assertRaises(HTTPException) as error:
                app.create_request(app.CreateRequest(provider="custom", account=name))
            self.assertEqual(error.exception.status_code, expected)
        self.assertEqual(app._resolve_account_id("101"), "101")

    def test_readiness_is_aggregate_but_polling_readiness_is_per_account(self):
        self.clients["202"].is_connected.return_value = False
        with self.assertRaises(HTTPException):
            app.readyz()
        self.assertTrue(app._telegram_ready("101"))
        self.assertFalse(app._telegram_ready("202"))
        self.assertEqual(app.admin_verify()["ready_count"], 1)
        self.assertNotIn("session-101", str(app.admin_verify()))

    async def test_lifespan_disconnects_all_on_startup_failure_and_shutdown(self):
        for failure in ("connect", "unauthorized", "wrong-id", "none"):
            clients = []
            for uid in ("101", "202"):
                client = MagicMock()
                client.session = SimpleNamespace(dc_id=2)
                client.connect = AsyncMock(side_effect=RuntimeError("connect failed") if uid == "202" and failure == "connect" else None)
                client.disconnect = AsyncMock()
                client.is_user_authorized = AsyncMock(return_value=not (uid == "202" and failure == "unauthorized"))
                client.get_me = AsyncMock(return_value=SimpleNamespace(id=999 if uid == "202" and failure == "wrong-id" else int(uid), phone="", username=""))
                clients.append(client)
            with patch.object(app, "_validate_runtime"), patch.object(app, "_configured_account_configs", return_value=(config(101), config(202))), patch.object(app, "_telegram_session", return_value=app.StringSession()), patch.object(app, "_prepare_telegram_session", return_value=app.StringSession()), patch.object(app, "_detect_use_ipv6", return_value=False), patch.object(app, "TelegramClient", side_effect=clients):
                async def run():
                    async with app.lifespan(app.app):
                        self.assertEqual(len(app.account_runtimes), 2)
                if failure == "none":
                    await run()
                else:
                    with self.assertRaises(RuntimeError):
                        await run()
                for client in clients:
                    client.disconnect.assert_awaited_once()
                self.assertEqual(app.account_runtimes, {})
