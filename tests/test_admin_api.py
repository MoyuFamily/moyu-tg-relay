import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import BaseModel

import moyu_tg_relay.app as relay_app
from moyu_tg_relay.log_store import RelayLogStore


class TestAdminDashboardAndApi(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_admin_logs.db"
        self.test_log_store = RelayLogStore(db_path=self.db_path, retention_days=15)
        self.test_token = "secret-test-bearer-token-12345"

        # Patch app global objects
        self.patcher_store = patch.object(relay_app, "log_store", self.test_log_store)
        self.patcher_token = patch.object(relay_app, "RELAY_TOKEN", self.test_token)
        self.patcher_account = patch.object(relay_app, "TELEGRAM_ACCOUNT_ID", "123456789")
        self.patcher_store.start()
        self.patcher_token.start()
        self.patcher_account.start()

    def tearDown(self):
        self.patcher_account.stop()
        self.patcher_token.stop()
        self.patcher_store.stop()
        self.temp_dir.cleanup()

    def test_admin_dashboard_html_rendering_and_autofill_form(self):
        response = relay_app.admin_dashboard_ui()
        self.assertEqual(response.status_code, 200)
        html = response.body.decode("utf-8")

        # Verify semantic form and password manager autofill support
        self.assertIn('id="login-form"', html)
        self.assertIn('autocomplete="username"', html)
        self.assertIn('autocomplete="current-password"', html)
        self.assertIn('type="password"', html)
        self.assertIn('name="password"', html)
        self.assertIn('name="username"', html)
        self.assertIn('method="POST"', html)
        self.assertIn('Moyu Telegram Relay 运维后台', html)

    def test_admin_auth_dependency(self):
        # 1. No auth
        with self.assertRaises(HTTPException) as ctx:
            relay_app.require_auth(None)
        self.assertEqual(ctx.exception.status_code, 401)

        # 2. Invalid auth
        with self.assertRaises(HTTPException) as ctx:
            relay_app.require_auth("Bearer wrong-token")
        self.assertEqual(ctx.exception.status_code, 401)

        # 3. Valid auth
        relay_app.require_auth(f"Bearer {self.test_token}")

    def test_admin_verify(self):
        with patch.object(relay_app, "_telegram_ready", return_value=True):
            data = relay_app.admin_verify()
            self.assertEqual(data["status"], "ready")
            self.assertEqual(data["account_id"], "123456789")

        with patch.object(relay_app, "_telegram_ready", return_value=False):
            data = relay_app.admin_verify()
            self.assertEqual(data["status"], "not_ready")

    def test_admin_stats(self):
        self.test_log_store.record("INFO", "system", "System test event")
        self.test_log_store.record("WARNING", "provider", "Warning event")

        data = relay_app.admin_stats()
        self.assertEqual(data["retention_days"], 15)
        self.assertGreaterEqual(data["total_logs"], 2)
        self.assertIn("level_counts", data)
        self.assertIn("category_counts", data)
        self.assertIn("telegram", data)

    def test_admin_logs_query_and_filtering(self):
        self.test_log_store.record(
            "INFO",
            "provider",
            "Hax click event",
            provider="hax",
            request_id="req-abc-1",
        )
        self.test_log_store.record(
            "ERROR",
            "system",
            "Database disk full simulation",
            request_id="req-xyz-2",
        )

        # Query all
        data = relay_app.admin_query_logs()
        self.assertEqual(data["total"], 2)
        self.assertEqual(len(data["logs"]), 2)

        # Filter by level
        err_data = relay_app.admin_query_logs(level="ERROR")
        self.assertEqual(err_data["total"], 1)
        self.assertEqual(err_data["logs"][0]["level"], "ERROR")

        # Search query
        search_data = relay_app.admin_query_logs(search="Hax")
        self.assertEqual(search_data["total"], 1)
        self.assertEqual(search_data["logs"][0]["provider"], "hax")

    def test_admin_prune_endpoint(self):
        payload = relay_app.PrunePayload(days=15)
        res = relay_app.admin_prune_logs(payload)
        self.assertIn("deleted", res)

    def test_request_lifecycle_generates_logs(self):
        payload = relay_app.CreateRequest(
            provider="hax",
            account="123456789",
            ttl_seconds=300,
            context={"action": "login"},
        )
        with patch.object(relay_app, "_is_matching_account", return_value=True):
            create_resp = relay_app.create_request(payload)

        req_id = create_resp.request_id

        # Verify log entry was written
        logs = relay_app.admin_query_logs(request_id=req_id)["logs"]
        self.assertGreaterEqual(len(logs), 1)
        self.assertEqual(logs[0]["category"], "otp_request")
        self.assertEqual(logs[0]["provider"], "hax")

        # Cancel the request
        cancel_resp = relay_app.cancel_request(req_id)
        self.assertEqual(cancel_resp.status_code, 204)

        # Verify cancel log exists
        logs_after_cancel = relay_app.admin_query_logs(request_id=req_id)["logs"]
        self.assertEqual(len(logs_after_cancel), 2)
        messages = [l["message"] for l in logs_after_cancel]
        self.assertTrue(any("取消交互请求" in m for m in messages))


if __name__ == "__main__":
    unittest.main()
