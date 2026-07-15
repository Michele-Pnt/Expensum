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
    TxEvent,
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


def test_token_analytics_90d_overall_conversion_rate(mock_db_session):
    """Regressione: l'overall conversion rate calcolato lato server deve riflettere
    i successi reali, non restare bloccato a 0% come faceva il vecchio JS lato
    client (variabile totalSuccesses mai incrementata)."""
    with mock_db_session.Session() as s:
        s.add(User(chat_id="u1", username="Alice", created_at=NOW))
        s.add(UserPlan(chat_id="u1", plan_type="free", is_trial=False,
                       tokens_total=150_000, tokens_reset_at=NOW + timedelta(days=10)))
        # 3 richieste riuscite (total_tokens > 0), 1 fallita (total_tokens = 0)
        for i in range(3):
            s.add(LlmUsageEvent(chat_id="u1", occurred_at=NOW - timedelta(days=i),
                                provider="mistral", model="small", operation="expense_parse",
                                prompt_tokens=100, completion_tokens=50, total_tokens=150,
                                estimated_cost_amount=0.001, request_key=f"ok{i}"))
        s.add(LlmUsageEvent(chat_id="u1", occurred_at=NOW, provider="mistral", model="small",
                            operation="expense_parse", prompt_tokens=0, completion_tokens=0,
                            total_tokens=0, estimated_cost_amount=0.0, request_key="fail1"))
        s.commit()
    with mock_db_session.Session() as s:
        res = m.get_token_analytics_90d(s)

    assert res["overall"]["total_requests"] == 4
    assert res["overall"]["conversion_rate_pct"] == 75.0
    assert res["overall"]["avg_tokens"] > 0
    assert res["overall"]["operation_count"] == 1


def test_usage_chart_custom_period(mock_db_session):
    """Il selettore periodo (10gg/1mese/2mesi/N a scelta) chiama get_usage_chart
    con `days` diverso da 10: verifica che il bucketing rispetti la finestra."""
    with mock_db_session.Session() as s:
        s.add(User(chat_id="u1", created_at=NOW))
        # Un evento a 5 giorni fa (dentro sia 10gg che 30gg), uno a 40 giorni fa
        # (fuori dalla finestra 10gg/30gg, dentro i 60gg).
        s.add(LlmUsageEvent(chat_id="u1", occurred_at=NOW - timedelta(days=5),
                            provider="mistral", model="small", operation="expense_parse",
                            total_tokens=100, request_key="recent"))
        s.add(LlmUsageEvent(chat_id="u1", occurred_at=NOW - timedelta(days=40),
                            provider="mistral", model="small", operation="expense_parse",
                            total_tokens=200, request_key="old"))
        s.commit()
    with mock_db_session.Session() as s:
        chart_10 = m.get_usage_chart(s, days=10, now=NOW)
        chart_60 = m.get_usage_chart(s, days=60, now=NOW)

    assert len(chart_10["chart_labels"]) == 10
    assert sum(chart_10["chart_total"]) == 100  # solo l'evento recente
    assert len(chart_60["chart_labels"]) == 60
    assert sum(chart_60["chart_total"]) == 300  # entrambi gli eventi


def test_usage_chart_caps_max_days(mock_db_session):
    with mock_db_session.Session() as s:
        chart = m.get_usage_chart(s, days=99999, now=NOW)
    assert len(chart["chart_labels"]) == m.MAX_USAGE_CHART_DAYS


def test_source_breakdown_telegram_vs_webapp(mock_db_session):
    """Il canale si deriva dal prefisso 'web_' del chat_id, senza colonna dedicata."""
    with mock_db_session.Session() as s:
        s.add(User(chat_id="123456", created_at=NOW))
        s.add(User(chat_id="web_abc123", created_at=NOW))
        s.add(LlmUsageEvent(chat_id="123456", occurred_at=NOW, provider="mistral",
                            model="small", operation="expense_parse", total_tokens=100,
                            estimated_cost_amount=0.01, request_key="tg1"))
        s.add(LlmUsageEvent(chat_id="123456", occurred_at=NOW, provider="gemini",
                            model="gemini", operation="voice_transcribe", total_tokens=50,
                            estimated_cost_amount=0.005, request_key="tg2"))
        s.add(LlmUsageEvent(chat_id="web_abc123", occurred_at=NOW, provider="mistral",
                            model="small", operation="chat_parse", total_tokens=300,
                            estimated_cost_amount=0.02, request_key="web1"))
        s.commit()
    with mock_db_session.Session() as s:
        res = m.get_source_breakdown_90d(s)

    assert res["telegram"]["requests"] == 2
    assert res["telegram"]["total_tokens"] == 150
    assert res["webapp"]["requests"] == 1
    assert res["webapp"]["total_tokens"] == 300


