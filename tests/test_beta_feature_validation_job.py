import asyncio
import logging
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _clean_beta_validation_tables():
    """`bot._user_store` è un singleton condiviso: senza reset esplicito, gli utenti/feedback
    creati da un test contaminerebbero `get_beta_default_users()` nei test successivi."""
    import bot
    from src.user_store import User, UserPlan, PlanChange, Feedback

    with bot._user_store.Session() as s:
        s.query(Feedback).delete()
        s.query(PlanChange).delete()
        s.query(UserPlan).delete()
        s.query(User).delete()
        s.commit()
    yield


def _run_job(job_fn, mock_app):
    """Esegue un job APScheduler come in produzione: loop dedicato in un thread separato."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        job_fn(mock_app, loop)
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
        loop.close()


def _make_app():
    app = MagicMock()
    app.bot.send_message = AsyncMock()
    return app


def _make_beta_user(store, chat_id: str, **kwargs):
    store.add_user(chat_id=chat_id, **kwargs)
    store.set_user_plan(chat_id, "pro", payment_reference="beta_default")


def _make_query_update_context(chat_id: str, callback_data: str, *, user_data=None):
    query = MagicMock()
    query.data = callback_data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()

    update = MagicMock()
    update.callback_query = query
    update.effective_chat.id = int(chat_id)

    context = MagicMock()
    context.user_data = user_data if user_data is not None else {}

    return query, update, context


# --- user_store: segmentazione beta + save_feedback esteso -----------------


def test_get_beta_default_users_returns_only_beta_default(monkeypatch):
    import bot

    _make_beta_user(bot._user_store, "920001")
    bot._user_store.add_user(chat_id="920002")  # utente free "normale", non beta

    chat_ids = bot._user_store.get_beta_default_users()

    assert chat_ids == ["920001"]


def test_get_beta_default_users_excludes_notifications_disabled():
    import bot
    from src.user_store import User

    _make_beta_user(bot._user_store, "920003")
    with bot._user_store.Session() as s:
        user = s.query(User).filter_by(chat_id="920003").first()
        user.notifications_enabled = False
        s.commit()

    assert bot._user_store.get_beta_default_users() == []


def test_save_feedback_with_category_and_rating_roundtrip():
    import bot
    from src.user_store import Feedback

    bot._user_store.add_user(chat_id="920004")
    bot._user_store.save_feedback("920004", "ottimo!", category="beta_validation", rating="up")

    with bot._user_store.Session() as s:
        fb = s.query(Feedback).filter_by(chat_id="920004").first()
        assert fb.category == "beta_validation"
        assert fb.rating == "up"
        assert fb.message == "ottimo!"


def test_save_feedback_without_category_defaults_to_none():
    """Retrocompatibilità: /feedback esistente non passa category/rating."""
    import bot
    from src.user_store import Feedback

    bot._user_store.add_user(chat_id="920005")
    bot._user_store.save_feedback("920005", "bug nella categoria spesa")

    with bot._user_store.Session() as s:
        fb = s.query(Feedback).filter_by(chat_id="920005").first()
        assert fb.category is None
        assert fb.rating is None


def test_has_recent_beta_validation_feedback():
    import bot

    bot._user_store.add_user(chat_id="920006")
    assert bot._user_store.has_recent_beta_validation_feedback("920006") is False

    bot._user_store.save_feedback("920006", "up", category="beta_validation", rating="up")
    assert bot._user_store.has_recent_beta_validation_feedback("920006") is True

    # Un feedback libero (categoria diversa) non conta come check-in beta recente
    bot._user_store.add_user(chat_id="920007")
    bot._user_store.save_feedback("920007", "altro feedback")
    assert bot._user_store.has_recent_beta_validation_feedback("920007") is False


# --- job settimanale ---------------------------------------------------------


def test_beta_validation_job_sends_only_to_beta_default_users():
    import bot

    _make_beta_user(bot._user_store, "920010")
    bot._user_store.add_user(chat_id="920011")  # non beta, non deve ricevere nulla
    app = _make_app()

    _run_job(bot._beta_feature_validation_job, app)

    app.bot.send_message.assert_awaited_once()
    _, kwargs = app.bot.send_message.call_args
    assert kwargs["chat_id"] == 920010


def test_beta_validation_job_excludes_non_telegram_beta_identities(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Il check-in ignora le identità beta che non hanno un chat ID Telegram."""
    import bot

    _make_beta_user(bot._user_store, "system")
    _make_beta_user(bot._user_store, "web_beta_validation")
    _make_beta_user(bot._user_store, "920015")
    app = _make_app()
    caplog.set_level(logging.INFO, logger="financial_agent.bot")

    _run_job(bot._beta_feature_validation_job, app)

    app.bot.send_message.assert_awaited_once()
    _, kwargs = app.bot.send_message.call_args
    assert kwargs["chat_id"] == 920015
    assert not any(
        getattr(record, "event", None) == "beta_validation_user_failed"
        for record in caplog.records
    )
    completed = next(
        record
        for record in caplog.records
        if getattr(record, "event", None) == "beta_validation_completed"
    )
    assert completed.meta["eligible"] == 1


