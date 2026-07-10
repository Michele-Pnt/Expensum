from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _clean_trial_tables():
    """`bot._user_store` è un singleton condiviso: senza reset esplicito, gli utenti trial
    creati da un test contaminerebbero `get_expired_trials()` nei test successivi."""
    import bot
    from src.user_store import User, UserPlan, TrialLifecycleEvent, PlanChange

    with bot._user_store.Session() as s:
        s.query(TrialLifecycleEvent).delete()
        s.query(PlanChange).delete()
        s.query(UserPlan).delete()
        s.query(User).delete()
        s.commit()
    yield


def test_trial_expiry_job_skips_when_automation_disabled(monkeypatch):
    import bot

    monkeypatch.setattr(bot.Config, "TRIAL_AUTOMATION_ENABLED", False)
    bot._user_store.add_user(chat_id="exp1")
    bot._user_store.start_trial("exp1", days=30)
    with bot._user_store.Session() as s:
        from src.user_store import UserPlan
        plan = s.query(UserPlan).filter_by(chat_id="exp1").first()
        plan.trial_ends_at = datetime.utcnow() - timedelta(days=1)
        s.commit()

    bot._trial_expiry_job(app=None, loop=None)

    plan = bot._user_store.get_user_plan("exp1")
    assert plan["is_trial"] is True
    assert plan["plan_type"] == "pro"


def test_trial_expiry_job_downgrades_expired_trial(monkeypatch):
    import bot

    monkeypatch.setattr(bot.Config, "TRIAL_AUTOMATION_ENABLED", True)
    bot._user_store.add_user(chat_id="exp2")
    bot._user_store.start_trial("exp2", days=30)
    with bot._user_store.Session() as s:
        from src.user_store import UserPlan
        plan = s.query(UserPlan).filter_by(chat_id="exp2").first()
        plan.trial_ends_at = datetime.utcnow() - timedelta(days=1)
        s.commit()

    bot._trial_expiry_job(app=None, loop=None)

    plan = bot._user_store.get_user_plan("exp2")
    assert plan["is_trial"] is False
    assert plan["plan_type"] == "free"


def test_trial_expiry_job_leaves_active_trial_untouched(monkeypatch):
    import bot

    monkeypatch.setattr(bot.Config, "TRIAL_AUTOMATION_ENABLED", True)
    bot._user_store.add_user(chat_id="exp3")
    bot._user_store.start_trial("exp3", days=30)  # scade tra 30gg, non ancora

    bot._trial_expiry_job(app=None, loop=None)

    plan = bot._user_store.get_user_plan("exp3")
    assert plan["is_trial"] is True
    assert plan["plan_type"] == "pro"
