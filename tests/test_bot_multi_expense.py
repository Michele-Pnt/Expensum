import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.integration


def _make_query_update_context(chat_id: str, callback_data: str, *, pending_expenses=None, category_options=None):
    query = MagicMock()
    query.data = callback_data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()

    update = MagicMock()
    update.callback_query = query
    update.effective_chat.id = int(chat_id)

    context = MagicMock()
    user_data = {}
    if pending_expenses is not None:
        user_data["pending_expenses"] = pending_expenses
    if category_options is not None:
        user_data["category_options"] = category_options
    context.user_data = user_data

    return query, update, context


def _accounts():
    return [{"id": 1, "name": "Conto Corrente", "current_balance": 500.0}]


def test_process_expense_text_sends_all_confirmations_immediately(monkeypatch):
    """Un messaggio multi-spesa manda SUBITO tutti i messaggi di conferma, uno per transazione,
    ognuno con bottoni indipendenti (id dedicato) — non uno alla volta in sequenza."""
    import bot

    transactions = [
        {"type": "expense", "date": date(2026, 4, 9), "amount": 10.0, "category": "Ristoranti", "income_type": None, "name": "Pranzo"},
        {"type": "expense", "date": date(2026, 4, 9), "amount": 20.0, "category": "Trasporti", "income_type": None, "name": "Benzina"},
        {"type": "expense", "date": date(2026, 4, 9), "amount": 5.0, "category": "Bar", "income_type": None, "name": "Caffe"},
    ]

    fake_parser = MagicMock()
    fake_parser.parse_multi_with_usage.return_value = (transactions, {"provider": "mistral"})
    monkeypatch.setattr(bot, "_get_parser", lambda chat_id: fake_parser)
    monkeypatch.setattr(bot._user_store, "reserve_llm_tokens", lambda **k: None)
    monkeypatch.setattr(bot._user_store, "finalize_llm_usage", lambda **k: None)
    monkeypatch.setattr(bot._user_store, "log_message", lambda *a, **k: None)
    monkeypatch.setattr(bot.analytics, "track", lambda *a, **k: None)

    # Categorizzazione adattiva (src/category_matcher.py): pass-through, la categoria
    # proposta dall'LLM resta invariata — qui si testa solo il flusso multi-spesa.
    monkeypatch.setattr(bot, "_get_storage", lambda chat_id: MagicMock())
    monkeypatch.setattr(bot._user_store, "get_user_category_names", lambda chat_id: [])
    monkeypatch.setattr(bot._user_store, "Session", lambda: MagicMock())
    # _get_message_when (chiamata indipendente dal parsing) usa get_user_preferences
    # via _user_store.Session() — con Session mockato genericamente sopra andrebbe in
    # crash su json.loads(MagicMock); qui la aggiriamo direttamente.
    monkeypatch.setattr(bot._user_store, "get_user_preferences", lambda chat_id: {})
    monkeypatch.setattr(
        bot.category_matcher,
        "evaluate_and_track",
        lambda session, storage, user_store, chat_id, name, category, known: MagicMock(
            category_name=category, awaiting_confirmation=False,
        ),
    )

    context = MagicMock()
    context.user_data = {}

    update = MagicMock()
    update.effective_message.message_id = 1
    update.message.reply_text = AsyncMock()

    asyncio.run(bot._process_expense_text(update, context, "10 pranzo, 20 benzina, 5 caffe ieri", "111"))

    # Tutte e 3 le conferme inviate come messaggi separati, nella stessa chiamata (nessuna coda sequenziale).
    assert update.message.reply_text.await_count == 3
    assert "expense_queue" not in context.user_data

    pending_expenses = context.user_data["pending_expenses"]
    assert len(pending_expenses) == 3
    amounts = sorted(tx["amount"] for tx in pending_expenses.values())
    assert amounts == [5.0, 10.0, 20.0]

    # Ogni messaggio ha bottoni taggati con un id univoco (mconfirm:<id>/mcancel:<id>).
    tags = set()
    for call in update.message.reply_text.await_args_list:
        keyboard = call.kwargs["reply_markup"]
        for row in keyboard.inline_keyboard:
            for btn in row:
                assert btn.callback_data.startswith(("mconfirm:", "mcancel:", "medit_category:"))
                tags.add(btn.callback_data.split(":", 1)[1])
    assert len(tags) == 3