def test_beta_validation_job_skips_users_with_recent_feedback():
    import bot

    _make_beta_user(bot._user_store, "920012")
    bot._user_store.save_feedback("920012", "up", category="beta_validation", rating="up")
    app = _make_app()

    _run_job(bot._beta_feature_validation_job, app)

    app.bot.send_message.assert_not_awaited()


def test_beta_validation_job_respects_notifications_opt_out():
    import bot
    from src.user_store import User

    _make_beta_user(bot._user_store, "920013")
    with bot._user_store.Session() as s:
        user = s.query(User).filter_by(chat_id="920013").first()
        user.notifications_enabled = False
        s.commit()
    app = _make_app()

    _run_job(bot._beta_feature_validation_job, app)

    app.bot.send_message.assert_not_awaited()


def test_beta_validation_job_message_has_three_reaction_buttons():
    import bot

    _make_beta_user(bot._user_store, "920014")
    app = _make_app()

    _run_job(bot._beta_feature_validation_job, app)

    _, kwargs = app.bot.send_message.call_args
    keyboard = kwargs["reply_markup"]
    callback_data = [btn.callback_data for row in keyboard.inline_keyboard for btn in row]
    assert len(callback_data) == 3
    assert all(cd.startswith("betaval:") for cd in callback_data)
    assert {cd.split(":")[-1] for cd in callback_data} == {"up", "down", "skip"}


# --- callback handler: step 1 (reazione) + step 2 (feedback libero) --------


def test_handle_callback_betaval_saves_feedback_and_prompts_step_two(monkeypatch):
    import bot
    from src.user_store import Feedback

    bot._user_store.add_user(chat_id="920020")
    monkeypatch.setattr(bot, "_is_authorized", lambda u: True)

    feature_code = bot.BETA_VALIDATION_FEATURES[0][0]
    query, update, context = _make_query_update_context("920020", f"betaval:{feature_code}:up")

    asyncio.run(bot.handle_callback(update, context))

    with bot._user_store.Session() as s:
        fb = s.query(Feedback).filter_by(chat_id="920020").first()
        assert fb.category == "beta_validation"
        assert fb.rating == "up"

    assert context.user_data["waiting_for_beta_feedback"] is True
    query.edit_message_text.assert_awaited_once()
    _, kwargs = query.edit_message_text.call_args
    assert "reply_markup" in kwargs


def test_handle_callback_betaval_skip_feedback_clears_waiting_flag(monkeypatch):
    import bot

    monkeypatch.setattr(bot, "_is_authorized", lambda u: True)
    query, update, context = _make_query_update_context(
        "920021", "betaval_skip_feedback", user_data={"waiting_for_beta_feedback": True},
    )

    asyncio.run(bot.handle_callback(update, context))

    assert "waiting_for_beta_feedback" not in context.user_data
    query.edit_message_text.assert_awaited_once()


def test_handle_text_captures_beta_feedback_and_skips_expense_parsing(monkeypatch):
    import bot

    bot._user_store.add_user(chat_id="920022")
    monkeypatch.setattr(bot, "_is_authorized", lambda u: True)
    monkeypatch.setattr(bot, "is_rate_limited", lambda *a, **k: False)
    monkeypatch.setattr(bot, "_check_and_consume_tokens", AsyncMock(return_value=True))
    process_mock = AsyncMock()
    monkeypatch.setattr(bot, "_process_expense_text", process_mock)

    update = MagicMock()
    update.effective_chat.id = 920022
    update.message.text = "Ottima l'app, continuate così!"
    update.message.chat.send_action = AsyncMock()
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.user_data = {"waiting_for_beta_feedback": True}

    asyncio.run(bot.handle_text(update, context))

    from src.user_store import Feedback

    with bot._user_store.Session() as s:
        fb = s.query(Feedback).filter_by(chat_id="920022").first()
        assert fb.message == "Ottima l'app, continuate così!"
        assert fb.category == "beta_validation"

    assert "waiting_for_beta_feedback" not in context.user_data
    process_mock.assert_not_awaited()
    update.message.reply_text.assert_awaited_once()
