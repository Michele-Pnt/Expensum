import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

pytestmark = pytest.mark.integration


def _make_update_context(chat_id: str, args: list[str]):
    update = MagicMock()
    update.effective_chat.id = int(chat_id)
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = args
    return update, context


def test_cmd_start_link_payload_reassigns_web_account(monkeypatch):
    import bot

    web_chat_id = "web_abc123"
    bot._user_store.add_user(chat_id=web_chat_id, username="tester", storage_backend="postgres")
    state = bot._user_store.create_oauth_session(web_chat_id)

    update, context = _make_update_context("999888777", [f"link_{state}"])
    monkeypatch.setattr(bot, "_is_authorized", lambda u: False)

    asyncio.run(bot.cmd_start(update, context))

    assert bot._user_store.get_user("999888777") is not None
    assert bot._user_store.get_user(web_chat_id) is None
    update.message.reply_text.assert_awaited_once()
    assert "collegato" in update.message.reply_text.call_args.args[0].lower()


def test_cmd_start_link_payload_expired_token(monkeypatch):
    import bot

    update, context = _make_update_context("111222333", ["link_not-a-real-token"])
    monkeypatch.setattr(bot, "_is_authorized", lambda u: False)

    asyncio.run(bot.cmd_start(update, context))

    update.message.reply_text.assert_awaited_once()
    assert "scaduto" in update.message.reply_text.call_args.args[0].lower()


def test_cmd_start_link_payload_duplicate_delivery_is_idempotent(monkeypatch):
    """Il client Telegram invia talvolta lo stesso /start due volte aprendo un deep
    link: la seconda invocazione non deve mostrare "link scaduto" se la prima ha
    gia' collegato con successo lo stesso chat_id."""
    import bot

    web_chat_id = "web_dup789"
    telegram_chat_id = "777888999"
    bot._user_store.add_user(chat_id=web_chat_id, username="tester3", storage_backend="postgres")
    state = bot._user_store.create_oauth_session(web_chat_id)

    monkeypatch.setattr(bot, "_is_authorized", lambda u: False)

    update1, context1 = _make_update_context(telegram_chat_id, [f"link_{state}"])
    asyncio.run(bot.cmd_start(update1, context1))
    assert "collegato" in update1.message.reply_text.call_args.args[0].lower()

    update2, context2 = _make_update_context(telegram_chat_id, [f"link_{state}"])
    asyncio.run(bot.cmd_start(update2, context2))

    update2.message.reply_text.assert_awaited_once()
    reply2 = update2.message.reply_text.call_args.args[0].lower()
    assert "già collegato" in reply2
    assert "scaduto" not in reply2


def test_cmd_start_link_payload_conflict_keeps_both_accounts(monkeypatch):
    import bot

    web_chat_id = "web_def456"
    telegram_chat_id = "444555666"
    bot._user_store.add_user(chat_id=web_chat_id, username="tester2", storage_backend="postgres")
    bot._user_store.set_credentials(web_chat_id, "conflict@example.com", "Password123")
    bot._user_store.add_user(chat_id=telegram_chat_id, username="already-there", storage_backend="postgres")
    bot._user_store.set_credentials(telegram_chat_id, "other@example.com", "Password123")
    state = bot._user_store.create_oauth_session(web_chat_id)

    update, context = _make_update_context(telegram_chat_id, [f"link_{state}"])
    monkeypatch.setattr(bot, "_is_authorized", lambda u: False)

    asyncio.run(bot.cmd_start(update, context))

    assert bot._user_store.get_user(web_chat_id) is not None
    assert bot._user_store.get_user(telegram_chat_id) is not None
    update.message.reply_text.assert_awaited_once()
    assert "già associato" in update.message.reply_text.call_args.args[0]
