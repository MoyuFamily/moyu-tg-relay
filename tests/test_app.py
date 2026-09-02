import unittest
from unittest.mock import patch

from fastapi import HTTPException
from telethon.sessions import StringSession

import moyu_tg_relay.app as relay_app


class FakeTelegram:
    def __init__(self, connected: bool):
        self.connected = connected

    def is_connected(self):
        return self.connected


class HaxOtpRelayAppTests(unittest.TestCase):
    def test_public_api_docs_are_disabled(self):
        self.assertIsNone(relay_app.app.docs_url)
        self.assertIsNone(relay_app.app.redoc_url)
        self.assertIsNone(relay_app.app.openapi_url)

    def test_healthz_is_process_liveness_only(self):
        self.assertEqual(relay_app.healthz(), {"status": "ok"})

    def test_readyz_reports_503_when_client_missing_or_disconnected(self):
        with patch.object(relay_app, "telegram", None):
            with self.assertRaises(HTTPException) as ctx:
                relay_app.readyz()
            self.assertEqual(ctx.exception.status_code, 503)

        with patch.object(relay_app, "telegram", FakeTelegram(connected=False)):
            with self.assertRaises(HTTPException) as ctx:
                relay_app.readyz()
            self.assertEqual(ctx.exception.status_code, 503)

    def test_readyz_reports_ok_when_client_connected(self):
        with patch.object(relay_app, "telegram", FakeTelegram(connected=True)):
            self.assertEqual(relay_app.readyz(), {"status": "ready"})

    def test_bearer_auth_rejects_missing_and_invalid_token(self):
        with patch.object(relay_app, "RELAY_TOKEN", "test-secret"):
            for supplied in (None, "", "Bearer wrong-secret", "test-secret"):
                with self.subTest(supplied=supplied):
                    with self.assertRaises(HTTPException) as ctx:
                        relay_app.require_auth(supplied)
                    self.assertEqual(ctx.exception.status_code, 401)

    def test_bearer_auth_accepts_exact_token(self):
        with patch.object(relay_app, "RELAY_TOKEN", "test-secret"):
            self.assertIsNone(relay_app.require_auth("Bearer test-secret"))

    def test_file_session_remains_default_fallback(self):
        with (
            patch.object(relay_app, "TELEGRAM_SESSION_STRING", ""),
            patch.object(relay_app, "TELEGRAM_SESSION_PATH", "/tmp/relay.session"),
        ):
            self.assertEqual(relay_app._telegram_session(), "/tmp/relay.session")

    def test_string_session_takes_precedence_over_file_path(self):
        encoded = StringSession().save()
        with (
            patch.object(relay_app, "TELEGRAM_SESSION_STRING", encoded),
            patch.object(relay_app, "TELEGRAM_SESSION_PATH", "/tmp/relay.session"),
        ):
            selected = relay_app._telegram_session()

        self.assertIsInstance(selected, StringSession)
        self.assertEqual(selected.save(), encoded)

    def test_invalid_string_session_fails_closed(self):
        with patch.object(relay_app, "TELEGRAM_SESSION_STRING", "not-a-session"):
            with self.assertRaisesRegex(RuntimeError, "TELEGRAM_SESSION_STRING is invalid"):
                relay_app._telegram_session()


if __name__ == "__main__":
    unittest.main()
