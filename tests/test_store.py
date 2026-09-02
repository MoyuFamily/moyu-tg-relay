import unittest

from moyu_tg_relay.providers.hax import extract_verification_code
from moyu_tg_relay.store import PendingOtpStore


class FakeClock:
    def __init__(self, value=1000.0):
        self.value = value

    def __call__(self):
        return self.value


class RelayStoreTests(unittest.TestCase):
    def test_hax_code_extraction_fails_closed_on_unrelated_or_ambiguous_text(self):
        self.assertEqual(extract_verification_code("hello 12345678"), "")
        self.assertEqual(
            extract_verification_code("Verification code 12345678, id 87654321"),
            "",
        )
        self.assertEqual(
            extract_verification_code("Your Hax verification code is 12345678"),
            "12345678",
        )

    def test_only_one_active_request_per_telegram_account(self):
        clock = FakeClock()
        store = PendingOtpStore(clock=clock)
        first = store.create("123", 300, provider="hax")
        second = store.create("123", 300, provider="other")

        self.assertEqual(store.get(first.request_id).status, "cancelled")
        self.assertEqual(store.get(second.request_id).status, "pending")
        self.assertEqual(store.get(second.request_id).provider, "other")

    def test_code_is_one_time_consumed(self):
        store = PendingOtpStore()
        request = store.create("123", 300, provider="hax")
        request_id = store.attach_code(account="123", code="12345678")

        self.assertEqual(request_id, request.request_id)
        self.assertEqual(store.get(request.request_id).status, "ready")
        self.assertEqual(store.consume(request.request_id), "12345678")
        self.assertEqual(store.get(request.request_id).status, "consumed")
        with self.assertRaises(ValueError):
            store.consume(request.request_id)

    def test_store_accepts_provider_defined_non_numeric_code(self):
        store = PendingOtpStore()
        request = store.create("123", provider="custom")
        self.assertEqual(
            store.attach_code(account="123", code="ABC-42"),
            request.request_id,
        )

    def test_expired_request_rejects_late_code(self):
        clock = FakeClock()
        store = PendingOtpStore(clock=clock)
        request = store.create("123", 60, provider="hax")
        clock.value += 61

        self.assertEqual(store.get(request.request_id).status, "expired")
        self.assertEqual(store.attach_code(account="123", code="12345678"), "")

    def test_terminal_requests_are_pruned_after_retention_window(self):
        clock = FakeClock()
        store = PendingOtpStore(clock=clock)
        request = store.create("123", 60, provider="hax")
        store.cancel(request.request_id)

        clock.value += 60 + 600 + 1
        with self.assertRaises(KeyError):
            store.get(request.request_id)


if __name__ == "__main__":
    unittest.main()
