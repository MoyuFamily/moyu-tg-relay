import unittest

from moyu_tg_relay.providers.hax import HaxProvider, extract_verification_code


class HaxProviderTests(unittest.TestCase):
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

    def test_hax_provider_defaults(self):
        provider = HaxProvider.from_env()
        self.assertEqual(provider.name, "hax")
        self.assertEqual(provider.bot_username, "HaxTG_bot")
        self.assertTrue(provider.auto_confirm)
        self.assertIn("777000", provider.confirmation_sender_ids)
        self.assertIn("hax.co.id", provider.confirmation_markers)
        self.assertIn("confirm", provider.auto_confirm_buttons)


if __name__ == "__main__":
    unittest.main()
