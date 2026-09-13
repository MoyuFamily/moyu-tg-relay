import unittest
from types import SimpleNamespace

from moyu_tg_relay.providers import build_provider_registry
from moyu_tg_relay.providers.base import IncomingMessage
from moyu_tg_relay.providers.woiden import WoidenProvider


class WoidenProviderTests(unittest.TestCase):
    def test_woiden_provider_in_registry(self):
        registry = build_provider_registry()
        self.assertIn("woiden", registry)
        self.assertIsInstance(registry["woiden"], WoidenProvider)

    def test_woiden_provider_defaults(self):
        provider = WoidenProvider.from_env()
        self.assertEqual(provider.name, "woiden")
        self.assertEqual(provider.bot_username, "HaxTG_bot")
        self.assertTrue(provider.auto_confirm)
        self.assertIn("777000", provider.confirmation_sender_ids)
        self.assertIn("woiden.id", provider.confirmation_markers)
        self.assertIn("woiden", provider.confirmation_markers)
        self.assertIn("hax.co.id", provider.confirmation_markers)
        self.assertIn("confirm", provider.auto_confirm_buttons)
        self.assertIn("确认", provider.auto_confirm_buttons)

    def test_woiden_code_extraction(self):
        provider = WoidenProvider.from_env()
        message = IncomingMessage(
            sender_username="HaxTG_bot",
            sender_id="123456",
            text="Your Code is \nODgxMjQ0MTY3Nzo6OjMxZDJjNGU2MDM2Zjg0YmUxZjQwMmFkMjdlOTE3NDA3",
            buttons=(),
        )
        request = SimpleNamespace(
            context={"source": "renew-provider", "stage": "login"},
            account="123",
        )
        decision = provider.evaluate(message, request)
        self.assertEqual(decision.action, "code")
        self.assertEqual(
            decision.code,
            "ODgxMjQ0MTY3Nzo6OjMxZDJjNGU2MDM2Zjg0YmUxZjQwMmFkMjdlOTE3NDA3",
        )

    def test_woiden_provider_recognizes_woiden_confirm_card(self):
        provider = WoidenProvider.from_env()
        request = SimpleNamespace(
            context={"source": "renew-provider", "stage": "login"},
            account="123",
        )
        button = SimpleNamespace(text="确认", kind="callback")
        message = IncomingMessage(
            sender_username="",
            sender_id="777000",
            text="We received a request to log in to woiden.id with your Telegram account.",
            buttons=(button,),
        )
        decision = provider.evaluate(message, request)
        self.assertEqual(decision.action, "click")
        self.assertEqual(decision.button, button)


if __name__ == "__main__":
    unittest.main()
