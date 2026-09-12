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

    def test_multiline_quoted_value_supported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "relay.env"
            path.write_text(
                "KEY_ONE='[\n  {\"name\": \"value\"}\n]'\n"
                "KEY_TWO=\"line1\nline2\"\n"
                "KEY_THREE=simple\n",
                encoding="utf-8",
            )
            values = load_env_file(str(path))

        self.assertEqual(values["KEY_ONE"], "[\n  {\"name\": \"value\"}\n]")
        self.assertEqual(values["KEY_TWO"], "line1\nline2")
        self.assertEqual(values["KEY_THREE"], "simple")

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
 
    def test_save_account_to_accounts_json_creates_multiline_formatted_json(self):
        from moyu_tg_relay.bootstrap_session import save_account_to_accounts_json
        from moyu_tg_relay.accounts import load_account_configs

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "relay.env"
            save_account_to_accounts_json(
                path,
                account_id="111",
                api_id=12345,
                api_hash="hash1",
                session_string="sess-1",
                phone="1234567890",
            )
            content = path.read_text(encoding="utf-8")
            self.assertIn("TELEGRAM_ACCOUNTS_JSON='[", content)
            self.assertIn('  {\n    "account_id": "111",', content)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

            values = load_env_file(str(path))
            configs = load_account_configs(values)
            self.assertEqual(len(configs), 1)
            self.assertEqual(configs[0].account_id, "111")
            self.assertEqual(configs[0].phone, "1234567890")

    def test_save_account_to_accounts_json_updates_existing_placeholder(self):
        from moyu_tg_relay.bootstrap_session import save_account_to_accounts_json
        from moyu_tg_relay.accounts import load_account_configs

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "relay.env"
            path.write_text(
                "TELEGRAM_ACCOUNTS_JSON='[\n"
                "  {\n"
                '    "account_id": "111",\n'
                '    "api_id": 12345,\n'
                '    "api_hash": "hash1",\n'
                '    "session_string": "sess-1"\n'
                "  },\n"
                "  {\n"
                '    "account_id": "222",\n'
                '    "api_id": 67890,\n'
                '    "api_hash": "hash2",\n'
                '    "session_string": "<placeholder>"\n'
                "  }\n"
                "]'\n",
                encoding="utf-8",
            )
            save_account_to_accounts_json(
                path,
                account_id="222",
                api_id=67890,
                api_hash="hash2",
                session_string="sess-2-real",
            )
            values = load_env_file(str(path))
            configs = load_account_configs(values)
            self.assertEqual(len(configs), 2)
            self.assertEqual(configs[0].account_id, "111")
            self.assertEqual(configs[0].session_string, "sess-1")
            self.assertEqual(configs[1].account_id, "222")
            self.assertEqual(configs[1].session_string, "sess-2-real")

    def test_interactive_bootstrap_writes_to_multi_account_json(self):
        from unittest.mock import AsyncMock, patch
        from moyu_tg_relay.bootstrap_session import interactive_bootstrap
        from moyu_tg_relay.accounts import load_account_configs

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "relay.env"
            path.write_text(
                "TELEGRAM_API_ID=123456\n"
                "TELEGRAM_API_HASH=aabbccddeeff00112233445566778899\n"
                "OTP_RELAY_BEARER_TOKEN=token-123\n"
                "TELEGRAM_ACCOUNT_ID=101\n"
                "TELEGRAM_SESSION_STRING=old-single-session\n",
                encoding="utf-8",
            )
            with patch("moyu_tg_relay.bootstrap_session.bootstrap_string_session", new=AsyncMock(return_value=("session-999", 999))):
                code = interactive_bootstrap(path)

            self.assertEqual(code, 0)
            values = load_env_file(str(path))
            self.assertIn("TELEGRAM_ACCOUNTS_JSON", values)
            self.assertNotIn("TELEGRAM_ACCOUNT_ID", values)
            self.assertNotIn("TELEGRAM_SESSION_STRING", values)

            configs = load_account_configs(values)
            self.assertEqual([c.account_id for c in configs], ["101", "999"])
            self.assertEqual(configs[1].session_string, "session-999")


if __name__ == "__main__":
    unittest.main()

