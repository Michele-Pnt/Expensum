import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.integration


def test_nightly_category_sync_builds_notion_client_with_income_database_for_outbox_retry():
    """The scheduled outbox retry needs the Income database, not only Categories."""
    import bot

    user = SimpleNamespace(
        chat_id="7001",
        notion_access_token="token",
        categories_db_id="categories-db",
        income_db_id="income-db",
    )
    with (
        patch.object(
            bot._user_store, "get_active_notion_users", return_value=[user],
        ),
        patch.object(
            bot._user_store, "get_active_postgres_users", return_value=[],
        ),
        patch.object(bot, "NotionFinanceClient") as client_cls,
        patch.object(bot, "NotionStorage") as storage_cls,
        patch.object(
            bot, "refresh_category_averages", return_value=None,
        ),
        patch.object(bot.time, "sleep"),
    ):
        bot._nightly_category_sync(MagicMock(), MagicMock())

    client_cls.assert_called_once_with(
        api_key="token", categories_db_id="categories-db", income_db_id="income-db",
    )
    storage_cls.return_value.retry_pending_income_category_syncs.assert_called_once_with()


def _make_query_update_context(
    chat_id: str,
    callback_data: str,
    *,
    pending_expense=None,
    pending_expenses=None,
    category_options=None,
    category_options_by_tx=None,
):
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
    if pending_expenses is not None:
        user_data["pending_expenses"] = pending_expenses
    if category_options_by_tx is not None:
        user_data["category_options_by_tx"] = category_options_by_tx
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


def test_build_confirm_keyboard_income_has_edit_category_button():
    import bot

    data = {
        "type": "income", "date": "2026-07-13", "amount": 100.0,
        "income_type": "stipendio", "name": "Bonus",
    }
    keyboard = bot._build_confirm_keyboard(data)
    callback_data = [btn.callback_data for row in keyboard.inline_keyboard for btn in row]
    assert "edit_category" in callback_data
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
    fake_storage.get_categories.return_value = [
        {"id": 1, "name": "Ristorante"}, {"id": 2, "name": "Aperitivo"},
        {"id": 3, "name": "Spesa"},
    ]
    monkeypatch.setattr(bot, "_get_storage", lambda chat_id: fake_storage)

    asyncio.run(bot.handle_callback(update, context))

    query.edit_message_text.assert_awaited_once()
    _, kwargs = query.edit_message_text.call_args
    keyboard = kwargs["reply_markup"]
    labels = [btn.text for row in keyboard.inline_keyboard for btn in row]
    assert "Aperitivo" in labels
    assert context.user_data["category_options_by_tx"]["single"] == [
        {"id": 1, "name": "Ristorante"}, {"id": 2, "name": "Aperitivo"},
        {"id": 3, "name": "Spesa"},
    ]


def test_handle_callback_setcat_updates_pending_category(monkeypatch):
    import bot

    pending = {
        "type": "expense", "date": "2026-07-13", "amount": 5.0,
        "category": "Ristorante", "name": "Coca",
    }
    query, update, context = _make_query_update_context(
        "111", "setcat:1", pending_expense=pending,
        category_options_by_tx={"single": [
            {"id": 1, "name": "Ristorante"}, {"id": 2, "name": "Aperitivo"},
            {"id": 3, "name": "Spesa"},
        ]},
    )
    monkeypatch.setattr(bot, "_is_authorized", lambda u: True)

    asyncio.run(bot.handle_callback(update, context))

    assert context.user_data["pending_expense"]["category"] == "Aperitivo"
    assert context.user_data["pending_expense"]["category_was_corrected"] is True
    query.edit_message_text.assert_awaited_once()
    text = query.edit_message_text.call_args.args[0]
    assert "Aperitivo" in text


def test_setcat_then_confirm_records_category_corrected_reason(monkeypatch):
    """Il KPI 'category corrected' (src/dashboard/admin_metrics.py) dipende dal
    fatto che il flag settato da setcat/msetcat arrivi intatto a record_tx_event
    quando la transazione viene confermata — copre bot.py::_save_to_notion."""
    import bot

    pending = {
        "type": "expense", "date": "2026-07-13", "amount": 5.0,
        "category": "Ristorante", "name": "Coca",
    }
    query, update, context = _make_query_update_context(
        "111", "setcat:1", pending_expense=pending,
        category_options_by_tx={"single": [
            {"id": 1, "name": "Ristorante"}, {"id": 2, "name": "Aperitivo"},
        ]},
    )
    monkeypatch.setattr(bot, "_is_authorized", lambda u: True)
    asyncio.run(bot.handle_callback(update, context))

    corrected_data = context.user_data["pending_expense"]
    storage = MagicMock()
    monkeypatch.setattr(bot, "_get_storage", lambda chat_id: storage)
    monkeypatch.setattr(bot._user_store, "get_user", lambda chat_id: None)
    monkeypatch.setattr(bot._user_store, "log_message", lambda *a, **k: None)
    monkeypatch.setattr(bot, "_track_event", lambda *a, **k: None)
    monkeypatch.setattr(bot, "get_category_spent_and_budget", lambda *a, **k: None)
    record_mock = MagicMock(return_value=None)
    monkeypatch.setattr(bot._user_store, "record_tx_event", record_mock)

    confirm_context = MagicMock()
    confirm_context.user_data = {"input_method": "text"}
    query2 = MagicMock()
    query2.edit_message_text = AsyncMock()

    asyncio.run(bot._save_to_notion(query2, confirm_context, "111", corrected_data, account_id="acc-1"))

    record_mock.assert_called_once_with(
        "111", "expense", "text", "confirmed", "telegram", reason="category_corrected",
    )