def test_input_method_breakdown_90d(mock_db_session):
    """input_method distingue testo/voce/foto; le righe storiche (NULL, prima
    della colonna aggiunta il 2026-07-14) finiscono in 'n/d'."""
    with mock_db_session.Session() as s:
        s.add(User(chat_id="u1", created_at=NOW))
        s.add(LlmUsageEvent(chat_id="u1", occurred_at=NOW, provider="mistral", model="small",
                            operation="expense_parse", input_method="text", total_tokens=100,
                            request_key="t1"))
        s.add(LlmUsageEvent(chat_id="u1", occurred_at=NOW, provider="gemini", model="gemini",
                            operation="voice_transcribe", input_method="voice", total_tokens=50,
                            request_key="v1"))
        s.add(LlmUsageEvent(chat_id="u1", occurred_at=NOW, provider="mistral", model="small",
                            operation="weekly_plan", input_method=None, total_tokens=200,
                            request_key="p1"))
        s.commit()
    with mock_db_session.Session() as s:
        res = m.get_input_method_breakdown_90d(s)

    assert res["text"] == {"requests": 1, "total_tokens": 100}
    assert res["voice"] == {"requests": 1, "total_tokens": 50}
    assert res["n/d"] == {"requests": 1, "total_tokens": 200}


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


def test_funnel_revenue_excludes_beta_grants_from_mrr(mock_db_session, monkeypatch):
    """Un utente pro con reason='beta_default' (grant amministrativo, non un vero
    pagamento — vedi scripts/upgrade_beta_users_to_pro.py) non deve contribuire
    all'MRR, ma resta visibile come pro_count/beta_grant_pro."""
    monkeypatch.setattr(m, "PRO_PRICE_EUR", 5.0)
    with mock_db_session.Session() as s:
        s.add(User(chat_id="beta1", created_at=NOW))
        s.add(User(chat_id="paid1", created_at=NOW))
        s.add(UserPlan(chat_id="beta1", plan_type="pro", is_trial=False,
                       tokens_total=3_000_000, tokens_reset_at=NOW + timedelta(days=10)))
        s.add(UserPlan(chat_id="paid1", plan_type="pro", is_trial=False,
                       tokens_total=3_000_000, tokens_reset_at=NOW + timedelta(days=10)))
        s.add(PlanChange(chat_id="beta1", from_plan="free", to_plan="pro",
                         change_type="upgrade", changed_at=NOW, reason="beta_default"))
        s.add(PlanChange(chat_id="paid1", from_plan="free", to_plan="pro",
                         change_type="upgrade", changed_at=NOW, reason="stripe_evt_123"))
        s.commit()
    with mock_db_session.Session() as s:
        f = m.get_funnel_revenue(s)

    assert f["pro_count"] == 2
    assert f["beta_grant_pro"] == 1
    assert f["real_paying_pro"] == 1
    assert f["mrr_eur"] == 5.0  # solo paid1, non beta1


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


