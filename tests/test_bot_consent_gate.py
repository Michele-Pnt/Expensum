"""Test per `_consent_gate` (bot.py) — gate cross-cutting lato Telegram.

Handler registrato in `group=-1` (prima di ogni altro handler) che blocca l'uso del
bot per utenti registrati con consenso privacy/ToS non aggiornato, applicando lo
stesso criterio del gate bloccante già attivo lato webapp
(`_resolve_authenticated_redirect` in `src/dashboard/blueprints/auth_routes.py`).
"""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

pytestmark = pytest.mark.integration


def _make_message_update(chat_id: str, text: str | None):
    """Update con `update.message` valorizzato (comando testuale o testo libero)."""
    update = MagicMock()
    update.effective_chat.id = int(chat_id)
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.callback_query = None
    context = MagicMock()
    context.bot.send_message = AsyncMock()
    return update, context


def _make_callback_query_update(chat_id: str):
    """Update con `update.callback_query` valorizzato (nessun `update.message`)."""
    update = MagicMock()
    update.effective_chat.id = int(chat_id)
    update.message = None
    update.callback_query.answer = AsyncMock()
    context = MagicMock()
    context.bot.send_message = AsyncMock()
    return update, context


def test_consent_gate_unknown_user_is_noop(monkeypatch):
    """Utente non registrato: nessuna azione, nessun ApplicationHandlerStop (gestito altrove)."""
    import bot

    update, context = _make_message_update("100000001", "/status")

    asyncio.run(bot._consent_gate(update, context))

    update.message.reply_text.assert_not_called()
    context.bot.send_message.assert_not_called()


def test_consent_gate_up_to_date_consent_is_noop():
    """Utente con privacy/ToS già alla versione corrente: nessuna azione."""
    import bot
    from config import Config

    chat_id = "100000002"
    bot._user_store.add_user(chat_id=chat_id, username="consent-ok", storage_backend="postgres")
    bot._user_store.accept_privacy_policy(chat_id, Config.CURRENT_PRIVACY_POLICY_VERSION)
    bot._user_store.accept_terms_of_service(chat_id, Config.CURRENT_TOS_VERSION)

    update, context = _make_message_update(chat_id, "/status")

    asyncio.run(bot._consent_gate(update, context))

    update.message.reply_text.assert_not_called()
    context.bot.send_message.assert_not_called()


def test_consent_gate_blocks_disallowed_command_with_free_text():
    """Consenso non aggiornato + testo libero (non un comando): blocca e informa."""
    import bot
    from config import Config
    from telegram.ext import ApplicationHandlerStop

    chat_id = "100000003"
    bot._user_store.add_user(chat_id=chat_id, username="consent-stale", storage_backend="postgres")

    update, context = _make_message_update(chat_id, "spesa 20 euro pizza")

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(bot._consent_gate(update, context))

    update.message.reply_text.assert_awaited_once()
    assert Config.WEBAPP_BASE_URL in update.message.reply_text.call_args.args[0]


def test_consent_gate_blocks_disallowed_command_status():
    """Consenso non aggiornato + comando fuori allowlist (/status): blocca e informa."""
    import bot
    from config import Config
    from telegram.ext import ApplicationHandlerStop

    chat_id = "100000004"
    bot._user_store.add_user(chat_id=chat_id, username="consent-stale-status", storage_backend="postgres")

    update, context = _make_message_update(chat_id, "/status")

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(bot._consent_gate(update, context))

    update.message.reply_text.assert_awaited_once()
    assert Config.WEBAPP_BASE_URL in update.message.reply_text.call_args.args[0]


@pytest.mark.parametrize("command", ["/accedi", "/logout", "/export"])
def test_consent_gate_allows_allowlisted_commands(command):
    """Consenso non aggiornato ma comando in allowlist: nessuna azione, nessun blocco.

    `/export` è il comando di esportazione dati (diritto di accesso/portabilità Art.
    15/20 GDPR): deve restare raggiungibile anche a gate attivo, perché un diritto
    dell'interessato non può dipendere dall'aver accettato i nuovi ToS.
    """
    import bot

    chat_id = {"/accedi": "100000005", "/logout": "100000006", "/export": "100000009"}[command]
    bot._user_store.add_user(chat_id=chat_id, username="consent-allowlist", storage_backend="postgres")

    update, context = _make_message_update(chat_id, command)

    asyncio.run(bot._consent_gate(update, context))

    update.message.reply_text.assert_not_called()
    context.bot.send_message.assert_not_called()


def test_consent_gate_blocks_callback_query_with_stale_consent():
    """Consenso non aggiornato su un update con `callback_query`: usa `context.bot.send_message`."""
    import bot
    from config import Config
    from telegram.ext import ApplicationHandlerStop

    chat_id = "100000007"
    bot._user_store.add_user(chat_id=chat_id, username="consent-stale-cb", storage_backend="postgres")

    update, context = _make_callback_query_update(chat_id)

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(bot._consent_gate(update, context))

    update.callback_query.answer.assert_awaited_once()
    context.bot.send_message.assert_awaited_once()
    kwargs = context.bot.send_message.call_args.kwargs
    assert kwargs["chat_id"] == int(chat_id)
    assert Config.WEBAPP_BASE_URL in kwargs["text"]


def test_consent_gate_blocked_callback_logs_kind_callback(mocker):
    """Il blocco via `callback_query` logga `kind="callback"` esplicito, non dedotto.

    `_log_consent_gate_blocked` riceve il `kind` dal chiamante invece di dedurlo dal
    tipo di update: verifica che il ramo `callback_query` passi sempre `"callback"`.
    """
    import bot
    from telegram.ext import ApplicationHandlerStop

    chat_id = "100000021"
    bot._user_store.add_user(chat_id=chat_id, username="consent-stale-cb-log", storage_backend="postgres")
    update, context = _make_callback_query_update(chat_id)
    log_spy = mocker.patch.object(bot, "_log_consent_gate_blocked")

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(bot._consent_gate(update, context))

    log_spy.assert_called_once_with(chat_id, "callback")


