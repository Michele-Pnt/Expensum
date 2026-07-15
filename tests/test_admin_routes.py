"""Test e2e delle route della dashboard admin (blueprint admin_bp).

Verificano che ogni pagina/endpoint admin risponda correttamente con una sessione
admin, e che l'accesso non autenticato venga reindirizzato al login.
"""
from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.e2e


def _seed_app_store():
    from src.dashboard.app import store
    from src.user_store import ChatMessage, Feedback, JobRun, LlmUsageEvent, User, UserPlan

    now = datetime.utcnow()
    with store.Session() as s:
        if s.query(User).filter(User.chat_id == "admin_e2e_u1").first():
            return "admin_e2e_u1"
        s.add(User(chat_id="admin_e2e_u1", username="Alice",
                   created_at=now - timedelta(days=40), storage_backend="postgres",
                   onboarding_step="completed", setup_status="COMPLETED", is_active=True))
        s.add(UserPlan(chat_id="admin_e2e_u1", plan_type="pro", is_trial=False,
                       tokens_total=3_000_000, tokens_reset_at=now + timedelta(days=10)))
        s.add(LlmUsageEvent(chat_id="admin_e2e_u1", occurred_at=now, provider="mistral",
                            model="small", operation="expense_parse", prompt_tokens=100,
                            completion_tokens=50, total_tokens=150,
                            estimated_cost_amount=0.001, request_key="admin_e2e_rk1"))
        s.add(ChatMessage(chat_id="admin_e2e_u1", source="telegram", role="bot", text="ok",
                          metadata_json='{"amount": 10}', created_at=now - timedelta(days=38)))
        s.add(Feedback(chat_id="admin_e2e_u1", message="ciao", status="unread"))
        s.add(JobRun(job_id="db_backup", status="success", trigger_type="system",
                     return_code=0, finished_at=now))
        s.commit()
    return "admin_e2e_u1"


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["admin_logged_in"] = True


@pytest.mark.parametrize("route", [
    "/admin",
    "/admin/product",
    "/admin/business",
    "/admin/jobs",
    "/admin/users",
    "/admin/feedbacks",
    "/admin/logs",
    "/admin/api/users/token-usage",
    "/admin/api/overview",
])
def test_admin_routes_return_200_when_authenticated(client, route):
    _seed_app_store()
    _login_admin(client)
    resp = client.get(route)
    assert resp.status_code == 200


def test_overview_refresh_json_shape(client):
    """L'endpoint di auto-refresh deve avere la stessa forma dei dati usati da
    index() per il render iniziale, così il JS può riusare le stesse funzioni."""
    _seed_app_store()
    _login_admin(client)
    resp = client.get("/admin/api/overview")
    data = resp.get_json()
    assert set(data.keys()) == {"sys", "kpis", "analytics_data", "source_breakdown", "input_method_breakdown"}
    assert "chart_labels" in data["kpis"]
    assert len(data["kpis"]["chart_labels"]) == 10
    assert "requests_by_operation" in data["analytics_data"]


def test_vendored_chartjs_is_served(client):
    """Chart.js deve essere servito same-origin (nessuna dipendenza da CDN
    esterni, bloccata dalla CSP di produzione)."""
    resp = client.get("/admin/static/vendor/chart.umd.min.js")
    assert resp.status_code == 200
    assert b"Chart.js" in resp.data[:100]


def test_logs_viewer_rows_are_expandable(client, tmp_path, monkeypatch):
    """Ogni riga di log deve avere una riga di dettaglio associata (JSON completo,
    incl. exc_info) che si apre al click, non solo il meta troncato in tabella."""
    from config import Config
    log_file = tmp_path / "app.jsonl"
    log_file.write_text(
        '{"ts": "2026-07-15T09:00:00.000Z", "level": "ERROR", "domain": "app", '
        '"logger": "financial_agent.bot", "event": "boom", "meta": {"k": "v"}, '
        '"exc_info": "Traceback...\\nValueError: x"}\n'
    )
    monkeypatch.setattr(Config, "LOG_DIR", tmp_path)
    _login_admin(client)
    resp = client.get("/admin/logs")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "log-row-detail" in html
    assert "toggleLogRow" in html
    assert "Traceback" in html


def test_user_detail_page(client):
    chat_id = _seed_app_store()
    _login_admin(client)
    assert client.get(f"/admin/user/{chat_id}").status_code == 200
    assert client.get("/admin/user/does_not_exist").status_code == 404


def test_admin_routes_redirect_when_anonymous(client):
    resp = client.get("/admin", follow_redirects=False)
    assert resp.status_code == 302
    assert "/admin/login" in resp.headers["Location"]


def test_logs_viewer_rejects_unknown_file(client):
    _login_admin(client)
    # File fuori whitelist → fallback ad app.jsonl, comunque 200
    assert client.get("/admin/logs?file=/etc/passwd").status_code == 200
