from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from moyu_tg_relay.bot_interaction import (
    BotInteractionStore,
    _find_matching_button,
    _serialize_message,
)


class DummyButton:
    def __init__(self, text: str) -> None:
        self.text = text
        self.clicked = False

    async def click(self) -> None:
        self.clicked = True


class DummyMessage:
    def __init__(self, msg_id: int, text: str, buttons: list[list[DummyButton]] | None = None) -> None:
        self.id = msg_id
        self.raw_text = text
        self.buttons = buttons or []
        self.date = None


class TestBotInteraction(unittest.TestCase):
    def test_serialize_message(self) -> None:
        btn1 = DummyButton("Yes")
        btn2 = DummyButton("No")
        msg = DummyMessage(101, "Hello world", [[btn1, btn2]])

        data = _serialize_message(msg)
        self.assertEqual(data["id"], 101)
        self.assertEqual(data["text"], "Hello world")
        self.assertEqual(data["buttons"], ["Yes", "No"])

    def test_find_matching_button_exact_and_substring(self) -> None:
        b1 = DummyButton("🤖 激活 Gemini Pro 1 年")
        b2 = DummyButton("🎁 出席并获得奖励")
        b3 = DummyButton("❌ 取消当前操作")
        buttons = [b1, b2, b3]

        # Exact match
        btn, text = _find_matching_button(buttons, "🎁 出席并获得奖励")
        self.assertIs(btn, b2)
        self.assertEqual(text, "🎁 出席并获得奖励")

        # Substring match
        btn, text = _find_matching_button(buttons, "出席")
        self.assertIs(btn, b2)
        self.assertEqual(text, "🎁 出席并获得奖励")

        # Not found
        btn, text = _find_matching_button(buttons, "不存在的按钮")
        self.assertIsNone(btn)
        self.assertIsNone(text)

    def test_find_matching_button_candidates_list(self) -> None:
        b1 = DummyButton("🎁 Điểm danh nhận thưởng")
        buttons = [b1]

        candidates = ["🎁 出席并获得奖励", "Điểm danh", "Attendance"]
        btn, text = _find_matching_button(buttons, candidates)
        self.assertIs(btn, b1)
        self.assertEqual(text, "🎁 Điểm danh nhận thưởng")

    def test_find_matching_button_regex(self) -> None:
        b1 = DummyButton("🎁 出席并获得奖励")
        buttons = [b1]

        btn, text = _find_matching_button(buttons, r"(?:出席|Điểm danh|Attendance)")
        self.assertIs(btn, b1)
        self.assertEqual(text, "🎁 出席并获得奖励")

    def test_bot_interaction_store_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "bot_store.json"
            clock_time = 1000.0

            def get_time():
                return clock_time

            store = BotInteractionStore(persistence_path=file_path, clock=get_time)

            # 1. Create
            item = store.create(
                account="8812441677",
                bot="sheeridverifier_bot",
                command="/start",
                action=["🎁 出席并获得奖励", "Điểm danh"],
                wait_response_timeout=15.0,
                wait_result_timeout=45.0,
            )

            self.assertTrue(item.interaction_id.startswith("bint_"))
            self.assertEqual(item.account, "8812441677")
            self.assertEqual(item.bot, "sheeridverifier_bot")
            self.assertEqual(item.status, "pending")

            # 2. Get
            retrieved = store.get(item.interaction_id)
            self.assertEqual(retrieved.interaction_id, item.interaction_id)

            # 3. Update progress
            store.update(
                item.interaction_id,
                status="in_progress",
                stage="waiting_result",
                action_clicked="🎁 出席并获得奖励",
            )
            self.assertEqual(store.get(item.interaction_id).status, "in_progress")
            self.assertEqual(store.get(item.interaction_id).action_clicked, "🎁 出席并获得奖励")

            # 4. Finish
            store.update(
                item.interaction_id,
                status="completed",
                stage="done",
                result_message={"text": "🎉 出席率 成功！"},
            )
            self.assertEqual(store.get(item.interaction_id).status, "completed")

            # 5. Reload from persistence
            store2 = BotInteractionStore(persistence_path=file_path, clock=get_time)
            reloaded = store2.get(item.interaction_id)
            self.assertEqual(reloaded.status, "completed")
            self.assertEqual(reloaded.result_message, {"text": "🎉 出席率 成功！"})

            # 6. Expiration
            clock_time += 1800.0 + item.expires_at
            store2._expire_locked()
            with self.assertRaises(KeyError):
                store2.get(item.interaction_id)


if __name__ == "__main__":
    unittest.main()
