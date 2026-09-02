import tempfile
import unittest
from pathlib import Path

from moyu_tg_relay.bootstrap_session import _explicit_session_path, load_env_file


class BootstrapSessionEnvTests(unittest.TestCase):
    def test_env_file_is_literal_and_supports_simple_quotes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "relay.env"
            path.write_text(
                "# comment\n"
                "export TELEGRAM_API_ID=123456\n"
                "TELEGRAM_API_HASH='literal-$HOME-hash'\n",
                encoding="utf-8",
            )
            values = load_env_file(str(path))

        self.assertEqual(values["TELEGRAM_API_ID"], "123456")
        self.assertEqual(values["TELEGRAM_API_HASH"], "literal-$HOME-hash")

    def test_invalid_env_line_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "relay.env"
            path.write_text("not-an-assignment\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                load_env_file(str(path))

    def test_explicit_session_path_preserves_file_session_mode(self):
        self.assertTrue(_explicit_session_path(["--session-path", "/tmp/relay.session"]))
        self.assertTrue(_explicit_session_path(["--session-path=/tmp/relay.session"]))
        self.assertFalse(_explicit_session_path(["--env-file", "/tmp/relay.env"]))


if __name__ == "__main__":
    unittest.main()
