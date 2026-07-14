"""Test del layer di aggregazione della dashboard admin (src/dashboard/admin_metrics.py).

Tier `integration`: usano SQLite in-memory (fixture mock_db_session) e verificano
che le metriche derivate producano i valori attesi su dataset noti.
"""
from datetime import datetime, timedelta

import pytest

from src.dashboard import admin_metrics as m
from src.user_store import (
    ChatMessage,
    Feedback,
    JobRun,
    LlmUsageEvent,
    PlanChange,
    TallyLead,
    User,
    UserPlan,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 7, 14, 12, 0, 0)


def _seed(store):
    """Popola un dataset noto: 1 utente pro attivo con storico, 1 free nuovo."""
    with store.Session() as s:
        s.add(User(chat_id="u1", username="Alice", created_at=NOW - timedelta(days=40),
                   storage_backend="postgres", onboarding_step="completed",
                   onboarding_completed_at=NOW - timedelta(days=39),
                   setup_status="COMPLETED", is_active=True))
        s.add(User(chat_id="u2", username="Bob", created_at=NOW - timedelta(days=3),
                   storage_backend="notion", onboarding_step="pending",
                   setup_status="WAIT_ACCOUNTS", is_active=True))
        s.add(UserPlan(chat_id="u1", plan_type="pro", is_trial=False,
                       tokens_total=3_000_000, tokens_reset_at=NOW + timedelta(days=10)))
        s.add(UserPlan(chat_id="u2", plan_type="free", is_trial=False,
                       tokens_total=150_000, tokens_reset_at=NOW + timedelta(days=20)))
        s.add(PlanChange(chat_id="u1", from_plan="free", to_plan="pro",
                         change_type="upgrade", changed_at=NOW - timedelta(days=10)))
        # Eventi LLM: u1 attivo di recente, u2 una volta
        for i, cid in enumerate(["u1", "u1", "u2"]):
            s.add(LlmUsageEvent(chat_id=cid, occurred_at=NOW - timedelta(days=i),
                                provider="mistral", model="small", operation="expense_parse",
                                prompt_tokens=100, completion_tokens=50, total_tokens=150,
                                estimated_cost_amount=0.001, request_key=f"rk{i}{cid}"))
        # Transazioni confermate di u1 (chat_messages con metadata)
        s.add(ChatMessage(chat_id="u1", source="telegram", role="bot", text="ok",
                          metadata_json='{"amount": 10}', created_at=NOW - timedelta(days=38)))
        s.add(ChatMessage(chat_id="u1", source="telegram", role="bot", text="ok",
                          metadata_json='{"amount": 20}', created_at=NOW - timedelta(days=30)))
        s.add(Feedback(chat_id="u2", message="ciao", status="unread"))
        s.add(TallyLead(tally_submission_id="t1", email="x@y.z",
                        synced_to_brevo=True, beta_account_granted=True))
        s.commit()


def test_overview_kpis(mock_db_session):
    _seed(mock_db_session)
    with mock_db_session.Session() as s:
        kpi = m.get_overview_kpis(s)
    assert kpi["users_count"] == 2
    assert kpi["active_users"] == 2
    assert kpi["unread_feedback"] == 1
    assert len(kpi["chart_labels"]) == 10


def test_retention(mock_db_session):
    _seed(mock_db_session)
    with mock_db_session.Session() as s:
        r = m.get_retention(s)
    assert r["total_users"] == 2
    # Solo u1 ha account ≥ 60 giorni? No: u1 ha 40 giorni → nessun idoneo a 60.
    assert r["cohort_retention"][60]["eligible"] == 0
    # Entrambi hanno attività recente → rolling active a 7 giorni = 2
    assert r["rolling_active"][7]["count"] == 2


