import tempfile
import time
import unittest
from pathlib import Path

from moyu_tg_relay.log_store import RelayLogStore


class TestRelayLogStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_logs.db"
        self.current_time = 1700000000.0
        self.store = RelayLogStore(
            db_path=self.db_path,
            retention_days=15,
            clock=lambda: self.current_time,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_record_and_query_basic(self):
        log_id = self.store.record(
            level="INFO",
            category="telegram",
            message="Telegram message received",
            provider="hax",
            account="12345678",
            request_id="req-123",
            detail="Button found: Confirm",
            extra={"button": "Confirm", "sender": "HaxTG_bot"},
        )
        self.assertGreater(log_id, 0)

        result = self.store.query_logs(page=1, page_size=10)
        self.assertEqual(result["total"], 1)
        self.assertEqual(len(result["logs"]), 1)
        log = result["logs"][0]
        self.assertEqual(log["id"], log_id)
        self.assertEqual(log["level"], "INFO")
        self.assertEqual(log["category"], "telegram")
        self.assertEqual(log["message"], "Telegram message received")
        self.assertEqual(log["provider"], "hax")
        self.assertEqual(log["account"], "12345678")
        self.assertEqual(log["request_id"], "req-123")
        self.assertEqual(log["detail"], "Button found: Confirm")
        self.assertEqual(log["extra"]["button"], "Confirm")
        self.assertEqual(log["extra"]["sender"], "HaxTG_bot")

    def test_filtering_and_pagination(self):
        for i in range(1, 26):
            lvl = "ERROR" if i % 5 == 0 else "INFO"
            cat = "provider" if i % 2 == 0 else "otp_request"
            self.store.record(
                level=lvl,
                category=cat,
                message=f"Log event #{i}",
                provider="hax" if i % 3 == 0 else "generic",
                request_id=f"req-{i}",
                detail=f"detail {i}",
            )

        # Total count
        all_logs = self.store.query_logs(page=1, page_size=10)
        self.assertEqual(all_logs["total"], 25)
        self.assertEqual(len(all_logs["logs"]), 10)
        self.assertEqual(all_logs["total_pages"], 3)

        # Filter by level
        error_logs = self.store.query_logs(level="ERROR")
        self.assertEqual(error_logs["total"], 5)
        for row in error_logs["logs"]:
            self.assertEqual(row["level"], "ERROR")

        # Filter by category
        provider_logs = self.store.query_logs(category="provider")
        self.assertEqual(provider_logs["total"], 12)

        # Search keyword
        search_res = self.store.query_logs(search="Log event #10")
        self.assertEqual(search_res["total"], 1)
        self.assertEqual(search_res["logs"][0]["message"], "Log event #10")

        # Provider filter
        hax_res = self.store.query_logs(provider="hax")
        self.assertEqual(hax_res["total"], 8)

    def test_fifteen_day_prune_retention(self):
        one_day = 86400.0

        # Record a log 16 days ago
        self.current_time = 1700000000.0 - (16 * one_day)
        old_id = self.store.record("INFO", "system", "Old log from 16 days ago")

        # Record a log 14 days ago (within 15 days)
        self.current_time = 1700000000.0 - (14 * one_day)
        valid_id_1 = self.store.record("INFO", "system", "Valid log from 14 days ago")

        # Record a log today
        self.current_time = 1700000000.0
        valid_id_2 = self.store.record("INFO", "system", "Log today")

        # Query before prune
        res_before = self.store.query_logs()
        self.assertEqual(res_before["total"], 3)

        # Run prune
        deleted = self.store.prune()
        self.assertEqual(deleted, 1)

        # Query after prune
        res_after = self.store.query_logs()
        self.assertEqual(res_after["total"], 2)
        remaining_ids = {item["id"] for item in res_after["logs"]}
        self.assertNotIn(old_id, remaining_ids)
        self.assertIn(valid_id_1, remaining_ids)
        self.assertIn(valid_id_2, remaining_ids)

    def test_get_stats(self):
        one_day = 86400.0
        self.current_time = 1700000000.0

        self.store.record("INFO", "telegram", "Msg 1", request_id="r1")
        self.store.record("WARNING", "provider", "Msg 2", request_id="r1")
        self.store.record("ERROR", "system", "Msg 3", request_id="r2")

        stats = self.store.get_stats()
        self.assertEqual(stats["total_logs"], 3)
        self.assertEqual(stats["logs_24h"], 3)
        self.assertEqual(stats["requests_24h"], 2)
        self.assertEqual(stats["level_counts"]["INFO"], 1)
        self.assertEqual(stats["level_counts"]["WARNING"], 1)
        self.assertEqual(stats["level_counts"]["ERROR"], 1)
        self.assertEqual(stats["category_counts"]["telegram"], 1)
        self.assertEqual(stats["category_counts"]["provider"], 1)
        self.assertEqual(stats["category_counts"]["system"], 1)
        self.assertEqual(stats["retention_days"], 15)


if __name__ == "__main__":
    unittest.main()
