import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.integration


def _make_query_update_context(chat_id: str, callback_data: str, *, pending_expense=None):
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
    context.user_data = user_data

    return query, update, context


def _accounts():
    return [
        {"id": 1, "name": "Conto Corrente", "current_balance": 500.0},
        {"id": 2, "name": "Risparmio", "current_balance": 200.0},
    ]


def test_build_expense_summary_transfer():
    import bot

    data = {
        "type": "transfer", "date": "2026-07-13", "amount": 100.0,
        "name": "Trasferimento", "from_account_name": "Conto Corrente", "to_account_name": "Risparmio",
    }
    summary = bot._build_expense_summary(data)
    assert "Conto Corrente" in summary
    assert "Risparmio" in summary
    assert "€100.00" in summary


def test_build_confirm_keyboard_transfer_has_no_edit_category_button():
    import bot

    data = {"type": "transfer", "date": "2026-07-13", "amount": 100.0, "name": "Trasferimento"}
    keyboard = bot._build_confirm_keyboard(data)
    callback_data = [btn.callback_data for row in keyboard.inline_keyboard for btn in row]
    assert "edit_category" not in callback_data
    assert "confirm" in callback_data
    assert "cancel" in callback_data


def test_resolve_account_hint_exact_match():
    import bot

    match = bot._resolve_account_hint("Risparmio", _accounts())
    assert match["id"] == 2


def test_resolve_account_hint_fuzzy_match():
    import bot

    match = bot._resolve_account_hint("risparmi", _accounts())
    assert match["id"] == 2


def test_resolve_account_hint_no_match():
    import bot

    assert bot._resolve_account_hint("Carta Prepagata", _accounts()) is None
    assert bot._resolve_account_hint(None, _accounts()) is None


def test_advance_transfer_flow_asks_from_account_when_nothing_resolved(monkeypatch):
    import bot

    fake_storage = MagicMock()
    fake_storage.fetch_accounts.return_value = _accounts()
    monkeypatch.setattr(bot, "_get_storage", lambda chat_id: fake_storage)

    context = MagicMock()
    context.user_data = {
        "pending_expense": {
            "type": "transfer", "date": "2026-07-13", "amount": None, "name": "Trasferimento",
            "from_account_id": None, "to_account_id": None,
        }
    }

    sent = {}

    async def _send(text, reply_markup=None):
        sent["text"] = text
        sent["reply_markup"] = reply_markup

    asyncio.run(bot._advance_transfer_flow(context, "111", _send))

    assert "Da quale conto" in sent["text"]
    callback_data = [btn.callback_data for row in sent["reply_markup"].inline_keyboard for btn in row]
    assert "transfer_from:1" in callback_data
    assert "transfer_from:2" in callback_data


def test_advance_transfer_flow_resolves_nlp_hints_and_asks_amount(monkeypatch):
    import bot

    fake_storage = MagicMock()
    fake_storage.fetch_accounts.return_value = _accounts()
    monkeypatch.setattr(bot, "_get_storage", lambda chat_id: fake_storage)

    context = MagicMock()
    pending = {
        "type": "transfer", "date": "2026-07-13", "amount": None, "name": "Trasferimento",
        "from_account_id": None, "to_account_id": None,
        "from_account_hint": "Conto Corrente", "to_account_hint": "Risparmio",
    }
    context.user_data = {"pending_expense": pending}

    sent = {}

    async def _send(text, reply_markup=None):
        sent["text"] = text

    asyncio.run(bot._advance_transfer_flow(context, "111", _send))

    assert pending["from_account_id"] == 1
    assert pending["to_account_id"] == 2
    assert context.user_data["waiting_for_amount"] is True
    assert "importo" in sent["text"].lower()