def test_awaiting_confirmation_sends_extra_promotion_message(monkeypatch):
    """Se evaluate_and_track segnala awaiting_confirmation, viene inviato un messaggio
    extra separato (Sì/No) oltre alle conferme spesa — non incorporato nella card."""
    import bot

    transactions = [
        {"type": "expense", "date": date(2026, 4, 9), "amount": 10.0, "category": "Ristoranti", "income_type": None, "name": "Pranzo"},
    ]

    fake_parser = MagicMock()
    fake_parser.parse_multi_with_usage.return_value = (transactions, {"provider": "mistral"})
    monkeypatch.setattr(bot, "_get_parser", lambda chat_id: fake_parser)
    monkeypatch.setattr(bot._user_store, "reserve_llm_tokens", lambda **k: None)
    monkeypatch.setattr(bot._user_store, "finalize_llm_usage", lambda **k: None)
    monkeypatch.setattr(bot._user_store, "log_message", lambda *a, **k: None)
    monkeypatch.setattr(bot.analytics, "track", lambda *a, **k: None)
    monkeypatch.setattr(bot, "_get_storage", lambda chat_id: MagicMock())
    monkeypatch.setattr(bot._user_store, "get_user_category_names", lambda chat_id: [])
    monkeypatch.setattr(bot._user_store, "Session", lambda: MagicMock())
    # _get_message_when (chiamata indipendente dal parsing) usa get_user_preferences
    # via _user_store.Session() — con Session mockato genericamente sopra andrebbe in
    # crash su json.loads(MagicMock); qui la aggiriamo direttamente.
    monkeypatch.setattr(bot._user_store, "get_user_preferences", lambda chat_id: {})
    monkeypatch.setattr(
        bot.category_matcher,
        "evaluate_and_track",
        lambda session, storage, user_store, chat_id, name, category, known: MagicMock(
            category_name="Altro", awaiting_confirmation=True, candidate_id=42, suggested_name="Pranzo",
        ),
    )

    context = MagicMock()
    context.user_data = {}
    update = MagicMock()
    update.effective_message.message_id = 1
    update.message.reply_text = AsyncMock()

    asyncio.run(bot._process_expense_text(update, context, "10 pranzo", "111"))

    # 1 conferma spesa + 1 messaggio di conferma categoria = 2 chiamate distinte.
    assert update.message.reply_text.await_count == 2
    last_call = update.message.reply_text.await_args_list[-1]
    assert "Pranzo" in last_call.args[0]
    keyboard = last_call.kwargs["reply_markup"]
    callback_data = [btn.callback_data for row in keyboard.inline_keyboard for btn in row]
    assert callback_data == ["catpromote_yes:42", "catpromote_no:42"]


def test_parse_failure_enriches_reason_with_last_error_status_code(monkeypatch):
    """Quando il parser fallisce del tutto, `reason` deve incorporare lo status
    code dell'ultimo errore Mistral (src/expense_parser.py::last_error_status_code)
    per distinguere rate-limit/5xx da altri fallimenti nella dashboard admin."""
    import bot

    fake_parser = MagicMock()
    fake_parser.parse_multi_with_usage.return_value = ([], {})
    fake_parser.last_error_status_code = 503
    monkeypatch.setattr(bot, "_get_parser", lambda chat_id: fake_parser)
    monkeypatch.setattr(bot._user_store, "reserve_llm_tokens", lambda **k: None)
    monkeypatch.setattr(bot._user_store, "increment_ai_metrics", lambda **k: None)
    monkeypatch.setattr(bot.analytics, "track", lambda *a, **k: None)
    monkeypatch.setattr(bot._user_store, "Session", lambda: MagicMock())
    monkeypatch.setattr(bot._user_store, "get_user_preferences", lambda chat_id: {})
    record_mock = MagicMock()
    monkeypatch.setattr(bot._user_store, "record_tx_event", record_mock)

    context = MagicMock()
    context.user_data = {}
    update = MagicMock()
    update.effective_message.message_id = 1
    update.message.reply_text = AsyncMock()

    asyncio.run(bot._process_expense_text(update, context, "boh", "111"))

    record_mock.assert_called_once_with(
        "111", "unknown", "text", "failed", "telegram", reason="ai_unavailable_503",
    )


