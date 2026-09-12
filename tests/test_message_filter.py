import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import moyu_tg_relay.app as relay_app
from moyu_tg_relay.store import PendingOtpStore


class MockSender:
    def __init__(
        self,
        *,
        id=12345,
        username="",
        bot=False,
        support=False,
        verified=False,
    ):
        self.id = id
        self.username = username
        self.bot = bot
        self.support = support
        self.verified = verified


class MockEvent:
    def __init__(
        self,
        *,
        sender_id=12345,
        sender=None,
        is_private=True,
        is_group=False,
        is_channel=False,
        raw_text="Hello test",
        buttons=None,
    ):
        self.sender_id = sender_id
        self._sender = sender or MockSender(id=sender_id)
        self.is_private = is_private
        self.is_group = is_group
        self.is_channel = is_channel
        self.raw_text = raw_text
        self.buttons = buttons or []

    async def get_sender(self):
        return self._sender


class MessageFilterTests(unittest.IsolatedAsyncioTestCase):
    async def test_group_messages_are_filtered_out(self):
        event = MockEvent(
            is_group=True,
            is_private=False,
            sender=MockSender(bot=True, username="any_bot"),
        )
        self.assertFalse(await relay_app._is_bot_or_system_event(event))

    async def test_channel_messages_are_filtered_out(self):
        event = MockEvent(
            is_channel=True,
            is_private=False,
            sender=MockSender(id=777000),
        )
        self.assertFalse(await relay_app._is_bot_or_system_event(event))

    async def test_non_private_chat_is_filtered_out(self):
        event = MockEvent(
            is_private=False,
            sender=MockSender(id=777000),
        )
        self.assertFalse(await relay_app._is_bot_or_system_event(event))

    async def test_human_direct_chat_is_filtered_out(self):
        # A normal human user (not a bot, not system ID, not official)
        human_sender = MockSender(
            id=987654321,
            username="friendly_human",
            bot=False,
            support=False,
            verified=False,
        )
        event = MockEvent(
            sender_id=987654321,
            sender=human_sender,
            is_private=True,
            raw_text="Hey, are you free tonight?",
        )
        self.assertFalse(await relay_app._is_bot_or_system_event(event))

    async def test_human_direct_chat_not_logged_and_not_processed(self):
        human_sender = MockSender(id=112233, username="alice", bot=False)
        event = MockEvent(sender_id=112233, sender=human_sender, is_private=True, raw_text="Hi")

        mock_log = MagicMock()
        store = PendingOtpStore()
        req = store.create("123", provider="hax")

        with (
            patch.object(relay_app, "log_store", mock_log),
            patch.object(relay_app, "store", store),
            patch.object(relay_app, "TELEGRAM_ACCOUNT_ID", "123"),
            patch.object(relay_app, "FILTER_CHAT_MESSAGES", True),
        ):
            await relay_app._handle_telegram_message(event)

        # Log store must NOT have received any log call
        mock_log.record.assert_not_called()
        # Active request must remain unaffected
        self.assertEqual(store.get(req.request_id).status, "pending")

    async def test_telegram_system_notification_777000_is_accepted(self):
        system_sender = MockSender(id=777000, username="", bot=False)
        event = MockEvent(
            sender_id=777000,
            sender=system_sender,
            is_private=True,
            raw_text="Login code: 123456",
        )
        self.assertTrue(await relay_app._is_bot_or_system_event(event))

    async def test_telegram_system_notification_42777_is_accepted(self):
        event = MockEvent(
            sender_id=42777,
            sender=MockSender(id=42777),
            is_private=True,
        )
        self.assertTrue(await relay_app._is_bot_or_system_event(event))

    async def test_bot_with_bot_flag_is_accepted(self):
        bot_sender = MockSender(id=998877, username="service_bot", bot=True)
        event = MockEvent(sender_id=998877, sender=bot_sender, is_private=True)
        self.assertTrue(await relay_app._is_bot_or_system_event(event))

    async def test_bot_with_username_suffix_is_accepted(self):
        bot_sender = MockSender(id=998877, username="HaxTG_bot", bot=False)
        event = MockEvent(sender_id=998877, sender=bot_sender, is_private=True)
        self.assertTrue(await relay_app._is_bot_or_system_event(event))

    async def test_telegram_official_verified_sender_is_accepted(self):
        verified_sender = MockSender(id=888, username="telegram", verified=True)
        event = MockEvent(sender_id=888, sender=verified_sender, is_private=True)
        self.assertTrue(await relay_app._is_bot_or_system_event(event))

    async def test_telegram_support_sender_is_accepted(self):
        support_sender = MockSender(id=999, username="support", support=True)
        event = MockEvent(sender_id=999, sender=support_sender, is_private=True)
        self.assertTrue(await relay_app._is_bot_or_system_event(event))

    async def test_provider_custom_bot_username_is_accepted(self):
        fake_provider = SimpleNamespace(name="myprov", bot_username="custom_relay_agent")
        event = MockEvent(
            sender=MockSender(id=333, username="custom_relay_agent", bot=False),
            is_private=True,
        )
        with patch.object(relay_app, "providers", {"myprov": fake_provider}):
            self.assertTrue(await relay_app._is_bot_or_system_event(event))

    async def test_filter_disabled_allows_all_messages(self):
        human_sender = MockSender(id=112233, username="alice", bot=False)
        event = MockEvent(sender_id=112233, sender=human_sender, is_private=True, raw_text="Hi")

        with patch.object(relay_app, "FILTER_CHAT_MESSAGES", False):
            self.assertTrue(await relay_app._is_bot_or_system_event(event))


if __name__ == "__main__":
    unittest.main()
