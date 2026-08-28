import sys
import unittest
from unittest.mock import patch

import smoke_check


class SmokeCheckTests(unittest.TestCase):
    def run_main(self, responses, *, token="test-secret"):
        calls = []

        def fake_request(base_url, path, *, token=""):
            calls.append((path, token))
            return responses[path]

        argv = ["smoke_check.py", "--base-url", "http://relay.test"]
        if token:
            argv.extend(["--token", token])
        with patch.object(smoke_check, "_request", side_effect=fake_request), patch.object(sys, "argv", argv):
            return smoke_check.main(), calls

    def test_full_smoke_uses_real_protected_route(self):
        code, calls = self.run_main(
            {
                "/healthz": (200, '{"status":"ok"}'),
                "/readyz": (200, '{"status":"ready"}'),
                "/v1/otp/requests/smoke-check": (401, '{"detail":"unauthorized"}'),
            }
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            calls,
            [
                ("/healthz", ""),
                ("/readyz", "test-secret"),
                ("/v1/otp/requests/smoke-check", "invalid-test-token"),
            ],
        )

    def test_readiness_failure_is_fatal(self):
        code, calls = self.run_main(
            {
                "/healthz": (200, '{"status":"ok"}'),
                "/readyz": (503, '{"detail":"telegram relay not ready"}'),
            }
        )
        self.assertEqual(code, 1)
        self.assertEqual(calls[-1][0], "/readyz")

    def test_liveness_only_mode_does_not_require_token(self):
        code, calls = self.run_main(
            {"/healthz": (200, '{"status":"ok"}')},
            token="",
        )
        self.assertEqual(code, 0)
        self.assertEqual(calls, [("/healthz", "")])


if __name__ == "__main__":
    unittest.main()