def test_confirm_without_category_edit_records_no_reason(monkeypatch):
    """Controprova: se l'utente conferma senza mai toccare la categoria proposta
    dall'AI, `record_tx_event` deve ricevere reason=None come prima di questa
    feature — nessuna regressione sul comportamento di default."""
    import bot

    data = {
        "type": "expense", "date": "2026-07-13", "amount": 5.0,
        "category": "Ristorante", "name": "Coca",
    }
    storage = MagicMock()
    monkeypatch.setattr(bot, "_get_storage", lambda chat_id: storage)
    monkeypatch.setattr(bot._user_store, "get_user", lambda chat_id: None)
    monkeypatch.setattr(bot._user_store, "log_message", lambda *a, **k: None)
    monkeypatch.setattr(bot, "_track_event", lambda *a, **k: None)
    monkeypatch.setattr(bot, "get_category_spent_and_budget", lambda *a, **k: None)
    record_mock = MagicMock(return_value=None)
    monkeypatch.setattr(bot._user_store, "record_tx_event", record_mock)

    context = MagicMock()
    context.user_data = {"input_method": "text"}
    query = MagicMock()
    query.edit_message_text = AsyncMock()

    asyncio.run(bot._save_to_notion(query, context, "111", data, account_id="acc-1"))

    record_mock.assert_called_once_with(
        "111", "expense", "text", "confirmed", "telegram", reason=None,
    )


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
    fake_storage.get_categories.return_value = []
    monkeypatch.setattr(bot, "_get_storage", lambda chat_id: fake_storage)

    asyncio.run(bot.handle_callback(update, context))

    query.edit_message_text.assert_awaited_once()
    text = query.edit_message_text.call_args.args[0]
    assert "/modify" in text


def test_handle_callback_income_category_uses_tenant_income_categories(monkeypatch):
    import bot
    pending = {"type": "income", "date": "2026-07-13", "amount": 100.0,
               "income_category": "Stipendio", "income_type": "Stipendio", "name": "Cliente"}
    query, update, context = _make_query_update_context("111", "edit_category", pending_expense=pending)
    monkeypatch.setattr(bot, "_is_authorized", lambda u: True)
    fake_storage = MagicMock()
    fake_storage.get_income_categories.return_value = [
        {"id": 1, "name": "Stipendio"}, {"id": 2, "name": "Consulenza"},
    ]
    monkeypatch.setattr(bot, "_get_storage", lambda chat_id: fake_storage)
    asyncio.run(bot.handle_callback(update, context))
    fake_storage.get_income_categories.assert_called_once_with()
    assert context.user_data["category_options_by_tx"]["single"] == [
        {"id": 1, "name": "Stipendio"}, {"id": 2, "name": "Consulenza"},
    ]


def test_multi_picker_options_are_isolated_by_transaction_and_keep_income_id(monkeypatch):
    """An expense picker opened later cannot overwrite an income transaction's choices."""
    import bot

    pending_expenses = {
        "income-1": {"type": "income", "date": "2026-07-13", "amount": 100.0,
                     "income_category": "Stipendio", "income_type": "Stipendio", "name": "Cliente"},
        "expense-2": {"type": "expense", "date": "2026-07-13", "amount": 5.0,
                      "category": "Cibo", "name": "Pranzo"},
    }
    monkeypatch.setattr(bot, "_is_authorized", lambda u: True)
    storage = MagicMock()
    storage.get_income_categories.return_value = [{"id": 41, "name": "Consulenza"}]
    storage.get_categories.return_value = [{"id": 5, "name": "Cibo"}]
    monkeypatch.setattr(bot, "_get_storage", lambda chat_id: storage)

    _, update_income, context = _make_query_update_context(
        "111", "medit_category:income-1", pending_expenses=pending_expenses,
    )
    asyncio.run(bot.handle_callback(update_income, context))
    _, update_expense, _ = _make_query_update_context("111", "medit_category:expense-2")
    update_expense.callback_query = MagicMock(data="medit_category:expense-2", answer=AsyncMock(), edit_message_text=AsyncMock())
    update_expense.effective_chat.id = 111
    asyncio.run(bot.handle_callback(update_expense, context))

    assert context.user_data["category_options_by_tx"] == {
        "income-1": [{"id": 41, "name": "Consulenza"}],
        "expense-2": [{"id": 5, "name": "Cibo"}],
    }
    query, update, _ = _make_query_update_context("111", "msetcat:income-1:0")
    update.callback_query = query
    update.effective_chat.id = 111
    asyncio.run(bot.handle_callback(update, context))

    selected = context.user_data["pending_expenses"]["income-1"]
    assert selected["income_category_id"] == 41
    assert selected["income_category"] == "Consulenza"
    assert selected["income_type"] == "Consulenza"


def test_income_save_passes_picker_id_and_surfaces_storage_tenant_rejection(monkeypatch):
    """The bot never turns a foreign picker ID into a name-only storage write."""
    import bot

    storage = MagicMock()
    storage.create_income.side_effect = ValueError("Income category not found")
    monkeypatch.setattr(bot, "_get_storage", lambda chat_id: storage)
    query = MagicMock()
    query.edit_message_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}
    data = {
        "type": "income", "date": "2026-07-13", "amount": 100.0,
        "income_category_id": 999, "income_category": "Non mia",
        "income_type": "Non mia", "name": "Cliente",
    }

    asyncio.run(bot._save_to_notion(query, context, "111", data, account_id="account-1"))

    assert storage.create_income.call_args.kwargs["income_category_id"] == 999
    assert storage.create_income.call_args.kwargs["income_category_name"] == "Non mia"
    assert "Non sono riuscito" in query.edit_message_text.call_args.args[0]
