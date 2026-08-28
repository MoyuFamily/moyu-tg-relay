import unittest
from unittest.mock import patch

from fastapi import HTTPException

import relay.hax_otp.app as relay_app


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

    def test_readyz_rejects_when_telegram_is_not_connected(self):
        with patch.object(relay_app, "telegram", None):
            with self.assertRaises(HTTPException) as raised:
                relay_app.readyz()

        self.assertEqual(raised.exception.status_code, 503)

    def test_readyz_succeeds_when_telegram_is_connected(self):
        with patch.object(relay_app, "telegram", FakeTelegram(True)):
            self.assertEqual(relay_app.readyz(), {"status": "ready"})

    def test_readyz_rejects_disconnected_client(self):
        with patch.object(relay_app, "telegram", FakeTelegram(False)):
            with self.assertRaises(HTTPException) as raised:
                relay_app.readyz()

        self.assertEqual(raised.exception.status_code, 503)

    def test_bearer_auth_accepts_only_exact_token(self):
        with patch.object(relay_app, "RELAY_TOKEN", "relay-secret"):
            relay_app.require_auth("Bearer relay-secret")
            for supplied in (None, "", "Bearer wrong", "relay-secret"):
                with self.subTest(supplied=supplied):
                    with self.assertRaises(HTTPException) as raised:
                        relay_app.require_auth(supplied)
                    self.assertEqual(raised.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
