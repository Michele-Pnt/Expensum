import asyncio
import threading
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _clean_trial_tables():
    """`bot._user_store` è un singleton condiviso (sqlite in-memory con StaticPool per
    supportare il loop del job su un thread separato, come in produzione): senza reset
    esplicito, gli utenti trial creati da un test contaminerebbero `get_active_trial_users()`
    nei test successivi."""
    import bot
    from src.user_store import User, UserPlan, TrialLifecycleEvent, PlanChange

    with bot._user_store.Session() as s:
        s.query(TrialLifecycleEvent).delete()
        s.query(PlanChange).delete()
        s.query(UserPlan).delete()
        s.query(User).delete()
        s.commit()
    yield


def _run_job(job_fn, mock_app):
    """Esegue un job APScheduler come in produzione: loop dedicato in un thread separato,
    il job usa asyncio.run_coroutine_threadsafe(...) su quel loop."""
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


def _backdate_trial(store, chat_id: str, days: int):
    from src.user_store import UserPlan
    with store.Session() as s:
        plan = s.query(UserPlan).filter_by(chat_id=chat_id).first()
        plan.trial_started_at = datetime.utcnow() - timedelta(days=days)
        s.commit()


def test_drip_skips_when_automation_disabled(monkeypatch):
    import bot

    monkeypatch.setattr(bot.Config, "TRIAL_AUTOMATION_ENABLED", False)
    bot._user_store.add_user(chat_id="910001")
    bot._user_store.start_trial("910001", days=30)
    _backdate_trial(bot._user_store, "910001", 7)
    app = _make_app()

    _run_job(bot._trial_lifecycle_job, app)

    app.bot.send_message.assert_not_awaited()


def test_drip_sends_telegram_and_email_at_d7(monkeypatch):
    import bot

    monkeypatch.setattr(bot.Config, "TRIAL_AUTOMATION_ENABLED", True)
    bot._user_store.add_user(chat_id="910002", email="user@example.com", storage_backend="postgres")
    bot._user_store.start_trial("910002", days=30)
    _backdate_trial(bot._user_store, "910002", 7)
    app = _make_app()

    with patch("bot.brevo_client.send_transactional_email") as mock_email:
        _run_job(bot._trial_lifecycle_job, app)

    app.bot.send_message.assert_awaited_once()
    mock_email.assert_called_once()
    assert bot._user_store.get_lifecycle_sent_steps("910002", "telegram") == {"d7"}
    assert bot._user_store.get_lifecycle_sent_steps("910002", "email") == {"d7"}


def test_drip_does_not_resend_same_step_same_day(monkeypatch):
    import bot

    monkeypatch.setattr(bot.Config, "TRIAL_AUTOMATION_ENABLED", True)
    bot._user_store.add_user(chat_id="910003", storage_backend="postgres")
    bot._user_store.start_trial("910003", days=30)
    _backdate_trial(bot._user_store, "910003", 7)
    app = _make_app()

    with patch("bot.brevo_client.send_transactional_email"):
        _run_job(bot._trial_lifecycle_job, app)
        _run_job(bot._trial_lifecycle_job, app)

    assert app.bot.send_message.await_count == 1


def test_drip_excludes_converted_pro_user(monkeypatch):
    """Se l'utente converte a pagamento, is_trial diventa False ed esce dal funnel."""
    import bot

    monkeypatch.setattr(bot.Config, "TRIAL_AUTOMATION_ENABLED", True)
    bot._user_store.add_user(chat_id="910004")
    bot._user_store.start_trial("910004", days=30)
    _backdate_trial(bot._user_store, "910004", 7)
    bot._user_store.set_user_plan("910004", "pro", payment_reference="stripe_evt_1")
    app = _make_app()

    with patch("bot.brevo_client.send_transactional_email") as mock_email:
        _run_job(bot._trial_lifecycle_job, app)

    app.bot.send_message.assert_not_awaited()
    mock_email.assert_not_called()


def test_drip_skips_email_when_user_has_no_email(monkeypatch):
    import bot

    monkeypatch.setattr(bot.Config, "TRIAL_AUTOMATION_ENABLED", True)
    bot._user_store.add_user(chat_id="910005", storage_backend="postgres")
    bot._user_store.start_trial("910005", days=30)
    _backdate_trial(bot._user_store, "910005", 7)
    app = _make_app()

    with patch("bot.brevo_client.send_transactional_email") as mock_email:
        _run_job(bot._trial_lifecycle_job, app)

    app.bot.send_message.assert_awaited_once()
    mock_email.assert_not_called()


def test_drip_excludes_user_with_notifications_disabled(monkeypatch):
    import bot

    monkeypatch.setattr(bot.Config, "TRIAL_AUTOMATION_ENABLED", True)
    bot._user_store.add_user(chat_id="910006", storage_backend="postgres")
    bot._user_store.start_trial("910006", days=30)
    _backdate_trial(bot._user_store, "910006", 7)
    with bot._user_store.Session() as s:
        from src.user_store import User
        user = s.query(User).filter_by(chat_id="910006").first()
        user.notifications_enabled = False
        s.commit()
    app = _make_app()

    with patch("bot.brevo_client.send_transactional_email") as mock_email:
        _run_job(bot._trial_lifecycle_job, app)

    app.bot.send_message.assert_not_awaited()
    mock_email.assert_not_called()
