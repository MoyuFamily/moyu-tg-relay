import tempfile
import time
import unittest
from pathlib import Path

from fastapi import HTTPException

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

    def tearDown(self):
        self.temp_dir.cleanup()
        app.RELAY_TOKEN = self.original_token
        app.log_store = self.original_log_store

    def test_messages_endpoint_requires_auth(self):
        # 1. No Authorization header
        with self.assertRaises(HTTPException) as ctx:
            app.require_auth(None)
        self.assertEqual(ctx.exception.status_code, 401)

        # 2. Invalid Bearer token
        with self.assertRaises(HTTPException) as ctx:
            app.require_auth("Bearer wrong-token")
        self.assertEqual(ctx.exception.status_code, 401)

        # 3. Valid Bearer token
        app.require_auth("Bearer secret-test-token")

    def test_messages_endpoint_empty(self):
        data = app.list_messages()
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["messages"], [])

    def test_messages_endpoint_records_and_filters(self):
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
        data = app.list_messages()
        self.assertEqual(data["count"], 3)
        self.assertIn("Your HAX VPS is ready", data["messages"][0]["text"])
        self.assertIn("VPS will be removed", data["messages"][1]["text"])
        self.assertIn("Your Woiden IPv6 VPS is ready", data["messages"][2]["text"])

        # 2. Filter by sender (with or without @)
        hax_data = app.list_messages(sender="@HaxTG_bot")
        self.assertEqual(hax_data["count"], 2)
        self.assertEqual(hax_data["messages"][0]["sender_username"], "HaxTG_bot")

        # 3. Filter by account
        acc_data = app.list_messages(account="acc2")
        self.assertEqual(acc_data["count"], 1)
        self.assertEqual(acc_data["messages"][0]["sender_username"], "WoidenTG_bot")

        # 4. Filter by since
        since_data = app.list_messages(since=1700000005.0)
        self.assertEqual(since_data["count"], 2)
        self.assertIn("VPS will be removed", since_data["messages"][0]["text"])

        # 5. Filter by since_id
        first_id = data["messages"][0]["id"]
        since_id_data = app.list_messages(since_id=first_id)
        self.assertEqual(since_id_data["count"], 2)
        self.assertEqual(since_id_data["messages"][0]["id"], data["messages"][1]["id"])


if __name__ == "__main__":
    unittest.main()
