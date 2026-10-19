import tempfile
import time
import unittest
from pathlib import Path
from fastapi.testclient import TestClient

import moyu_tg_relay.app as app
from moyu_tg_relay.log_store import RelayLogStore


class TestMessagesApi(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_api_logs.db"
        self.original_token = app.RELAY_TOKEN
        app.RELAY_TOKEN = "secret-test-token"
        self.original_log_store = app.log_store
        self.current_time = 1700000000.0
        self.store = RelayLogStore(
            db_path=self.db_path,
            retention_days=15,
            clock=lambda: self.current_time,
        )
        app.log_store = self.store
        self.client = TestClient(app.app)

    def tearDown(self):
        self.temp_dir.cleanup()
        app.RELAY_TOKEN = self.original_token
        app.log_store = self.original_log_store

    def test_messages_endpoint_requires_auth(self):
        resp = self.client.get("/v1/messages")
        self.assertEqual(resp.status_code, 401)

        resp = self.client.get("/v1/messages", headers={"Authorization": "Bearer wrong-token"})
        self.assertEqual(resp.status_code, 401)

    def test_messages_endpoint_empty(self):
        headers = {"Authorization": "Bearer secret-test-token"}
        resp = self.client.get("/v1/messages", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["messages"], [])

    def test_messages_endpoint_records_and_filters(self):
        headers = {"Authorization": "Bearer secret-test-token"}

        # Record messages
        self.current_time = 1700000000.0
        self.store.record(
            "INFO",
            "telegram",
            "Hax ready",
            account="acc1",
            extra={
                "sender_username": "HaxTG_bot",
                "sender_id": "1001",
                "text": "Your HAX VPS is ready\n 2a01:4f8:211:2312:1234:4321:9a78:0001/112",
                "buttons": ["OK"],
            },
        )

        self.current_time = 1700000010.0
        self.store.record(
            "INFO",
            "telegram",
            "Removal notice",
            account="acc1",
            extra={
                "sender_username": "HaxTG_bot",
                "sender_id": "1001",
                "text": "VPS will be removed at 2026-10-21, you can renew it for free at https://hax.co.id/vps-renew/ ",
                "buttons": [],
            },
        )

        self.current_time = 1700000020.0
        self.store.record(
            "INFO",
            "telegram",
            "Woiden ready",
            account="acc2",
            extra={
                "sender_username": "WoidenTG_bot",
                "sender_id": "1002",
                "text": "IPv6:2a01:4f8:211:2312:1234:4321:9a78:0001/112\nYour Woiden IPv6 VPS is ready",
                "buttons": [],
            },
        )

        # 1. Fetch all
        resp = self.client.get("/v1/messages", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 3)
        self.assertIn("Your HAX VPS is ready", data["messages"][0]["text"])
        self.assertIn("VPS will be removed", data["messages"][1]["text"])
        self.assertIn("Your Woiden IPv6 VPS is ready", data["messages"][2]["text"])

        # 2. Filter by sender (with or without @)
        resp_sender = self.client.get("/v1/messages?sender=@HaxTG_bot", headers=headers)
        self.assertEqual(resp_sender.status_code, 200)
        hax_data = resp_sender.json()
        self.assertEqual(hax_data["count"], 2)
        self.assertEqual(hax_data["messages"][0]["sender_username"], "HaxTG_bot")

        # 3. Filter by account
        resp_acc = self.client.get("/v1/messages?account=acc2", headers=headers)
        self.assertEqual(resp_acc.status_code, 200)
        acc_data = resp_acc.json()
        self.assertEqual(acc_data["count"], 1)
        self.assertEqual(acc_data["messages"][0]["sender_username"], "WoidenTG_bot")

        # 4. Filter by since
        resp_since = self.client.get("/v1/messages?since=1700000005.0", headers=headers)
        self.assertEqual(resp_since.status_code, 200)
        since_data = resp_since.json()
        self.assertEqual(since_data["count"], 2)
        self.assertIn("VPS will be removed", since_data["messages"][0]["text"])


if __name__ == "__main__":
    unittest.main()
