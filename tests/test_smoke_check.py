import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import smoke_check


class SmokeCheckTests(unittest.TestCase):
    def run_main(self, responses, *, token="test-secret", env_file=""):
        calls = []

        def fake_request(base_url, path, *, token=""):
            calls.append((path, token))
            response = responses[path]
            return response(token) if callable(response) else response

        argv = ["smoke_check.py", "--base-url", "http://relay.test"]
        if token is not None:
            argv.extend(["--token", token])
        if env_file:
            argv.extend(["--env-file", env_file])
        with patch.object(smoke_check, "_request", side_effect=fake_request), patch.object(
            sys, "argv", argv
        ):
            return smoke_check.main(), calls

    def test_full_smoke_verifies_rejection_and_acceptance(self):
        protected_path = smoke_check._SMOKE_REQUEST_PATH

        def protected_response(token):
            if token == "invalid-test-token":
                return 401, '{"detail":"unauthorized"}'
            if token == "test-secret":
                return 404, '{"detail":"request not found"}'
            return 500, "{}"

        code, calls = self.run_main(
            {
                "/healthz": (200, '{"status":"ok"}'),
                "/readyz": (200, '{"status":"ready"}'),
                protected_path: protected_response,
            }
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            calls,
            [
                ("/healthz", ""),
                ("/readyz", "test-secret"),
                (protected_path, "invalid-test-token"),
                (protected_path, "test-secret"),
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

    def test_env_file_supplies_token_without_shell_evaluation(self):
        protected_path = smoke_check._SMOKE_REQUEST_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / "relay.env"
            env_path.write_text(
                "OTP_RELAY_BEARER_TOKEN='literal-$HOME-token'\n",
                encoding="utf-8",
            )

            def protected_response(token):
                if token == "invalid-test-token":
                    return 401, "{}"
                if token == "literal-$HOME-token":
                    return 404, "{}"
                return 500, "{}"

            code, calls = self.run_main(
                {
                    "/healthz": (200, '{"status":"ok"}'),
                    "/readyz": (200, '{"status":"ready"}'),
                    protected_path: protected_response,
                },
                token=None,
                env_file=str(env_path),
            )

        self.assertEqual(code, 0)
        self.assertIn(("/readyz", "literal-$HOME-token"), calls)


if __name__ == "__main__":
    unittest.main()
