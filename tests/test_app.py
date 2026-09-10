import unittest
from unittest.mock import patch

from fastapi import HTTPException

import moyu_tg_relay.app as relay_app


class FakeTelegram:
    def __init__(self, connected: bool):
        self.connected = connected

    def is_connected(self):
        return self.connected


class MoyuTgRelayAppTests(unittest.TestCase):
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
        sentinel = object()
        with (
            patch.object(relay_app, "TELEGRAM_SESSION_STRING", "secret-session"),
            patch.object(relay_app, "TELEGRAM_SESSION_PATH", "/tmp/relay.session"),
            patch.object(relay_app, "StringSession", return_value=sentinel) as constructor,
        ):
            selected = relay_app._telegram_session()

        self.assertIs(selected, sentinel)
        constructor.assert_called_once_with("secret-session")

    def test_invalid_string_session_fails_closed(self):
        with (
            patch.object(relay_app, "TELEGRAM_SESSION_STRING", "not-a-session"),
            patch.object(relay_app, "StringSession", side_effect=ValueError("bad")),
        ):
            with self.assertRaisesRegex(RuntimeError, "TELEGRAM_SESSION_STRING is invalid"):
                relay_app._telegram_session()

    def test_detect_use_ipv6_env_override(self):
        with patch.dict("os.environ", {"TELEGRAM_USE_IPV6": "true"}):
            self.assertTrue(relay_app._detect_use_ipv6())
        with patch.dict("os.environ", {"TELEGRAM_USE_IPV6": "1"}):
            self.assertTrue(relay_app._detect_use_ipv6())
        with patch.dict("os.environ", {"TELEGRAM_USE_IPV6": "false"}):
            self.assertFalse(relay_app._detect_use_ipv6())
        with patch.dict("os.environ", {"TELEGRAM_USE_IPV6": "0"}):
            self.assertFalse(relay_app._detect_use_ipv6())

    def test_detect_use_ipv6_auto_detects_ipv6_only_environment(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(relay_app, "_detect_has_ipv4", return_value=False),
            patch.object(relay_app, "_detect_has_ipv6", return_value=True),
        ):
            self.assertTrue(relay_app._detect_use_ipv6())

        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(relay_app, "_detect_has_ipv4", return_value=True),
            patch.object(relay_app, "_detect_has_ipv6", return_value=True),
        ):
            self.assertFalse(relay_app._detect_use_ipv6())

    def test_prepare_telegram_session_maps_dc_1_to_5_to_official_ipv6(self):
        expected_mappings = {
            1: "2001:b28:f23d:f001::a",
            2: "2001:67c:4e8:f002::a",
            3: "2001:b28:f23d:f003::a",
            4: "2001:67c:4e8:f004::a",
            5: "2001:b28:f23f:f005::a",
        }
        for dc_id, expected_ipv6 in expected_mappings.items():
            with self.subTest(dc_id=dc_id):
                session = relay_app.StringSession()
                session.set_dc(dc_id, "149.154.167.50", 443)
                with patch.object(relay_app, "_telegram_session", return_value=session):
                    adapted = relay_app._prepare_telegram_session(use_ipv6=True)
                    self.assertEqual(adapted.dc_id, dc_id)
                    self.assertEqual(adapted.server_address, expected_ipv6)
                    self.assertEqual(adapted.port, 443)

    def test_telegram_client_preserves_dc5_on_ipv6_connect(self):
        session = relay_app.StringSession()
        session.set_dc(5, "149.154.171.5", 443)
        with patch.object(relay_app, "_telegram_session", return_value=session):
            adapted = relay_app._prepare_telegram_session(use_ipv6=True)
            client = relay_app.TelegramClient(
                adapted,
                12345,
                "test_hash",
                use_ipv6=True,
            )
            self.assertEqual(client.session.dc_id, 5)
            self.assertEqual(client.session.server_address, "2001:b28:f23f:f005::a")


if __name__ == "__main__":
    unittest.main()
