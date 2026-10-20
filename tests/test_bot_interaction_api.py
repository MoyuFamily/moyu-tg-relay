from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from fastapi import BackgroundTasks, HTTPException
from typing_extensions import Self

from moyu_tg_relay import app
from moyu_tg_relay.accounts import AccountConfig, AccountIdentity, AccountRuntime
from moyu_tg_relay.bot_interaction import BotInteractionStore


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


class DummyConversation:
    def __init__(self, initial_msg: DummyMessage, result_msg: DummyMessage | None = None) -> None:
        self.initial_msg = initial_msg
        self.result_msg = result_msg
        self.sent_messages: list[str] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    async def send_message(self, text: str) -> None:
        self.sent_messages.append(text)

    async def get_response(self, timeout: float = 10.0) -> DummyMessage:
        if self.sent_messages and not hasattr(self, "_got_initial"):
            self._got_initial = True
            return self.initial_msg
        if self.result_msg is not None:
            return self.result_msg
        raise asyncio.TimeoutError()

    async def get_edit(self, msg: DummyMessage, timeout: float = 10.0) -> DummyMessage:
        # Forever wait unless result_msg is an edit
        await asyncio.sleep(timeout + 1)
        raise asyncio.TimeoutError()


class TestBotInteractionApi(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store_file = Path(self.temp_dir.name) / "bot_interactions.json"
        self.original_bot_store = app.bot_store
        self.original_token = app.RELAY_TOKEN
        self.original_account_id = app.TELEGRAM_ACCOUNT_ID
        self.original_runtimes = dict(app.account_runtimes)

        app.RELAY_TOKEN = "test-token"
        app.TELEGRAM_ACCOUNT_ID = "8812441677"
        os.environ["BOT_INTERACTION_CLICK_DELAY"] = "0"
        app.bot_store = BotInteractionStore(persistence_path=self.store_file)

        # Setup mock runtime
        self.mock_client = MagicMock()
        self.mock_client.is_connected.return_value = True

        cfg = AccountConfig(
            account_id="8812441677",
            api_id=12345,
            api_hash="hash",
            session_path="dummy.session",
        )
        ident = AccountIdentity(account_id="8812441677", phone="12345", username="tester")
        self.runtime = AccountRuntime(
            config=cfg,
            identity=ident,
            status="ready",
            client=self.mock_client,
            lock=asyncio.Lock(),
        )
        app.account_runtimes.clear()
        app.account_runtimes["8812441677"] = self.runtime

    async def asyncTearDown(self) -> None:
        app.account_runtimes.clear()
        app.account_runtimes.update(self.original_runtimes)
        app.bot_store = self.original_bot_store
        app.RELAY_TOKEN = self.original_token
        app.TELEGRAM_ACCOUNT_ID = self.original_account_id
        self.temp_dir.cleanup()

    async def test_create_bot_interaction_validation(self) -> None:
        bg = BackgroundTasks()

        # Missing bot
        with self.assertRaises(HTTPException) as ctx:
            app.create_bot_interaction(
                app.CreateBotInteractionRequest(bot="", command="/start"),
                bg,
            )
        self.assertEqual(ctx.exception.status_code, 400)

        # Unknown account
        with self.assertRaises(HTTPException) as ctx:
            app.create_bot_interaction(
                app.CreateBotInteractionRequest(bot="test_bot", account="9999999999"),
                bg,
            )
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_create_and_get_bot_interaction(self) -> None:
        bg = BackgroundTasks()
        resp = app.create_bot_interaction(
            app.CreateBotInteractionRequest(
                bot="sheeridverifier_bot",
                command="/start",
                action=["🎁 出席并获得奖励", "Điểm danh"],
                wait_response_timeout=10.0,
                wait_result_timeout=20.0,
            ),
            bg,
        )

        self.assertTrue(resp.interaction_id.startswith("bint_"))
        self.assertEqual(resp.status, "pending")
        self.assertEqual(resp.account, "8812441677")
        self.assertEqual(resp.bot, "sheeridverifier_bot")

        # Query status
        status_resp = app.get_bot_interaction(resp.interaction_id)
        self.assertEqual(status_resp.interaction_id, resp.interaction_id)
        self.assertEqual(status_resp.status, "pending")

        # 404 for unknown id
        with self.assertRaises(HTTPException) as ctx:
            app.get_bot_interaction("unknown_id")
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_cancel_bot_interaction(self) -> None:
        bg = BackgroundTasks()
        resp = app.create_bot_interaction(
            app.CreateBotInteractionRequest(bot="sheeridverifier_bot"),
            bg,
        )
        cancel_resp = app.cancel_bot_interaction(resp.interaction_id)
        self.assertEqual(cancel_resp.status_code, 204)

        status_resp = app.get_bot_interaction(resp.interaction_id)
        self.assertEqual(status_resp.status, "cancelled")

    async def test_execute_bot_interaction_success_flow(self) -> None:
        btn_checkin = DummyButton("🎁 出席并获得奖励")
        btn_cancel = DummyButton("❌ 取消")
        initial_msg = DummyMessage(1537, "欢迎！", [[btn_checkin, btn_cancel]])
        result_msg = DummyMessage(1538, "🎉 出席率 成功！\n💎 +1 硬币| $0.04\n💰 平衡： 2 硬币", [])

        conv = DummyConversation(initial_msg=initial_msg, result_msg=result_msg)
        self.mock_client.conversation.return_value = conv

        item = app.bot_store.create(
            account="8812441677",
            bot="sheeridverifier_bot",
            command="/start",
            action=["🎁 出席并获得奖励", "Điểm danh"],
            wait_response_timeout=5.0,
            wait_result_timeout=5.0,
        )

        await app._execute_bot_interaction(item.interaction_id)

        res = app.bot_store.get(item.interaction_id)
        self.assertEqual(res.status, "completed")
        self.assertEqual(res.stage, "done")
        self.assertEqual(res.action_clicked, "🎁 出席并获得奖励")
        self.assertTrue(btn_checkin.clicked)
        self.assertIsNotNone(res.initial_message)
        self.assertIsNotNone(res.result_message)
        self.assertEqual(res.result_message["id"], 1538)
        self.assertIn("🎉 出席率 成功！", res.result_message["text"])
