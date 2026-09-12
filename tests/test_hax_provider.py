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
        self.assertEqual(
            extract_verification_code(
                "Your Code is \nODgxMjQ0MTY3Nzo6OjMxZDJjNGU2MDM2Zjg0YmUxZjQwMmFkMjdlOTE3NDA3"
            ),
            "ODgxMjQ0MTY3Nzo6OjMxZDJjNGU2MDM2Zjg0YmUxZjQwMmFkMjdlOTE3NDA3",
        )
        self.assertEqual(
            extract_verification_code(
                "Your Code is\nODgxMjQ0MTY3Nzo6OmVjYWIwOWM0OGJiMzc4MGViM2QzMTNkYzliYTc1NDFk"
            ),
            "ODgxMjQ0MTY3Nzo6OmVjYWIwOWM0OGJiMzc4MGViM2QzMTNkYzliYTc1NDFk",
        )

    def test_hax_provider_defaults(self):
        provider = HaxProvider.from_env()
        self.assertEqual(provider.name, "hax")
        self.assertEqual(provider.bot_username, "HaxTG_bot")
        self.assertTrue(provider.auto_confirm)
        self.assertIn("777000", provider.confirmation_sender_ids)
        self.assertIn("hax.co.id", provider.confirmation_markers)
        self.assertIn("confirm", provider.auto_confirm_buttons)
        self.assertIn("确认", provider.auto_confirm_buttons)
        self.assertIn("允许", provider.auto_confirm_buttons)

    def test_hax_provider_recognizes_chinese_confirm_buttons(self):
        from moyu_tg_relay.providers.base import IncomingMessage
        from types import SimpleNamespace

        provider = HaxProvider.from_env()
        request = SimpleNamespace(
            context={"source": "renew-provider", "stage": "login"},
            account="123",
        )
        button = SimpleNamespace(text="确认", kind="callback")
        message = IncomingMessage(
            sender_username="",
            sender_id="777000",
            text="We received a request to log in to hax.co.id with your Telegram account.",
            buttons=(button,),
        )
        decision = provider.evaluate(message, request)
        self.assertEqual(decision.action, "click")
        self.assertEqual(decision.button, button)


if __name__ == "__main__":
    unittest.main()