def test_parse_failure_without_status_code_falls_back_to_plain_reason(monkeypatch):
    """Controprova: se il parser non ha catturato uno status code (es. errore di
    rete generico), il reason resta il vecchio 'ai_unavailable' — nessuna
    regressione per i chiamanti/dashboard che già lo filtrano così."""
    import bot

    fake_parser = MagicMock()
    fake_parser.parse_multi_with_usage.return_value = ([], {})
    fake_parser.last_error_status_code = None
    monkeypatch.setattr(bot, "_get_parser", lambda chat_id: fake_parser)
    monkeypatch.setattr(bot._user_store, "reserve_llm_tokens", lambda **k: None)
    monkeypatch.setattr(bot._user_store, "increment_ai_metrics", lambda **k: None)
    monkeypatch.setattr(bot.analytics, "track", lambda *a, **k: None)
    monkeypatch.setattr(bot._user_store, "Session", lambda: MagicMock())
    monkeypatch.setattr(bot._user_store, "get_user_preferences", lambda chat_id: {})
    record_mock = MagicMock()
    monkeypatch.setattr(bot._user_store, "record_tx_event", record_mock)

    context = MagicMock()
    context.user_data = {}
    update = MagicMock()
    update.effective_message.message_id = 1
    update.message.reply_text = AsyncMock()

    asyncio.run(bot._process_expense_text(update, context, "boh", "111"))

    record_mock.assert_called_once_with(
        "111", "unknown", "text", "failed", "telegram", reason="ai_unavailable",
    )


def test_catpromote_yes_calls_confirm_promotion(monkeypatch):
    """Il bottone Sì richiama category_matcher.confirm_promotion col candidate_id giusto."""
    import bot

    monkeypatch.setattr(bot, "_is_authorized", lambda u: True)
    monkeypatch.setattr(bot, "_get_storage", lambda chat_id: MagicMock())
    monkeypatch.setattr(bot._user_store, "Session", lambda: MagicMock())
    # _get_message_when (chiamata indipendente dal parsing) usa get_user_preferences
    # via _user_store.Session() — con Session mockato genericamente sopra andrebbe in
    # crash su json.loads(MagicMock); qui la aggiriamo direttamente.
    monkeypatch.setattr(bot._user_store, "get_user_preferences", lambda chat_id: {})

    confirm_calls = []
    monkeypatch.setattr(
        bot.category_matcher,
        "confirm_promotion",
        lambda session, storage, user_store, candidate_id: confirm_calls.append(candidate_id) or MagicMock(
            promoted=True, promoted_category_name="Netflix",
        ),
    )

    query, update, context = _make_query_update_context("111", "catpromote_yes:42")
    asyncio.run(bot.handle_callback(update, context))

    assert confirm_calls == [42]
    query.edit_message_text.assert_awaited_once()
    assert "Netflix" in query.edit_message_text.await_args.args[0]