def test_consent_gate_rate_limited_raises_stop_without_sending_message(monkeypatch):
    """Utente gateato ma rate-limited: `ApplicationHandlerStop` silenzioso, nessun messaggio.

    Il rate limiter va applicato PRIMA di costruire/inviare il messaggio di blocco:
    senza questo controllo il gate bypasserebbe la sliding window applicata altrove.
    """
    import bot
    from telegram.ext import ApplicationHandlerStop

    chat_id = "100000008"
    bot._user_store.add_user(chat_id=chat_id, username="consent-rate-limited", storage_backend="postgres")
    monkeypatch.setattr(bot, "is_rate_limited", lambda *args, **kwargs: True)

    update, context = _make_message_update(chat_id, "/status")

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(bot._consent_gate(update, context))

    update.message.reply_text.assert_not_called()
    context.bot.send_message.assert_not_called()


def test_consent_gate_blocking_message_includes_accept_button():
    """Il messaggio di blocco include il bottone inline con `CONSENT_GATE_ACCEPT_CB`."""
    import bot
    from telegram.ext import ApplicationHandlerStop

    chat_id = "100000009"
    bot._user_store.add_user(chat_id=chat_id, username="consent-needs-button", storage_backend="postgres")

    update, context = _make_message_update(chat_id, "/status")

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(bot._consent_gate(update, context))

    update.message.reply_text.assert_awaited_once()
    reply_markup = update.message.reply_text.call_args.kwargs.get("reply_markup")
    assert reply_markup is not None
    buttons = [btn for row in reply_markup.inline_keyboard for btn in row]
    assert any(btn.callback_data == bot.CONSENT_GATE_ACCEPT_CB for btn in buttons)


@pytest.mark.parametrize(
    "callback_const",
    ["DELETE_ACCOUNT_CONFIRM_CB", "DELETE_ACCOUNT_CANCEL_CB", "LOGOUT_CONFIRM_CB", "LOGOUT_CANCEL_CB"],
)
def test_consent_gate_allows_confirmation_callbacks(monkeypatch, callback_const):
    """Callback di conferma/annulla di `/elimina_account` e `/logout` bypassano il gate.

    Senza allowlist un utente con consenso non aggiornato che clicca "elimina account"
    o "logout" resterebbe bloccato invece di poter confermare l'azione già in corso.
    """
    import bot

    chat_id = f"10000001{['DELETE_ACCOUNT_CONFIRM_CB', 'DELETE_ACCOUNT_CANCEL_CB', 'LOGOUT_CONFIRM_CB', 'LOGOUT_CANCEL_CB'].index(callback_const)}"
    update = MagicMock()
    update.effective_chat.id = int(chat_id)
    update.callback_query.data = getattr(bot, callback_const)
    update.callback_query.answer = AsyncMock()
    context = MagicMock()
    context.bot.send_message = AsyncMock()

    get_user_spy = MagicMock(wraps=bot._user_store.get_user)
    monkeypatch.setattr(bot._user_store, "get_user", get_user_spy)

    asyncio.run(bot._consent_gate(update, context))

    get_user_spy.assert_not_called()
    update.callback_query.answer.assert_not_awaited()
    context.bot.send_message.assert_not_called()


def test_consent_gate_blocks_callback_not_in_allowlist():
    """Callback fuori allowlist (es. da una tastiera qualunque): il gate blocca comunque.

    Garantisce che l'allowlist introdotta per elimina_account/logout non sia diventata
    troppo permissiva rispetto a qualsiasi altro callback_data.
    """
    import bot
    from config import Config
    from telegram.ext import ApplicationHandlerStop

    chat_id = "100000020"
    bot._user_store.add_user(chat_id=chat_id, username="consent-cb-not-allowlisted", storage_backend="postgres")

    update = MagicMock()
    update.effective_chat.id = int(chat_id)
    update.message = None
    update.callback_query.data = "qualcosa_a_caso"
    update.callback_query.answer = AsyncMock()
    context = MagicMock()
    context.bot.send_message = AsyncMock()

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(bot._consent_gate(update, context))

    update.callback_query.answer.assert_awaited_once()
    context.bot.send_message.assert_awaited_once()
    kwargs = context.bot.send_message.call_args.kwargs
    assert kwargs["chat_id"] == int(chat_id)
    assert Config.WEBAPP_BASE_URL in kwargs["text"]


def test_consent_gate_accept_callback_data_returns_immediately(monkeypatch):
    """`callback_query.data == CONSENT_GATE_ACCEPT_CB`: il gate ritorna subito.

    Non deve sollevare `ApplicationHandlerStop` né controllare il consenso dell'utente
    (gestito da `handle_consent_gate_accept_callback` nel group normale, non dal gate).
    """
    import bot

    chat_id = "100000010"
    update = MagicMock()
    update.effective_chat.id = int(chat_id)
    update.callback_query.data = bot.CONSENT_GATE_ACCEPT_CB
    update.callback_query.answer = AsyncMock()
    context = MagicMock()
    context.bot.send_message = AsyncMock()

    get_user_spy = MagicMock(wraps=bot._user_store.get_user)
    monkeypatch.setattr(bot._user_store, "get_user", get_user_spy)

    asyncio.run(bot._consent_gate(update, context))

    get_user_spy.assert_not_called()
    update.callback_query.answer.assert_not_awaited()
    context.bot.send_message.assert_not_called()
