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

        old_state = os.environ.get("STATE_DIR")
        old_sess = os.environ.get("TELEGRAM_SESSION_PATH")
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                custom_dir = str(Path(tmp_dir) / "custom_state")
                os.environ["STATE_DIR"] = custom_dir
                resolved_state = _resolve_state_dir()
                self.assertEqual(resolved_state, Path(custom_dir))

                os.environ["TELEGRAM_SESSION_PATH"] = "./.state/my.session"
                self.assertTrue(_resolve_session_path().endswith("my.session"))
            finally:
                if old_state is not None:
                    os.environ["STATE_DIR"] = old_state
                else:
                    os.environ.pop("STATE_DIR", None)
                if old_sess is not None:
                    os.environ["TELEGRAM_SESSION_PATH"] = old_sess
                else:
                    os.environ.pop("TELEGRAM_SESSION_PATH", None)


if __name__ == "__main__":
    unittest.main()
