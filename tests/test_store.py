import unittest

from moyu_tg_relay.store import PendingOtpStore, extract_hax_verification_code


class FakeClock:
    def __init__(self, value=1000.0):
        self.value = value

    def __call__(self):
        return self.value


class HaxOtpRelayStoreTests(unittest.TestCase):
    def test_code_extraction_fails_closed_on_unrelated_or_ambiguous_text(self):
        self.assertEqual(extract_hax_verification_code("hello 12345678"), "")
        self.assertEqual(
            extract_hax_verification_code("Verification code 12345678, id 87654321"),
            "",
        )
        self.assertEqual(
            extract_hax_verification_code("Your Hax verification code is 12345678"),
            "12345678",
        )

    def test_only_one_active_request_per_telegram_account(self):
        clock = FakeClock()
        store = PendingOtpStore(clock=clock)
        first = store.create("123", 300)
        second = store.create("123", 300)

        self.assertEqual(store.get(first.request_id).status, "cancelled")
        self.assertEqual(store.get(second.request_id).status, "pending")

    def test_code_is_one_time_consumed(self):
        store = PendingOtpStore()
        request = store.create("123", 300)
        request_id = store.attach_code(account="123", code="12345678")

        self.assertEqual(request_id, request.request_id)
        self.assertEqual(store.get(request.request_id).status, "ready")
        self.assertEqual(store.consume(request.request_id), "12345678")
        self.assertEqual(store.get(request.request_id).status, "consumed")
        with self.assertRaises(ValueError):
            store.consume(request.request_id)

    def test_expired_request_rejects_late_code(self):
        clock = FakeClock()
        store = PendingOtpStore(clock=clock)
        request = store.create("123", 60)
        clock.value += 61

        self.assertEqual(store.get(request.request_id).status, "expired")
        self.assertEqual(store.attach_code(account="123", code="12345678"), "")


if __name__ == "__main__":
    unittest.main()
