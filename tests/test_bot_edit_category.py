import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.integration


def _make_query_update_context(chat_id: str, callback_data: str, *, pending_expense=None, category_options=None):
    query = MagicMock()
    query.data = callback_data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()

    update = MagicMock()
    update.callback_query = query
    update.effective_chat.id = int(chat_id)

    context = MagicMock()
    user_data = {}
    if pending_expense is not None:
        user_data["pending_expense"] = pending_expense
    if category_options is not None:
        user_data["category_options"] = category_options
    context.user_data = user_data

    return query, update, context


def test_build_expense_summary_and_keyboard_expense():
    import bot

    data = {
        "type": "expense", "date": "2026-07-13", "amount": 5.0,
        "category": "Ristorante", "name": "Coca",
    }
    summary = bot._build_expense_summary(data)
    assert "Ristorante" in summary
    assert "€5.00" in summary

    keyboard = bot._build_confirm_keyboard(data)
    callback_data = [btn.callback_data for row in keyboard.inline_keyboard for btn in row]
    assert "edit_category" in callback_data
    assert "confirm" in callback_data
    assert "cancel" in callback_data


def test_build_confirm_keyboard_income_has_no_edit_category_button():
    import bot

    data = {
        "type": "income", "date": "2026-07-13", "amount": 100.0,
        "income_type": "stipendio", "name": "Bonus",
    }
    keyboard = bot._build_confirm_keyboard(data)
    callback_data = [btn.callback_data for row in keyboard.inline_keyboard for btn in row]
    assert "edit_category" not in callback_data
    assert "confirm" in callback_data
    assert "cancel" in callback_data


def test_handle_callback_edit_category_shows_category_buttons(monkeypatch):
    import bot

    pending = {
        "type": "expense", "date": "2026-07-13", "amount": 5.0,
        "category": "Ristorante", "name": "Coca",
    }
    query, update, context = _make_query_update_context(
        "111", "edit_category", pending_expense=pending,
    )
    monkeypatch.setattr(bot, "_is_authorized", lambda u: True)

    fake_storage = MagicMock()
    fake_storage.get_category_names.return_value = ["Ristorante", "Aperitivo", "Spesa"]
    monkeypatch.setattr(bot, "_get_storage", lambda chat_id: fake_storage)

    asyncio.run(bot.handle_callback(update, context))

    query.edit_message_text.assert_awaited_once()
    _, kwargs = query.edit_message_text.call_args
    keyboard = kwargs["reply_markup"]
    labels = [btn.text for row in keyboard.inline_keyboard for btn in row]
    assert "Aperitivo" in labels
    assert context.user_data["category_options"] == ["Ristorante", "Aperitivo", "Spesa"]


def test_handle_callback_setcat_updates_pending_category(monkeypatch):
    import bot

    pending = {
        "type": "expense", "date": "2026-07-13", "amount": 5.0,
        "category": "Ristorante", "name": "Coca",
    }
    query, update, context = _make_query_update_context(
        "111", "setcat:1", pending_expense=pending,
        category_options=["Ristorante", "Aperitivo", "Spesa"],
    )
    monkeypatch.setattr(bot, "_is_authorized", lambda u: True)

    asyncio.run(bot.handle_callback(update, context))

    assert context.user_data["pending_expense"]["category"] == "Aperitivo"
    query.edit_message_text.assert_awaited_once()
    text = query.edit_message_text.call_args.args[0]
    assert "Aperitivo" in text


def test_handle_callback_edit_category_no_categories(monkeypatch):
    import bot

    pending = {
        "type": "expense", "date": "2026-07-13", "amount": 5.0,
        "category": None, "name": "Coca",
    }
    query, update, context = _make_query_update_context(
        "111", "edit_category", pending_expense=pending,
    )
    monkeypatch.setattr(bot, "_is_authorized", lambda u: True)

    fake_storage = MagicMock()
    fake_storage.get_category_names.return_value = []
    monkeypatch.setattr(bot, "_get_storage", lambda chat_id: fake_storage)

    asyncio.run(bot.handle_callback(update, context))

    query.edit_message_text.assert_awaited_once()
    text = query.edit_message_text.call_args.args[0]
    assert "/modify" in text
