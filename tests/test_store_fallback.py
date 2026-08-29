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


if __name__ == "__main__":
    unittest.main()