def test_catpromote_no_calls_decline_promotion(monkeypatch):
    """Il bottone No richiama category_matcher.decline_promotion col candidate_id giusto."""
    import bot

    monkeypatch.setattr(bot, "_is_authorized", lambda u: True)
    monkeypatch.setattr(bot._user_store, "Session", lambda: MagicMock())
    # _get_message_when (chiamata indipendente dal parsing) usa get_user_preferences
    # via _user_store.Session() — con Session mockato genericamente sopra andrebbe in
    # crash su json.loads(MagicMock); qui la aggiriamo direttamente.
    monkeypatch.setattr(bot._user_store, "get_user_preferences", lambda chat_id: {})

    decline_calls = []
    monkeypatch.setattr(
        bot.category_matcher,
        "decline_promotion",
        lambda session, candidate_id: decline_calls.append(candidate_id),
    )

    query, update, context = _make_query_update_context("111", "catpromote_no:42")
    asyncio.run(bot.handle_callback(update, context))

    assert decline_calls == [42]
    query.edit_message_text.assert_awaited_once()


def test_mcancel_only_cancels_its_own_transaction(monkeypatch):
    """Annullare una transazione con 'mcancel:<id>' non deve toccare le altre in sospeso."""
    import bot

    pending_expenses = {
        "1": {"type": "expense", "date": "2026-04-09", "amount": 10.0, "category": "Ristoranti", "name": "Pranzo"},
        "2": {"type": "expense", "date": "2026-04-09", "amount": 20.0, "category": "Trasporti", "name": "Benzina"},
    }
    query, update, context = _make_query_update_context("111", "mcancel:1", pending_expenses=pending_expenses)
    monkeypatch.setattr(bot, "_is_authorized", lambda u: True)
    monkeypatch.setattr(bot.analytics, "track", lambda *a, **k: None)

    asyncio.run(bot.handle_callback(update, context))

    assert "1" not in context.user_data["pending_expenses"]
    assert "2" in context.user_data["pending_expenses"]
    query.edit_message_text.assert_awaited_once()


def test_mconfirm_then_maccount_saves_only_that_transaction(monkeypatch):
    """Il ciclo mconfirm -> maccount salva solo la transazione taggata, lasciando intatte le altre."""
    import bot

    pending_expenses = {
        "1": {"type": "expense", "date": "2026-04-09", "amount": 10.0, "category": "Ristoranti", "name": "Pranzo"},
        "2": {"type": "expense", "date": "2026-04-09", "amount": 20.0, "category": "Trasporti", "name": "Benzina"},
    }

    fake_storage = MagicMock()
    fake_storage.fetch_accounts.return_value = _accounts()
    fake_storage.create_expense.return_value = {"id": 1}
    monkeypatch.setattr(bot, "_get_storage", lambda chat_id: fake_storage)
    monkeypatch.setattr(bot, "_is_authorized", lambda u: True)
    monkeypatch.setattr(bot._user_store, "get_user", lambda chat_id: None)
    monkeypatch.setattr(bot._user_store, "log_message", lambda *a, **k: None)
    monkeypatch.setattr(bot._user_store, "increment_ai_metrics", lambda *a, **k: None)
    monkeypatch.setattr(bot.analytics, "track", lambda *a, **k: None)

    query, update, context = _make_query_update_context("111", "mconfirm:1", pending_expenses=pending_expenses)
    asyncio.run(bot.handle_callback(update, context))

    query.edit_message_text.assert_awaited_once()
    keyboard = query.edit_message_text.call_args.kwargs["reply_markup"]
    account_buttons = [btn.callback_data for row in keyboard.inline_keyboard for btn in row if btn.callback_data.startswith("maccount:")]
    assert account_buttons == ["maccount:1:1"]

    # Simula la scelta del conto
    query2, update2, context2 = _make_query_update_context("111", "maccount:1:1", pending_expenses=context.user_data["pending_expenses"])
    asyncio.run(bot.handle_callback(update2, context2))

    fake_storage.create_expense.assert_called_once()
    kwargs = fake_storage.create_expense.call_args.kwargs
    assert kwargs["amount"] == 10.0
    assert kwargs["name"] == "Pranzo"
    assert "1" not in context2.user_data["pending_expenses"]
    assert "2" in context2.user_data["pending_expenses"]
    assert context2.user_data["pending_expenses"]["2"]["amount"] == 20.0