def test_advance_transfer_flow_shows_confirm_when_ready(monkeypatch):
    import bot

    context = MagicMock()
    pending = {
        "type": "transfer", "date": "2026-07-13", "amount": 100.0, "name": "Trasferimento",
        "from_account_id": 1, "to_account_id": 2,
        "from_account_name": "Conto Corrente", "to_account_name": "Risparmio",
    }
    context.user_data = {"pending_expense": pending}

    sent = {}

    async def _send(text, reply_markup=None):
        sent["text"] = text
        sent["reply_markup"] = reply_markup

    asyncio.run(bot._advance_transfer_flow(context, "111", _send))

    assert "Trasferimento" in sent["text"]
    callback_data = [btn.callback_data for row in sent["reply_markup"].inline_keyboard for btn in row]
    assert "confirm" in callback_data


def test_handle_callback_transfer_from_then_to(monkeypatch):
    import bot

    fake_storage = MagicMock()
    fake_storage.fetch_accounts.return_value = _accounts()
    monkeypatch.setattr(bot, "_get_storage", lambda chat_id: fake_storage)
    monkeypatch.setattr(bot, "_is_authorized", lambda u: True)

    pending = {
        "type": "transfer", "date": "2026-07-13", "amount": None, "name": "Trasferimento",
        "from_account_id": None, "to_account_id": None,
    }
    query, update, context = _make_query_update_context("111", "transfer_from:1", pending_expense=pending)

    asyncio.run(bot.handle_callback(update, context))

    assert pending["from_account_id"] == "1"
    assert pending["from_account_name"] == "Conto Corrente"
    query.edit_message_text.assert_awaited_once()
    _, kwargs = query.edit_message_text.call_args
    callback_data = [btn.callback_data for row in kwargs["reply_markup"].inline_keyboard for btn in row]
    assert "transfer_to:2" in callback_data
    assert "transfer_to:1" not in callback_data


def test_handle_callback_transfer_to_rejects_same_account(monkeypatch):
    import bot

    monkeypatch.setattr(bot, "_is_authorized", lambda u: True)
    pending = {
        "type": "transfer", "date": "2026-07-13", "amount": None, "name": "Trasferimento",
        "from_account_id": "1", "to_account_id": None,
    }
    query, update, context = _make_query_update_context("111", "transfer_to:1", pending_expense=pending)

    asyncio.run(bot.handle_callback(update, context))

    query.edit_message_text.assert_awaited_once()
    text = query.edit_message_text.call_args.args[0]
    assert "diverso" in text.lower()
    assert pending["to_account_id"] is None


def test_handle_callback_confirm_transfer_saves_and_skips_account_picker(monkeypatch):
    import bot

    fake_storage = MagicMock()
    fake_storage.create_transfer.return_value = {"id": 1}
    fake_storage.fetch_accounts.return_value = _accounts()
    monkeypatch.setattr(bot, "_get_storage", lambda chat_id: fake_storage)
    monkeypatch.setattr(bot, "_is_authorized", lambda u: True)
    monkeypatch.setattr(bot._user_store, "get_user", lambda chat_id: None)
    monkeypatch.setattr(bot._user_store, "log_message", lambda *a, **k: None)
    monkeypatch.setattr(bot.analytics, "track", lambda *a, **k: None)

    async def _fake_refresh(*a, **k):
        return None
    monkeypatch.setattr(bot, "_refresh_pinned_dashboard", _fake_refresh)

    pending = {
        "type": "transfer", "date": "2026-07-13", "amount": 100.0, "name": "Trasferimento",
        "from_account_id": 1, "to_account_id": 2,
        "from_account_name": "Conto Corrente", "to_account_name": "Risparmio",
    }
    query, update, context = _make_query_update_context("111", "confirm", pending_expense=pending)

    asyncio.run(bot.handle_callback(update, context))

    fake_storage.create_transfer.assert_called_once()
    kwargs = fake_storage.create_transfer.call_args.kwargs
    assert kwargs["from_account_id"] == 1
    assert kwargs["to_account_id"] == 2
    assert kwargs["amount"] == 100.0
    query.edit_message_text.assert_awaited_once()
    text = query.edit_message_text.call_args.args[0]
    assert "Trasferimento salvato" in text
    assert "pending_expense" not in context.user_data