def test_expense_timing(mock_db_session):
    _seed(mock_db_session)
    with mock_db_session.Session() as s:
        t = m.get_expense_timing(s)
    assert t["users_with_tx"] == 1  # solo u1 ha transazioni
    assert t["users_without_tx"] == 1
    # prima spesa u1: 40-38 = 2 giorni dopo la registrazione
    assert t["time_to_first_expense"]["median_days"] == pytest.approx(2.0, abs=0.1)
    # intervallo tra le due spese: 38→30 = 8 giorni
    assert t["interval_between_expenses"]["median_days"] == pytest.approx(8.0, abs=0.1)


def test_onboarding_funnel(mock_db_session):
    _seed(mock_db_session)
    with mock_db_session.Session() as s:
        o = m.get_onboarding_funnel(s)
    assert o["total"] == 2
    assert o["completed"] == 1
    assert o["skipped_pending"] == 1
    assert o["by_step"]["completed"] == 1


def test_funnel_revenue(mock_db_session, monkeypatch):
    monkeypatch.setattr(m, "PRO_PRICE_EUR", 5.0)
    _seed(mock_db_session)
    with mock_db_session.Session() as s:
        f = m.get_funnel_revenue(s)
    assert f["pro_count"] == 1
    assert f["paying_pro"] == 1
    assert f["mrr_eur"] == 5.0
    assert f["upgrades_30d"] == 1


def test_engagement_acquisition(mock_db_session):
    _seed(mock_db_session)
    with mock_db_session.Session() as s:
        e = m.get_engagement_acquisition(s)
    assert e["mau"] == 2          # u1 e u2 attivi negli ultimi 30gg
    assert e["storage_backend"] == {"postgres": 1, "notion": 1}
    assert e["waitlist"]["beta_granted"] == 1


def test_monthly_token_usage(mock_db_session):
    _seed(mock_db_session)
    with mock_db_session.Session() as s:
        mt = m.get_monthly_token_usage(s)
    assert mt["per_user"][0]["chat_id"] == "u1"  # u1 consuma di più
    assert mt["current_month_stats"]["active_users"] >= 1


def test_user_detail(mock_db_session):
    _seed(mock_db_session)
    with mock_db_session.Session() as s:
        d = m.get_user_detail(s, "u1")
        missing = m.get_user_detail(s, "nope")
    assert missing is None
    assert d["plan_type"] == "pro"
    assert d["tx_count"] == 2
    assert d["tokens_total"] == 300
    assert d["time_to_first_days"] == pytest.approx(2.0, abs=0.1)


def test_jobs_status_states(mock_db_session):
    with mock_db_session.Session() as s:
        s.add(JobRun(job_id="nightly_category_sync", status="success", finished_at=NOW))
        s.add(JobRun(job_id="trial_expiry_job", status="error",
                     error_text="ValueError: x", finished_at=NOW))
        s.commit()
    with mock_db_session.Session() as s:
        res = m.get_jobs_status(s, now=NOW)
    states = {j["job_id"]: j["state"] for j in res["jobs"]}
    assert states["nightly_category_sync"] == "success"
    assert states["trial_expiry_job"] == "error"
    # daily atteso alle 03:00-09:00, ora 12:00, nessun run → no-show
    assert states["daily_dashboard_job"] == "missed"
    # 14 luglio 2026 è martedì → job settimanale (lunedì) e mensile (giorno 1) non previsti
    assert states["weekly_plan_job"] == "not_scheduled"
    assert states["monthly_plan_job"] == "not_scheduled"
    assert res["has_alerts"] is True


def test_record_and_cleanup_job_runs(mock_db_session):
    mock_db_session.record_job_run("db_backup", "success", trigger_type="system", return_code=0)
    with mock_db_session.Session() as s:
        s.add(JobRun(job_id="old", status="success", finished_at=NOW - timedelta(days=200)))
        s.commit()
    deleted = mock_db_session.cleanup_old_job_runs(days=90)
    assert deleted == 1
    with mock_db_session.Session() as s:
        remaining = s.query(JobRun).count()
    assert remaining == 1  # solo db_backup resta
