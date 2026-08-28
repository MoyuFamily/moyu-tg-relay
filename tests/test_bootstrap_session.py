import tempfile
import unittest
from pathlib import Path

from moyu_tg_relay.bootstrap_session import load_env_file


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


if __name__ == "__main__":
    unittest.main()
