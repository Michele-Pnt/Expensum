"""Test per `handle_consent_gate_accept_callback` (bot.py).

Handler del bottone inline "✅ Ho letto e accetto" mostrato dal gate `_consent_gate`
(vedi `tests/test_bot_consent_gate.py`): unica via di accettazione percorribile dagli
account `storage_backend="notion"`, che non hanno email/password per la webapp.
"""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

pytestmark = pytest.mark.integration


def _make_callback_update(chat_id: str):
    update = MagicMock()
    update.effective_chat.id = int(chat_id)
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    context = MagicMock()
    return update, context


def test_accept_callback_updates_consent_and_writes_audit_log():
    """Utente esistente: consenso aggiornato a entrambe le versioni correnti + 2 audit log."""
    import bot
    from config import Config
    from src.user_store import AuditLog

    chat_id = "200000001"
    bot._user_store.add_user(chat_id=chat_id, username="accept-cb-ok", storage_backend="notion")

    update, context = _make_callback_update(chat_id)

    asyncio.run(bot.handle_consent_gate_accept_callback(update, context))

    update.callback_query.answer.assert_awaited_once()
    update.callback_query.edit_message_text.assert_awaited_once()

    user = bot._user_store.get_user(chat_id)
    assert user.privacy_policy_version_accepted == Config.CURRENT_PRIVACY_POLICY_VERSION
    assert user.tos_version_accepted == Config.CURRENT_TOS_VERSION
    assert user.privacy_accepted_at is not None
    assert user.tos_accepted_at is not None

    with bot._user_store.Session() as session:
        logs = (
            session.query(AuditLog)
            .filter(AuditLog.user_id == chat_id, AuditLog.action == "consent_change")
            .all()
        )
        consent_types = {log.metadata_json["consent_type"] for log in logs}
    assert consent_types == {"privacy_policy", "terms_of_service"}


def test_accept_callback_already_accepted_is_idempotent():
    """Utente già a versione corrente (bottone di un gate precedente): no sovrascrittura/audit.

    Copre la guardia di idempotenza aggiunta a `handle_consent_gate_accept_callback`:
    se il consenso è già aggiornato (es. accettato altrove nel frattempo) l'handler deve
    limitarsi a confermarlo, senza richiamare accept_privacy_policy/accept_terms_of_service
    né scrivere nuove righe di audit log `consent_change`.
    """
    import bot
    from config import Config
    from src.user_store import AuditLog

    chat_id = "200000003"
    bot._user_store.add_user(chat_id=chat_id, username="accept-cb-idempotent", storage_backend="notion")
    bot._user_store.accept_privacy_policy(chat_id, Config.CURRENT_PRIVACY_POLICY_VERSION)
    bot._user_store.accept_terms_of_service(chat_id, Config.CURRENT_TOS_VERSION)

    with bot._user_store.Session() as session:
        logs_before = (
            session.query(AuditLog)
            .filter(AuditLog.user_id == chat_id, AuditLog.action == "consent_change")
            .count()
        )

    update, context = _make_callback_update(chat_id)

    accept_privacy_spy = MagicMock(wraps=bot._user_store.accept_privacy_policy)
    accept_tos_spy = MagicMock(wraps=bot._user_store.accept_terms_of_service)
    write_audit_spy = MagicMock(wraps=bot._user_store.write_audit_log)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(bot._user_store, "accept_privacy_policy", accept_privacy_spy)
        monkeypatch.setattr(bot._user_store, "accept_terms_of_service", accept_tos_spy)
        monkeypatch.setattr(bot._user_store, "write_audit_log", write_audit_spy)

        asyncio.run(bot.handle_consent_gate_accept_callback(update, context))

    update.callback_query.answer.assert_awaited_once()
    update.callback_query.edit_message_text.assert_awaited_once()
    assert "già accettato" in update.callback_query.edit_message_text.call_args.args[0]

    accept_privacy_spy.assert_not_called()
    accept_tos_spy.assert_not_called()
    write_audit_spy.assert_not_called()

    with bot._user_store.Session() as session:
        logs_after = (
            session.query(AuditLog)
            .filter(AuditLog.user_id == chat_id, AuditLog.action == "consent_change")
            .count()
        )
    assert logs_after == logs_before


def test_accept_callback_unknown_user_is_noop(monkeypatch):
    """Utente inesistente: nessuna eccezione, nessuna chiamata ad accept_privacy_policy/tos."""
    import bot

    chat_id = "200000002"  # mai registrato
    update, context = _make_callback_update(chat_id)

    accept_privacy_spy = MagicMock(wraps=bot._user_store.accept_privacy_policy)
    accept_tos_spy = MagicMock(wraps=bot._user_store.accept_terms_of_service)
    monkeypatch.setattr(bot._user_store, "accept_privacy_policy", accept_privacy_spy)
    monkeypatch.setattr(bot._user_store, "accept_terms_of_service", accept_tos_spy)

    asyncio.run(bot.handle_consent_gate_accept_callback(update, context))

    update.callback_query.answer.assert_awaited_once()
    accept_privacy_spy.assert_not_called()
    accept_tos_spy.assert_not_called()
    update.callback_query.edit_message_text.assert_not_awaited()