def test_tx_success_by_type_method(mock_db_session):
    with mock_db_session.Session() as s:
        s.add(User(chat_id="u1", username="Alice", created_at=NOW))
        s.add(TxEvent(chat_id="u1", tx_type="expense", input_method="text",
                      outcome="confirmed", source="telegram", occurred_at=NOW))
        s.add(TxEvent(chat_id="u1", tx_type="expense", input_method="text",
                      outcome="confirmed", source="telegram", occurred_at=NOW))
        s.add(TxEvent(chat_id="u1", tx_type="expense", input_method="text",
                      outcome="failed", source="telegram", reason="no_account", occurred_at=NOW))
        s.add(TxEvent(chat_id="u1", tx_type="expense", input_method="photo",
                      outcome="confirmed", source="telegram", occurred_at=NOW))
        s.add(TxEvent(chat_id="u1", tx_type="transfer", input_method="button",
                      outcome="cancelled", source="telegram", reason="user_cancelled", occurred_at=NOW))
        s.commit()
    with mock_db_session.Session() as s:
        res = m.get_tx_success_by_type_method(s)

    by_key = {(r["tx_type"], r["input_method"]): r for r in res["rows"]}
    text_row = by_key[("expense", "text")]
    assert text_row["confirmed"] == 2
    assert text_row["failed"] == 1
    assert text_row["total"] == 3
    assert text_row["success_rate_pct"] == pytest.approx(66.7, abs=0.1)

    photo_row = by_key[("expense", "photo")]
    assert photo_row["success_rate_pct"] == 100.0

    transfer_row = by_key[("transfer", "button")]
    assert transfer_row["cancelled"] == 1
    assert transfer_row["success_rate_pct"] == 0.0

    assert res["overall_total"] == 5
    assert res["overall_success_rate_pct"] == pytest.approx(60.0, abs=0.1)


def test_tx_success_respects_days_window(mock_db_session):
    with mock_db_session.Session() as s:
        s.add(User(chat_id="u1", created_at=NOW))
        s.add(TxEvent(chat_id="u1", tx_type="expense", input_method="text",
                      outcome="confirmed", source="telegram", occurred_at=NOW - timedelta(days=40)))
        s.commit()
    with mock_db_session.Session() as s:
        res = m.get_tx_success_by_type_method(s, days=30)
    assert res["overall_total"] == 0  # fuori dalla finestra di 30gg


def test_record_tx_event(mock_db_session):
    with mock_db_session.Session() as s:
        s.add(User(chat_id="u1", created_at=NOW))
        s.commit()
    mock_db_session.record_tx_event("u1", "expense", "voice", "confirmed", "telegram")
    with mock_db_session.Session() as s:
        events = s.query(TxEvent).filter(TxEvent.chat_id == "u1").all()
    assert len(events) == 1
    assert events[0].tx_type == "expense"
    assert events[0].input_method == "voice"
    assert events[0].outcome == "confirmed"
    assert events[0].source == "telegram"


def test_tour_funnel(mock_db_session):
    with mock_db_session.Session() as s:
        s.add(User(chat_id="u1", created_at=NOW, tour_status="completed",
                   tour_step="tour-complete", tour_completed_at=NOW))
        s.add(User(chat_id="u2", created_at=NOW, tour_status="skipped", tour_step="analytics-tabs"))
        s.add(User(chat_id="u3", created_at=NOW, tour_status="in_progress", tour_step="chat-input"))
        s.add(User(chat_id="u4", created_at=NOW))  # mai avviato il tour
        s.commit()
    with mock_db_session.Session() as s:
        res = m.get_tour_funnel(s)

    assert res["total_started"] == 3  # u4 non conta: tour_status is None
    assert res["completed"] == 1
    assert res["skipped"] == 1
    assert res["in_progress"] == 1
    assert res["completed_pct"] == pytest.approx(33.3, abs=0.1)
    assert res["abandon_by_step"] == {"analytics-tabs": 1, "chat-input": 1}
    assert "tour-complete" not in res["abandon_by_step"]  # completati esclusi


def test_record_tour_event(mock_db_session):
    with mock_db_session.Session() as s:
        s.add(User(chat_id="u1", created_at=NOW))
        s.commit()

    mock_db_session.record_tour_event("u1", "tour_started", None)
    with mock_db_session.Session() as s:
        u = s.query(User).filter(User.chat_id == "u1").first()
        assert u.tour_status == "in_progress"
        assert u.tour_completed_at is None

    mock_db_session.record_tour_event("u1", "tour_step_viewed", "analytics-tabs")
    with mock_db_session.Session() as s:
        u = s.query(User).filter(User.chat_id == "u1").first()
        assert u.tour_step == "analytics-tabs"
        assert u.tour_status == "in_progress"  # invariato da un semplice step-view

    mock_db_session.record_tour_event("u1", "tour_completed", "tour-complete")
    with mock_db_session.Session() as s:
        u = s.query(User).filter(User.chat_id == "u1").first()
        assert u.tour_status == "completed"
        assert u.tour_completed_at is not None


def test_record_tour_event_unknown_user_is_noop(mock_db_session):
    mock_db_session.record_tour_event("does_not_exist", "tour_started", None)  # non deve sollevare
