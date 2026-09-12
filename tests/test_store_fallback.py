import unittest

from moyu_tg_relay.store import PendingOtpStore


class StoreFallbackTests(unittest.TestCase):
    def test_code_can_arrive_after_human_required(self):
        store = PendingOtpStore()
        request = store.create("123", 300)

        self.assertEqual(
            store.mark_human_required(account="123", detail="manual confirm"),
            request.request_id,
        )
        self.assertEqual(store.get(request.request_id).status, "human_required")

        self.assertEqual(
            store.attach_code(account="123", code="83379232"),
            request.request_id,
        )
        self.assertEqual(store.get(request.request_id).status, "ready")
        self.assertEqual(store.consume(request.request_id), "83379232")

    def test_code_can_arrive_after_auto_attempt(self):
        store = PendingOtpStore()
        request = store.create("123", 300)

        self.assertEqual(
            store.mark_auto_attempted(account="123", detail="clicked"),
            request.request_id,
        )
        self.assertEqual(store.get(request.request_id).status, "auto_attempted")

        self.assertEqual(
            store.attach_code(account="123", code="83379232"),
            request.request_id,
        )
        self.assertEqual(store.get(request.request_id).status, "ready")


    def test_state_and_session_path_resolution(self):
        import os
        import tempfile
        from pathlib import Path
        from moyu_tg_relay.app import _resolve_session_path, _resolve_state_dir
        from moyu_tg_relay.log_store import RelayLogStore
        from moyu_tg_relay.store import PendingOtpStore

        old_state = os.environ.get("STATE_DIR")
        old_sess = os.environ.get("TELEGRAM_SESSION_PATH")
        old_otp = os.environ.get("OTP_STORE_FILE")
        old_log = os.environ.get("RELAY_LOG_DB_PATH")
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                custom_dir = str(Path(tmp_dir) / "custom_state")
                os.environ["STATE_DIR"] = custom_dir
                resolved_state = _resolve_state_dir()
                self.assertEqual(resolved_state, Path(custom_dir))
                self.assertTrue(resolved_state.is_dir())

                # Relative ./.state/... path resolves into custom_dir
                os.environ["TELEGRAM_SESSION_PATH"] = "./.state/my.session"
                self.assertEqual(_resolve_session_path(), str(Path(custom_dir) / "my.session"))

                os.environ["TELEGRAM_SESSION_PATH"] = ".state/custom.session"
                self.assertEqual(_resolve_session_path(), str(Path(custom_dir) / "custom.session"))

                # Absolute session path is preserved
                abs_session = str(Path(tmp_dir) / "other" / "abs.session")
                os.environ["TELEGRAM_SESSION_PATH"] = abs_session
                self.assertEqual(_resolve_session_path(), abs_session)

                # Store and log db default paths under custom STATE_DIR
                os.environ.pop("OTP_STORE_FILE", None)
                os.environ.pop("RELAY_LOG_DB_PATH", None)
                store_path = resolved_state / "pending_otp_store.json"
                log_db_path = store_path.parent / "relay_logs.db"

                test_store = PendingOtpStore(persistence_path=str(store_path))
                req = test_store.create(provider="test", account="acc1", ttl_seconds=300)
                test_store.attach_code(account="acc1", code="999888")
                self.assertTrue(store_path.is_file())

                test_log_store = RelayLogStore(db_path=str(log_db_path))
                test_log_store.record(level="INFO", category="test", message="hello from custom state")
                self.assertTrue(log_db_path.is_file())
                self.assertEqual(test_log_store.get_stats()["total_logs"], 1)
            finally:
                if old_state is not None:
                    os.environ["STATE_DIR"] = old_state
                else:
                    os.environ.pop("STATE_DIR", None)
                if old_sess is not None:
                    os.environ["TELEGRAM_SESSION_PATH"] = old_sess
                else:
                    os.environ.pop("TELEGRAM_SESSION_PATH", None)
                if old_otp is not None:
                    os.environ["OTP_STORE_FILE"] = old_otp
                else:
                    os.environ.pop("OTP_STORE_FILE", None)
                if old_log is not None:
                    os.environ["RELAY_LOG_DB_PATH"] = old_log
                else:
                    os.environ.pop("RELAY_LOG_DB_PATH", None)


if __name__ == "__main__":
    unittest.main()
