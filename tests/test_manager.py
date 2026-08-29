from __future__ import annotations

import argparse
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import manager


class ManagerTests(unittest.TestCase):
    def test_default_listen_host_and_port(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0)
            code = manager.handle_run_service()
            self.assertEqual(code, 0)
            args, kwargs = mock_run.call_args
            cmd = args[0]
            self.assertIn("--host", cmd)
            self.assertEqual(cmd[cmd.index("--host") + 1], "127.0.0.1")
            self.assertIn("--port", cmd)
            self.assertEqual(cmd[cmd.index("--port") + 1], "8787")

    def test_cli_parser_defaults(self):
        with mock.patch("sys.argv", ["manager.py", "run"]):
            with mock.patch("scripts.manager.handle_run_service", return_value=0) as mock_handle:
                code = manager.main()
                self.assertEqual(code, 0)
                mock_handle.assert_called_once_with(host="127.0.0.1", port=8787, reload=True)

    def test_handle_smoke_check_propagates_returncode(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=42)
            code = manager.handle_smoke_check(url="http://127.0.0.1:8787", token="secret")
            self.assertEqual(code, 42)

    def test_handle_unit_tests_propagates_pytest_failure_without_unittest_fallback(self):
        def fake_run(cmd, *args, **kwargs):
            if "-c" in cmd and "import pytest" in cmd[cmd.index("-c") + 1]:
                return mock.MagicMock(returncode=0)
            if "-m" in cmd and "pytest" in cmd:
                return mock.MagicMock(returncode=2)
            return mock.MagicMock(returncode=0)

        with mock.patch("subprocess.run", side_effect=fake_run) as mock_run:
            code = manager.handle_unit_tests()
            self.assertEqual(code, 2)
            # Verify unittest discover was NOT called
            for call in mock_run.call_args_list:
                cmd = call[0][0]
                self.assertNotIn("unittest", cmd)

    def test_handle_unit_tests_fallbacks_to_unittest_when_pytest_not_installed(self):
        def fake_run(cmd, *args, **kwargs):
            if "-c" in cmd and "import pytest" in cmd[cmd.index("-c") + 1]:
                return mock.MagicMock(returncode=1)  # pytest not installed
            if "-m" in cmd and "unittest" in cmd:
                return mock.MagicMock(returncode=3)
            return mock.MagicMock(returncode=0)

        with mock.patch("subprocess.run", side_effect=fake_run) as mock_run:
            code = manager.handle_unit_tests()
            self.assertEqual(code, 3)
            unittest_called = any("unittest" in call[0][0] for call in mock_run.call_args_list)
            self.assertTrue(unittest_called)

    def test_main_propagates_exit_codes(self):
        with mock.patch("sys.argv", ["manager.py", "smoke"]):
            with mock.patch("scripts.manager.handle_smoke_check", return_value=5):
                self.assertEqual(manager.main(), 5)

        with mock.patch("sys.argv", ["manager.py", "test"]):
            with mock.patch("scripts.manager.handle_unit_tests", return_value=7):
                self.assertEqual(manager.main(), 7)

    def test_load_env_map(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text(
                "OTP_RELAY_BEARER_TOKEN=my-secret-token\nexport HAX_AUTO_CONFIRM=true\n",
                encoding="utf-8",
            )
            with mock.patch.object(manager, "ENV_FILE", env_file):
                env_map = manager.load_env_map()
                self.assertEqual(env_map.get("OTP_RELAY_BEARER_TOKEN"), "my-secret-token")
                self.assertEqual(env_map.get("HAX_AUTO_CONFIRM"), "true")

    def test_find_session_files_discovers_state_and_explicit_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)
            state_dir = tmp_root / ".state"
            state_dir.mkdir()
            sess_file = state_dir / "telegram.session"
            sess_file.write_text("session data", encoding="utf-8")

            with mock.patch.object(manager, "ROOT", tmp_root):
                # 1. Default discovery in .state/
                found = manager.find_session_files({})
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0].resolve(), sess_file.resolve())

                # 2. Explicit custom path via TELEGRAM_SESSION_PATH
                custom_sess = tmp_root / "custom.session"
                custom_sess.write_text("custom session", encoding="utf-8")
                found_custom = manager.find_session_files({"TELEGRAM_SESSION_PATH": str(custom_sess)})
                found_paths = [f.resolve() for f in found_custom]
                self.assertIn(custom_sess.resolve(), found_paths)
                self.assertIn(sess_file.resolve(), found_paths)


if __name__ == "__main__":
    unittest.main()
