import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.e2e


def test_analytics_bucket_yearly_marks_current_year_partial():
    from datetime import date

    from src.dashboard.blueprints.analytics_routes import _analytics_bucket

    assert _analytics_bucket(date(2026, 2, 1), "yearly", date(2026, 8, 24)) == (
        "2026",
        "2026",
        True,
    )


def test_analytics_bucket_quarterly_has_stable_key_and_label():
    from datetime import date

    from src.dashboard.blueprints.analytics_routes import _analytics_bucket

    assert _analytics_bucket(date(2025, 5, 1), "quarterly", date(2026, 8, 24)) == (
        "2025-Q2",
        "Q2 2025",
        False,
    )


def _login_analytics_user(client, store, chat_id: str) -> None:
    store.add_user(chat_id=chat_id, username="analytics-user", storage_backend="postgres")
    store.set_user_plan(chat_id, "pro")
    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = chat_id
        sess["token_version"] = store.get_token_version(chat_id)


def test_user_preferences_rejects_general_budget_below_category_total(client):
    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage

    chat_id = "preferences_budget_minimum"
    _login_analytics_user(client, store, chat_id)
    with store.Session() as session:
        storage = PostgresStorage(session=session, user_id=chat_id)
        storage.create_category("Casa", monthly_budget=300.0)
        storage.create_category("Spesa", monthly_budget=200.0)

    response = client.put("/api/user/preferences", json={"monthly_budget": 400.0})

    assert response.status_code == 400
    assert response.json["error"] == (
        "Il budget mensile generale non puo' essere minore della somma dei budget categoria."
    )


def test_user_preferences_saves_general_monthly_budget(client):
    from src.dashboard.app import store

    chat_id = "preferences_budget_save"
    _login_analytics_user(client, store, chat_id)

    response = client.put("/api/user/preferences", json={"monthly_budget": 650.0})

    assert response.status_code == 200
    assert float(store.get_user_preferences(chat_id)["monthly_budget"]) == 650.0


def test_user_preferences_allows_general_budget_equal_to_active_category_total(client):
    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage

    chat_id = "preferences_budget_equal_minimum"
    _login_analytics_user(client, store, chat_id)
    with store.Session() as session:
        storage = PostgresStorage(session=session, user_id=chat_id)
        storage.create_category("Casa", monthly_budget=300.0)
        archived = storage.create_category("Vecchia", monthly_budget=200.0)
        storage.set_category_archived(archived["id"], True)

    response = client.put("/api/user/preferences", json={"monthly_budget": 300.0})

    assert response.status_code == 200
    assert float(store.get_user_preferences(chat_id)["monthly_budget"]) == 300.0


def test_user_preferences_rejects_non_finite_general_budget(client):
    from src.dashboard.app import store

    chat_id = "preferences_budget_nan"
    _login_analytics_user(client, store, chat_id)

    response = client.put("/api/user/preferences", json={"monthly_budget": "nan"})

    assert response.status_code == 400
    assert response.json["error"] == "monthly_budget deve essere un numero finito"


def test_user_preferences_rejects_infinite_general_budget(client):
    from src.dashboard.app import store

    chat_id = "preferences_budget_infinity"
    _login_analytics_user(client, store, chat_id)

    response = client.put("/api/user/preferences", json={"monthly_budget": "inf"})

    assert response.status_code == 400
    assert response.json["error"] == "monthly_budget deve essere un numero finito"


def test_user_preferences_clears_general_monthly_budget(client):
    from src.dashboard.app import store

    chat_id = "preferences_budget_clear"
    _login_analytics_user(client, store, chat_id)
    assert client.put("/api/user/preferences", json={"monthly_budget": 650.0}).status_code == 200

    response = client.put("/api/user/preferences", json={"monthly_budget": None})

    assert response.status_code == 200
    assert store.get_user_preferences(chat_id)["monthly_budget"] is None


def test_user_preferences_update_does_not_rewrite_onboarding_step(client):
    from src.dashboard.app import store

    chat_id = "preferences_budget_keeps_onboarding"
    _login_analytics_user(client, store, chat_id)
    store.complete_onboarding(chat_id)

    response = client.put("/api/user/preferences", json={"monthly_budget": 650.0})

    assert response.status_code == 200
    assert store.get_user_preferences(chat_id)["onboarding_step"] == "completed"


def _has_demo_data_flag(store, chat_id: str) -> bool:
    from src.user_store import User

    with store.Session() as session:
        user = session.query(User).filter(User.chat_id == chat_id).first()
        return bool(user.has_demo_data)


def test_demo_load_then_clear_round_trip(client):
    # Regressione: l'estrazione in blueprint aveva lasciato le due route su un nome
    # (`_get_storage`) mai importato in privacy_routes.py — un NameError silenzioso,
    # mai catturato da un test perché nessuno esercitava questi due endpoint.
    from src.dashboard.app import store

    chat_id = "demo_data_round_trip"
    store.add_user(chat_id=chat_id, username="demo-user", storage_backend="postgres")
    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = chat_id
        sess["token_version"] = store.get_token_version(chat_id)

    load_response = client.post("/api/demo/load")
    assert load_response.status_code == 200
    assert load_response.json["ok"] is True
    assert load_response.json["expense_count"] > 0
    assert _has_demo_data_flag(store, chat_id) is True

    clear_response = client.post("/api/demo/clear")
    assert clear_response.status_code == 200
    assert clear_response.json["ok"] is True
    assert clear_response.json["deleted"] == load_response.json["expense_count"]
    assert _has_demo_data_flag(store, chat_id) is False


def test_onboarding_completes_without_general_monthly_budget(client):
    from src.dashboard.app import store

    chat_id = "onboarding_without_budget"
    store.add_user(chat_id=chat_id, username="onboarding-user", storage_backend="postgres")
    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = chat_id
        sess["token_version"] = store.get_token_version(chat_id)

    step_response = client.post(
        "/api/onboarding/step",
        json={"step": "notifications", "data": {"notifications_enabled": True}},
    )
    complete_response = client.post("/api/onboarding/complete", json={"hobbies": []})

    preferences = store.get_user_preferences(chat_id)
    assert step_response.status_code == 200
    assert complete_response.status_code == 200
    assert preferences["monthly_budget"] is None
    assert preferences["onboarding_step"] == "completed"


def test_analytics_budget_status_includes_general_monthly_budget(client):
    from src.dashboard.app import store

    chat_id = "analytics_budget_general"
    _login_analytics_user(client, store, chat_id)
    assert client.put("/api/user/preferences", json={"monthly_budget": 900.0}).status_code == 200

    response = client.get("/api/analytics/budget-status")

    assert response.status_code == 200
    assert float(response.json["monthly_budget"]) == 900.0


def test_space_category_create_rejects_budget_that_exceeds_general_budget(client):
    from src.dashboard.app import store

    chat_id = "category_budget_over_general"
    _login_analytics_user(client, store, chat_id)
    csrf_token = client.get("/api/csrf-token").json["csrf_token"]
    assert client.put("/api/user/preferences", json={"monthly_budget": 300.0}).status_code == 200

    response = client.post(
        "/api/space/categories",
        json={"name": "Casa", "monthly_budget": 350.0},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 400
    assert response.json["error"] == (
        "La somma dei budget categoria non puo' superare il budget mensile generale."
    )


def test_space_category_update_rejects_budget_that_exceeds_general_budget(client):
    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage

    chat_id = "category_budget_update_over_general"
    _login_analytics_user(client, store, chat_id)
    csrf_token = client.get("/api/csrf-token").json["csrf_token"]
    assert client.put("/api/user/preferences", json={"monthly_budget": 300.0}).status_code == 200
    with store.Session() as session:
        storage = PostgresStorage(session=session, user_id=chat_id)
        category = storage.create_category("Casa", monthly_budget=200.0)

    response = client.put(
        f"/api/space/categories/{category['id']}",
        json={"monthly_budget": 350.0},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 400
    assert response.json["error"] == (
        "La somma dei budget categoria non puo' superare il budget mensile generale."
    )


def test_space_category_unarchive_rejects_budget_that_exceeds_general_budget(client):
    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage

    chat_id = "category_budget_unarchive_over_general"
    _login_analytics_user(client, store, chat_id)
    csrf_token = client.get("/api/csrf-token").json["csrf_token"]
    assert client.put("/api/user/preferences", json={"monthly_budget": 300.0}).status_code == 200
    with store.Session() as session:
        storage = PostgresStorage(session=session, user_id=chat_id)
        storage.create_category("Casa", monthly_budget=200.0)
        archived = storage.create_category("Extra", monthly_budget=200.0)
        storage.set_category_archived(archived["id"], True)

    response = client.post(
        f"/api/space/categories/{archived['id']}/unarchive",
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 400
    assert response.json["error"] == (
        "La somma dei budget categoria non puo' superare il budget mensile generale."
    )


def test_manage_add_category_rejects_budget_that_exceeds_general_budget(client):
    from src.dashboard.app import store

    chat_id = "manage_add_category_budget_over_general"
    store.add_user(chat_id=chat_id, username="manage-user", storage_backend="postgres")
    reg_token = store.create_oauth_session(chat_id)
    store.update_user_preferences(chat_id, {"monthly_budget": 300.0})

    response = client.post(
        "/api/manage/add",
        json={
            "reg_token": reg_token,
            "entity_type": "category",
            "data": {"name": "Casa", "monthly_budget": 350.0},
        },
    )

    assert response.status_code == 400
    assert response.json["error"] == (
        "La somma dei budget categoria non puo' superare il budget mensile generale."
    )


def test_manage_edit_category_rejects_budget_that_exceeds_general_budget(client):
    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage

    chat_id = "manage_edit_category_budget_over_general"
    store.add_user(chat_id=chat_id, username="manage-user", storage_backend="postgres")
    reg_token = store.create_oauth_session(chat_id)
    store.update_user_preferences(chat_id, {"monthly_budget": 300.0})
    with store.Session() as session:
        storage = PostgresStorage(session=session, user_id=chat_id)
        category = storage.create_category("Casa", monthly_budget=200.0)

    response = client.put(
        "/api/manage/update",
        json={
            "reg_token": reg_token,
            "entity_type": "category",
            "entity_id": category["id"],
            "data": {"monthly_budget": 350.0},
        },
    )

    assert response.status_code == 400
    assert response.json["error"] == (
        "La somma dei budget categoria non puo' superare il budget mensile generale."
    )


def test_categories_expense_yearly_api_aggregates_and_marks_partial(client, monkeypatch):
    from datetime import date

    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage

    _login_analytics_user(client, store, "analytics_categories_yearly")
    monkeypatch.setattr(PostgresStorage, "fetch_all_transactions", lambda self, start, end: [
        {"date": date(2025, 1, 10), "amount": 300.0, "category": "Casa"},
        {"date": date(2025, 2, 10), "amount": 350.0, "category": "Casa"},
        {"date": date(2026, 1, 10), "amount": 650.0, "category": "Casa"},
    ])
    monkeypatch.setattr(PostgresStorage, "get_categories", lambda self, include_archived=True: [])

    response = client.get("/api/analytics/categories-expense?months=24&granularity=yearly")

    assert response.status_code == 200
    row_2026 = next(row for row in response.json["by_category"] if row["period_key"] == "2026")
    assert row_2026["amount"] == 650.0
    assert row_2026["is_partial"] is True


def test_savings_rate_yearly_api_uses_aggregated_income_and_expenses(client, monkeypatch):
    from datetime import date

    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage

    _login_analytics_user(client, store, "analytics_savings_yearly")
    monkeypatch.setattr(PostgresStorage, "fetch_all_transactions", lambda self, start, end: [
        {"date": date(2025, 1, 10), "amount": 600.0},
        {"date": date(2025, 2, 10), "amount": 1200.0},
    ])
    monkeypatch.setattr(PostgresStorage, "fetch_income", lambda self, start, end: [
        {"date": date(2025, 1, 10), "amount": 1000.0},
        {"date": date(2025, 2, 10), "amount": 2000.0},
    ])

    response = client.get("/api/analytics/savings-rate?months=24&granularity=yearly")

    assert response.status_code == 200
    entry = next(row for row in response.json["savings_rate"] if row["period_key"] == "2025")
    assert entry["savings"] == 1200.0
    assert entry["rate"] == 40.0
    assert entry["months_included"] == 2


def test_income_yearly_api_returns_bucket_metadata(client, monkeypatch):
    from datetime import date

    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage

    _login_analytics_user(client, store, "analytics_income_yearly")
    monkeypatch.setattr(PostgresStorage, "fetch_income", lambda self, start, end: [
        {"date": date(2025, 1, 10), "amount": 1000.0},
    ])

    response = client.get("/api/analytics/income?months=24&granularity=yearly")

    assert response.status_code == 200
    assert response.json["monthly"][0]["period_key"] == "2025"


def test_capital_trend_quarterly_uses_last_snapshot_in_each_bucket(client, monkeypatch):
    from datetime import date
    from types import SimpleNamespace

    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage

    _login_analytics_user(client, store, "analytics_capital_quarterly")
    monkeypatch.setattr(PostgresStorage, "fetch_accounts", lambda self: [{
        "id": 1, "name": "Corrente", "opening_balance": 0.0,
    }])
    points = [
        SimpleNamespace(year=2025, month=1, total=100.0, by_account={1: 100.0}),
        SimpleNamespace(year=2025, month=2, total=130.0, by_account={1: 130.0}),
        SimpleNamespace(year=2025, month=4, total=200.0, by_account={1: 200.0}),
    ]
    monkeypatch.setattr(
        "src.wealth.build_wealth_series",
        lambda storage, end, since=None: SimpleNamespace(
            points=points, account_names={1: "Corrente"},
            unassigned_expenses=0.0, unassigned_incomes=0.0,
        ),
    )

    response = client.get("/api/analytics/capital-trend?months=24&granularity=quarterly")

    assert response.status_code == 200
    q1 = next(row for row in response.json["capital_trend"] if row["period_key"] == "2025-Q1")
    assert q1["total"] == 130.0
    assert q1["months_included"] == 2


def test_month_comparison_yearly_compares_previous_and_three_prior_buckets(client, monkeypatch):
    from datetime import date

    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage

    _login_analytics_user(client, store, "analytics_comparison_yearly")

    # Anni relativi a oggi: con anni fissi il test scadrebbe al cambio d'anno.
    current_year = date.today().year
    monkeypatch.setattr(PostgresStorage, "fetch_all_transactions", lambda self, start, end: [
        {"date": date(current_year - 4, 5, 1), "amount": 10.0, "category": "Casa"},
        {"date": date(current_year - 3, 5, 1), "amount": 20.0, "category": "Casa"},
        {"date": date(current_year - 2, 5, 1), "amount": 30.0, "category": "Casa"},
        {"date": date(current_year - 1, 5, 1), "amount": 40.0, "category": "Casa"},
        {"date": date(current_year, 5, 1), "amount": 50.0, "category": "Casa"},
    ])

    response = client.get("/api/analytics/month-comparison?granularity=yearly")

    assert response.status_code == 200
    row = next(item for item in response.json["comparisons"] if item["category"] == "Casa")
    assert row["current_month"] == 50.0
    assert row["last_month"] == 40.0
    assert row["avg_3m"] == 30.0
    assert row["period_key"] == str(current_year)


def test_month_comparison_monthly_keeps_legacy_denominator_for_missing_month(client, monkeypatch):
    from datetime import date

    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage

    _login_analytics_user(client, store, "analytics_comparison_monthly_gap")

    # Date relative al mese corrente: con date fisse il test inizia a fallire da
    # solo quando il calendario avanza (la finestra dei bucket è ancorata a oggi).
    def month_start(months_ago: int) -> date:
        absolute = date.today().year * 12 + date.today().month - 1 - months_ago
        return date(absolute // 12, absolute % 12 + 1, 1)

    monkeypatch.setattr(PostgresStorage, "fetch_all_transactions", lambda self, start, end: [
        {"date": month_start(3), "amount": 20.0, "category": "Casa"},
        {"date": month_start(1), "amount": 10.0, "category": "Casa"},
        {"date": month_start(0), "amount": 40.0, "category": "Casa"},
    ])

    response = client.get("/api/analytics/month-comparison")

    assert response.status_code == 200
    row = next(item for item in response.json["comparisons"] if item["category"] == "Casa")
    assert row["avg_3m"] == 15.0


def test_month_comparison_bucket_context_includes_months_included(client, monkeypatch):
    from datetime import date

    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage

    _login_analytics_user(client, store, "analytics_comparison_metadata")
    monkeypatch.setattr(PostgresStorage, "fetch_all_transactions", lambda self, start, end: [
        {"date": date(2025, 5, 1), "amount": 20.0, "category": "Casa"},
        {"date": date(2026, 5, 1), "amount": 40.0, "category": "Casa"},
    ])

    response = client.get("/api/analytics/month-comparison?granularity=yearly")

    assert response.status_code == 200
    assert response.json["current_bucket"]["months_included"] == 1
    assert response.json["previous_bucket"]["months_included"] == 1
    assert all("months_included" in bucket for bucket in response.json["average_buckets"])


def _create_dashboard_user(store, chat_id="chat_123", email="test@example.com", password="Password123"):
    store.add_user(chat_id=chat_id, username="test-user", storage_backend="postgres")
    store.set_credentials(chat_id, email, password)
    return chat_id, email, password


def _accept_privacy_and_tos(store, chat_id):
    """Fa accettare all'utente privacy policy e ToS nella versione corrente.

    Serve nei test che vogliono superare il gate `/consent` introdotto in
    `_resolve_authenticated_redirect` e verificare il comportamento "post-consenso".
    """
    from config import Config

    store.accept_privacy_policy(chat_id, Config.CURRENT_PRIVACY_POLICY_VERSION)
    store.accept_terms_of_service(chat_id, Config.CURRENT_TOS_VERSION)


def _csrf_token(client):
    """Recupera un token CSRF valido per la sessione corrente del test client.

    enforce_csrf_on_forms() chiama csrf.protect() manualmente, che valida il
    token a prescindere da WTF_CSRF_ENABLED: i test che fanno POST devono quindi
    allegare un token reale come i form/API in produzione.
    """
    return client.get("/api/csrf-token").json["csrf_token"]


def test_web_login_success_redirects_to_setup(client):
    from src.dashboard.app import store

    _, email, password = _create_dashboard_user(store)

    response = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)

    assert response.status_code == 302
    assert "/setup?reg_token=" in response.headers["Location"]


def test_web_login_completed_user_redirects_to_home(client):
    from src.dashboard.app import store

    chat_id, email, password = _create_dashboard_user(
        store,
        chat_id="chat_completed",
        email="completed@example.com",
    )
    store.mark_setup_completed(chat_id)
    store.complete_onboarding(chat_id)
    _accept_privacy_and_tos(store, chat_id)

    response = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/home")


def test_web_login_reactivates_suspended_user(client):
    from src.dashboard.app import store

    chat_id, email, password = _create_dashboard_user(store, chat_id="chat_suspended", email="suspended@example.com")
    store.logout_user(chat_id)

    response = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)

    assert response.status_code == 302
    assert "/setup?reg_token=" in response.headers["Location"]
    assert store.get_user(chat_id) is not None


def test_web_login_invalid_credentials_shows_error(client):
    from src.dashboard.app import store

    _, email, _ = _create_dashboard_user(store, chat_id="chat_invalid", email="invalid@example.com")

    response = client.post("/login", data={"email": email, "password": "wrong-password"}, follow_redirects=False)

    assert response.status_code == 200
    assert b"Email o password errati." in response.data


def test_web_login_notion_user_denied_web_access(client):
    """Un utente con backend Notion non può accedere alla web app dal browser."""
    from src.dashboard.app import store

    chat_id = "chat_notion_login"
    store.add_user(chat_id=chat_id, username="notion-user", storage_backend="notion")
    store.set_credentials(chat_id, "notion-login@example.com", "Password123")

    response = client.post(
        "/login",
        data={
            "email": "notion-login@example.com",
            "password": "Password123",
            "csrf_token": _csrf_token(client),
        },
        follow_redirects=False,
    )

    # Credenziali corrette ma nessuna sessione creata: resta sulla pagina di login.
    assert response.status_code == 200
    assert "collegato a Notion".encode() in response.data
    with client.session_transaction() as sess:
        assert not sess.get("user_logged_in")


def test_web_login_remember_me_creates_persistent_session(client):
    """Con "ricordami" la sessione è permanente e porta la token_version."""
    from src.dashboard.app import store

    _, email, password = _create_dashboard_user(store, chat_id="chat_remember", email="remember@example.com")

    response = client.post(
        "/login",
        data={"email": email, "password": password, "remember": "1", "csrf_token": _csrf_token(client)},
        follow_redirects=False,
    )
    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert sess.get("user_logged_in") is True
        assert sess.permanent is True
        assert sess.get("token_version") == 0


def test_web_login_without_remember_is_browser_session(client):
    """Senza "ricordami" la sessione non è permanente (muore alla chiusura del browser)."""
    from src.dashboard.app import store

    _, email, password = _create_dashboard_user(store, chat_id="chat_noremember", email="noremember@example.com")

    response = client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": _csrf_token(client)},
        follow_redirects=False,
    )
    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert sess.get("user_logged_in") is True
        assert sess.permanent is False


def test_stale_token_version_invalidates_session(client):
    """Bumpando la token_version lato server, la sessione esistente viene revocata."""
    from src.dashboard.app import store

    chat_id, email, password = _create_dashboard_user(
        store, chat_id="chat_revoke", email="revoke@example.com"
    )
    store.mark_setup_completed(chat_id)

    client.post(
        "/login",
        data={"email": email, "password": password, "remember": "1", "csrf_token": _csrf_token(client)},
        follow_redirects=False,
    )
    # La sessione è valida: /app instrada l'utente autenticato (non verso /login).
    assert not client.get("/app", follow_redirects=False).headers["Location"].endswith("/login")

    # Revoca globale delle sessioni.
    store.bump_token_version(chat_id)

    response = client.get("/app", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")
    with client.session_transaction() as sess:
        assert not sess.get("user_logged_in")


def test_logout_all_devices_bumps_token_version_and_clears_session(client):
    from src.dashboard.app import store

    chat_id, email, password = _create_dashboard_user(
        store, chat_id="chat_logoutall", email="logoutall@example.com"
    )
    store.mark_setup_completed(chat_id)
    client.post(
        "/login",
        data={"email": email, "password": password, "remember": "1", "csrf_token": _csrf_token(client)},
        follow_redirects=False,
    )

    response = client.post(
        "/api/settings/logout-all-devices",
        headers={"X-CSRFToken": _csrf_token(client)},
    )
    assert response.status_code == 200
    assert response.json["ok"] is True
    assert store.get_token_version(chat_id) == 1
    with client.session_transaction() as sess:
        assert not sess.get("user_logged_in")


def test_web_app_entry_notion_session_cleared_and_redirected_to_login(client):
    """Una sessione browser residua di un utente Notion viene invalidata su /app."""
    from src.dashboard.app import store

    chat_id = "chat_notion_entry"
    store.add_user(chat_id=chat_id, username="notion-user", storage_backend="notion")
    store.mark_setup_completed(chat_id)
    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = chat_id

    response = client.get("/app", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")
    with client.session_transaction() as sess:
        assert not sess.get("user_logged_in")


def test_api_auth_session_denies_notion_browser_session(client):
    """L'API di sessione considera non autorizzato un utente Notion."""
    from src.dashboard.app import store

    chat_id = "chat_notion_apisession"
    store.add_user(chat_id=chat_id, username="notion-user", storage_backend="notion")
    store.mark_setup_completed(chat_id)
    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = chat_id

    response = client.get("/api/auth/session")

    assert response.status_code == 401
    assert response.json["authorized"] is False


def test_web_login_session_guard_uses_user_logged_in(client):
    from src.dashboard.app import store

    _, email, password = _create_dashboard_user(store, chat_id="chat_guard", email="guard@example.com")

    login_response = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
    assert login_response.status_code == 302

    response = client.get("/login", follow_redirects=False)

    assert response.status_code == 302
    assert "/setup?reg_token=" in response.headers["Location"]


def test_web_login_session_guard_redirects_completed_user_to_home(client):
    from src.dashboard.app import store

    chat_id, email, password = _create_dashboard_user(
        store,
        chat_id="chat_guard_completed",
        email="guard-completed@example.com",
    )
    store.mark_setup_completed(chat_id)
    store.complete_onboarding(chat_id)
    _accept_privacy_and_tos(store, chat_id)

    login_response = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
    assert login_response.status_code == 302

    response = client.get("/login", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/home")


def test_web_app_entry_redirects_anonymous_users_to_login(client):
    response = client.get("/app", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_web_app_entry_redirects_logged_in_users_to_chat(client):
    from src.dashboard.app import store

    _, email, password = _create_dashboard_user(store, chat_id="chat_app_entry", email="app-entry@example.com")

    login_response = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
    assert login_response.status_code == 302

    response = client.get("/app", follow_redirects=False)

    assert response.status_code == 302
    assert "/setup?reg_token=" in response.headers["Location"]


def test_web_app_entry_redirects_completed_users_to_home(client):
    from src.dashboard.app import store

    chat_id, email, password = _create_dashboard_user(
        store,
        chat_id="chat_app_done",
        email="app-done@example.com",
    )
    store.mark_setup_completed(chat_id)
    store.complete_onboarding(chat_id)
    _accept_privacy_and_tos(store, chat_id)

    login_response = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
    assert login_response.status_code == 302

    response = client.get("/app", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/home")


def test_setup_without_token_denies_access_with_generic_message(client):
    response = client.get("/setup", follow_redirects=False)

    assert response.status_code == 403
    assert b"Accesso negato" in response.data
    assert b"Link non valido o sessione non autorizzata." in response.data


def test_api_auth_session_rejects_anonymous_browser_requests(client):
    response = client.get("/api/auth/session")

    assert response.status_code == 401
    assert response.json == {"authorized": False}


def test_api_auth_session_returns_setup_redirect_for_incomplete_browser_session(client):
    from src.dashboard.app import store

    _, email, password = _create_dashboard_user(
        store,
        chat_id="chat_auth_setup",
        email="auth-setup@example.com",
    )

    login_response = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
    assert login_response.status_code == 302

    response = client.get("/api/auth/session")

    assert response.status_code == 200
    assert response.json["authorized"] is True
    assert response.json["auth_mode"] == "browser"
    assert response.json["redirect_to"].startswith("/setup?reg_token=")


def test_api_auth_session_returns_home_for_completed_browser_session(client):
    from src.dashboard.app import store

    chat_id, email, password = _create_dashboard_user(
        store,
        chat_id="chat_auth_done",
        email="auth-done@example.com",
    )
    store.mark_setup_completed(chat_id)
    store.complete_onboarding(chat_id)
    _accept_privacy_and_tos(store, chat_id)

    login_response = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
    assert login_response.status_code == 302

    response = client.get("/api/auth/session")

    assert response.status_code == 200
    assert response.json["authorized"] is True
    assert response.json["auth_mode"] == "browser"
    assert response.json["redirect_to"] is None


def test_api_auth_session_returns_consent_redirect_for_unaccepted_policy_version(client):
    """Setup e onboarding completati ma privacy/tos mai accettati -> gate /consent."""
    from src.dashboard.app import store

    chat_id, email, password = _create_dashboard_user(
        store,
        chat_id="chat_auth_no_consent",
        email="auth-no-consent@example.com",
    )
    store.mark_setup_completed(chat_id)
    store.complete_onboarding(chat_id)
    # privacy_policy_version_accepted e tos_version_accepted restano None: nessuna
    # accept_privacy_policy/accept_terms_of_service e' mai stata chiamata.

    login_response = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
    assert login_response.status_code == 302

    response = client.get("/api/auth/session")

    assert response.status_code == 200
    assert response.json["authorized"] is True
    assert response.json["redirect_to"] == "/consent"


def test_api_auth_session_unblocks_after_accepting_privacy_and_tos(client):
    """Dopo accept-policy + accept-tos il gate /consent si sblocca (no loop)."""
    from src.dashboard.app import store

    chat_id, email, password = _create_dashboard_user(
        store,
        chat_id="chat_auth_consent_given",
        email="auth-consent-given@example.com",
    )
    store.mark_setup_completed(chat_id)
    store.complete_onboarding(chat_id)

    login_response = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
    assert login_response.status_code == 302

    # Prima di accettare, il gate deve bloccare su /consent.
    pre_response = client.get("/api/auth/session")
    assert pre_response.json["redirect_to"] == "/consent"

    csrf_token = client.get("/api/csrf-token").json["csrf_token"]
    accept_policy_response = client.post(
        "/api/privacy/accept-policy",
        headers={"X-CSRFToken": csrf_token},
    )
    assert accept_policy_response.status_code == 200

    accept_tos_response = client.post(
        "/api/privacy/accept-tos",
        headers={"X-CSRFToken": csrf_token},
    )
    assert accept_tos_response.status_code == 200

    response = client.get("/api/auth/session")

    assert response.status_code == 200
    assert response.json["authorized"] is True
    assert response.json["redirect_to"] is None


def test_web_login_next_url_ignored_when_consent_not_accepted(client):
    """`?next=` non deve scavalcare il gate /consent per un utente senza consenso valido."""
    from src.dashboard.app import store

    chat_id, email, password = _create_dashboard_user(
        store,
        chat_id="chat_next_no_consent",
        email="next-no-consent@example.com",
    )
    store.mark_setup_completed(chat_id)
    store.complete_onboarding(chat_id)
    # privacy_policy_version_accepted e tos_version_accepted restano None.

    response = client.post(
        "/login?next=/reports",
        data={"email": email, "password": password},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/consent")
    assert response.headers["Location"] != "/reports"

    # Anche rivisitando /login (già loggato) il gate resta prioritario su next.
    revisit_response = client.get("/login?next=/reports", follow_redirects=False)
    assert revisit_response.status_code == 302
    assert revisit_response.headers["Location"].endswith("/consent")


def test_web_login_next_url_honored_when_all_gates_passed(client):
    """`?next=` viene onorato solo quando l'utente ha gia' superato tutti i gate."""
    from src.dashboard.app import store

    chat_id, email, password = _create_dashboard_user(
        store,
        chat_id="chat_next_all_gates",
        email="next-all-gates@example.com",
    )
    store.mark_setup_completed(chat_id)
    store.complete_onboarding(chat_id)
    _accept_privacy_and_tos(store, chat_id)

    response = client.post(
        "/login?next=/reports",
        data={"email": email, "password": password},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/reports"

    # Rivisitando /login (già loggato) con next, il comportamento è invariato.
    revisit_response = client.get("/login?next=/reports", follow_redirects=False)
    assert revisit_response.status_code == 302
    assert revisit_response.headers["Location"] == "/reports"


def test_browser_session_can_access_reports_api_without_telegram_header(client):
    from src.dashboard.app import store

    chat_id, email, password = _create_dashboard_user(
        store,
        chat_id="chat_reports_browser",
        email="reports-browser@example.com",
    )
    store.mark_setup_completed(chat_id)

    login_response = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
    assert login_response.status_code == 302

    response = client.get("/api/reports")

    assert response.status_code == 200
    assert response.json == {"reports": [], "plan_type": "free"}


def _save_report(store, chat_id, share_token="tok-123", report_type="weekly"):
    from datetime import date
    from src.storage.postgres_storage import PostgresStorage

    with store.Session() as s:
        storage = PostgresStorage(session=s, user_id=chat_id)
        storage.save_report(
            user_id=chat_id,
            report_type=report_type,
            report_date=date.today(),
            text_content="Report di prova",
            report_data=None,
        )
        # save_report genera un token proprio: lo leggiamo per rendere il test
        # deterministico rispetto al token atteso dal chiamante.
        saved = storage.get_reports_for_user(user_id=chat_id, limit=1)[0]
        return saved["share_token"]


def test_report_detail_requires_auth(client):
    response = client.get("/api/reports/some-token")
    assert response.status_code == 401


def test_report_detail_returns_404_for_other_users_report(client):
    from src.dashboard.app import store

    owner_chat_id, _, _ = _create_dashboard_user(
        store, chat_id="chat_report_owner", email="owner@example.com"
    )
    token = _save_report(store, owner_chat_id)

    _, other_email, other_password = _create_dashboard_user(
        store, chat_id="chat_report_other", email="other@example.com"
    )
    store.mark_setup_completed("chat_report_other")
    client.post("/login", data={"email": other_email, "password": other_password})

    response = client.get(f"/api/reports/{token}")

    assert response.status_code == 404


def test_report_detail_returns_report_for_owner(client):
    from src.dashboard.app import store

    owner_chat_id, email, password = _create_dashboard_user(
        store, chat_id="chat_report_self", email="self@example.com"
    )
    store.mark_setup_completed(owner_chat_id)
    token = _save_report(store, owner_chat_id)

    client.post("/login", data={"email": email, "password": password})
    response = client.get(f"/api/reports/{token}")

    assert response.status_code == 200
    assert response.json["share_token"] == token
    assert response.json["text_content"] == "Report di prova"


def test_telegram_login_template_has_mobile_keyboard_guards(client):
    from src.dashboard.app import store

    state = store.create_oauth_session("chat_keyboard")
    response = client.get(f"/auth/telegram-login?state={state}")

    html = response.get_data(as_text=True)

    assert response.status_code == 200
    # Niente type="email" né inputmode="email": su Telegram WebApp Android quella
    # tastiera nasconde la @ (vedi commento in templates/telegram_login.html).
    assert 'inputmode="email"' not in html
    assert 'type="email"' not in html
    assert r'pattern="[^@\s]+@[^@\s]+\.[^@\s]+"' in html
    assert 'autocapitalize="none"' in html
    assert 'autocorrect="off"' in html
    assert 'spellcheck="false"' in html
    assert 'enterkeyhint="next"' in html
    assert 'enterkeyhint="go"' in html

def test_telegram_login_reassigns_account_to_new_chat_id(client, monkeypatch):
    from src.dashboard.app import store

    # La route arruola la riassegnazione in coda e attende (polling) il worker fuori
    # banda (scripts/process_reassignment_jobs.py) — vedi
    # UserStore.enqueue_chat_id_reassignment/wait_for_reassignment_job. Nessun worker
    # gira nei test: si simula il suo turno eseguendo la coda al posto dello sleep.
    monkeypatch.setattr(
        "src.user_store.time.sleep",
        lambda _: store.process_pending_reassignment_jobs(),
    )

    old_chat_id, email, password = _create_dashboard_user(
        store,
        chat_id="old_chat_123",
        email="telegram-rebind@example.com",
    )
    state = store.create_oauth_session("new_chat_456")

    response = client.post(
        "/auth/telegram-login",
        data={"state": state, "email": email, "password": password},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert b"Accesso effettuato" in response.data
    assert store.get_user_any_status(old_chat_id) is None

    rebound_user = store.get_user("new_chat_456")
    assert rebound_user is not None
    assert rebound_user.email == email
    assert store.get_and_delete_oauth_session(state) is None

def test_dashboard_home_page_redirects(client):
    """Verifica che la home admin (/admin/) ridiriga al login se non autenticato."""
    response = client.get("/admin/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]

def test_oauth_callback_error_no_code(client):
    """Verifica errore se si chiama la callback Notion senza parametri."""
    response = client.get("/auth/notion/callback")
    assert response.status_code == 400
    assert b"Parametri mancanti" in response.data

@patch("src.dashboard.blueprints.auth_routes.threading.Thread")
@patch("src.dashboard.blueprints.auth_routes.requests.post")
@patch("src.user_store.UserStore.get_and_delete_oauth_session")
def test_oauth_callback_success(mock_get_sess, mock_post, mock_thread, client):
    """Verifica che la callback OAuth sincrona risponda 302 e avvii il thread di setup.

    Il discovery (add_user, discover_databases…) avviene in background: questo test
    verifica solo la parte sincrona — scambio token + redirect + avvio thread.
    """
    mock_get_sess.return_value = "chat_123"

    # Mock scambio token Notion
    mock_post.return_value.ok = True
    mock_post.return_value.json.return_value = {
        "access_token": "ntn_access_token",
        "workspace_id": "ws_123",
        "duplicated_template_id": "tpl_456",
    }

    # Mock del thread: evita che parta davvero
    mock_thread_instance = MagicMock()
    mock_thread.return_value = mock_thread_instance

    response = client.get("/auth/notion/callback?code=notion_code&state=RT-magic_token")

    # La route risponde sempre con 302 → redirect verso t.me (setup in background)
    assert response.status_code == 302
    assert "t.me" in response.headers["Location"]

    # Verifica che il thread background sia stato avviato
    mock_thread.assert_called_once()
    mock_thread_instance.start.assert_called_once()


def test_login_brute_force_returns_429_after_threshold(client):
    """Verifica che dopo 5 tentativi falliti /login risponda 429 (brute-force protection)."""
    from src.dashboard.app import store, limiter

    _create_dashboard_user(store, chat_id="chat_bf", email="bf@example.com")

    # Svuota il storage del limiter tra i test
    limiter.reset()

    for _ in range(5):
        client.post("/login", data={"email": "bf@example.com", "password": "wrong"})

    response = client.post("/login", data={"email": "bf@example.com", "password": "wrong"})
    assert response.status_code == 429


def _login_completed(client, store, chat_id, email, storage_backend="postgres"):
    """Crea un utente con setup completato e ne simula la sessione browser.

    Usa session_transaction invece di POST /login: il flusso /login reale
    richiede un token CSRF che esula dallo scope dei test sugli endpoint
    privacy (l'autenticazione è già coperta da test_web_login_*).
    """
    store.add_user(chat_id=chat_id, username="test-user", storage_backend=storage_backend)
    store.set_credentials(chat_id, email, "Password123")
    store.mark_setup_completed(chat_id)
    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = chat_id
        # La sessione deve portare la token_version corrente, altrimenti
        # _get_session_chat_id la considera revocata (vedi meccanismo "ricordami").
        sess["token_version"] = store.get_token_version(chat_id)


def test_privacy_export_json_requires_auth(client):
    response = client.get("/api/privacy/export-json")
    assert response.status_code == 401


def test_privacy_export_json_excludes_secrets_and_includes_financial_data(client):
    from src.storage.models import Account, Expense, Income, UserIncomeCategory
    from datetime import date

    from src.dashboard.app import store

    chat_id, email = "chat_privacy_json", "privacy-json@example.com"
    _login_completed(client, store, chat_id, email)

    with store.Session() as s:
        account = Account(user_id=chat_id, name="Conto Test", opening_balance=100)
        s.add(account)
        s.commit()
        s.add(Expense(
            user_id=chat_id, expense_date=date.today(), amount=10, name="Caffè",
            account_id=account.id,
        ))
        income_category = UserIncomeCategory(user_id=chat_id, name="Consulenza")
        s.add(income_category)
        s.flush()
        s.add(Income(
            user_id=chat_id, income_date=date.today(), amount=150, name="Cliente",
            account_id=account.id, income_type="Consulenza", income_category_id=income_category.id,
        ))
        s.commit()

    response = client.get("/api/privacy/export-json")

    assert response.status_code == 200
    body = response.json
    assert body["account"]["email"] == email
    assert "password_hash" not in body["account"]
    assert "notion_access_token" not in body["account"]
    assert len(body["financial_data"]["expenses"]) == 1
    assert body["financial_data"]["expenses"][0]["name"] == "Caffè"
    assert any(row["name"] == "Consulenza" for row in body["financial_data"]["income_categories"])
    assert body["financial_data"]["incomes"][0]["income_category"] == "Consulenza"
    assert "your_rights" in body

    with store.Session() as s:
        from src.user_store import AuditLog
        log = s.query(AuditLog).filter_by(user_id=chat_id, action="export_json").first()
        assert log is not None


def test_privacy_export_json_notion_backend_denied_web_access(client):
    """Gli account Notion non hanno accesso alla web app: l'endpoint risponde 401.

    L'export GDPR (Art. 15/20) per gli utenti Notion avviene via bot Telegram
    (comando /export), non dalla web app riservata al backend PostgreSQL.
    """
    from src.dashboard.app import store

    chat_id, email = "chat_privacy_json_notion", "privacy-json-notion@example.com"
    _login_completed(client, store, chat_id, email, storage_backend="notion")

    response = client.get("/api/privacy/export-json")

    assert response.status_code == 401


def test_privacy_export_json_includes_consent_versions_and_timestamps(client):
    """L'export Art. 15 GDPR include il consenso privacy/ToS accettato dall'utente.

    Aggiunto dopo una review che aveva trovato l'export incompleto rispetto ai
    dati di consenso già tracciati su `User` (`privacy_policy_version_accepted`,
    `tos_version_accepted` e relativi timestamp).
    """
    from config import Config
    from src.dashboard.app import store

    chat_id, email = "chat_privacy_json_consent", "privacy-json-consent@example.com"
    _login_completed(client, store, chat_id, email)
    store.accept_privacy_policy(chat_id, Config.CURRENT_PRIVACY_POLICY_VERSION)
    store.accept_terms_of_service(chat_id, Config.CURRENT_TOS_VERSION)

    response = client.get("/api/privacy/export-json")

    assert response.status_code == 200
    account = response.json["account"]
    assert account["privacy_policy_version_accepted"] == Config.CURRENT_PRIVACY_POLICY_VERSION
    assert account["tos_version_accepted"] == Config.CURRENT_TOS_VERSION
    assert account["privacy_accepted_at"] is not None
    assert account["tos_accepted_at"] is not None


def test_privacy_export_csv_requires_auth(client):
    response = client.get("/api/privacy/export-csv")
    assert response.status_code == 401


def test_privacy_export_csv_returns_csv_for_postgres_user(client):
    from src.storage.models import Account, Expense
    from datetime import date

    from src.dashboard.app import store

    chat_id, email = "chat_privacy_csv", "privacy-csv@example.com"
    _login_completed(client, store, chat_id, email)

    with store.Session() as s:
        account = Account(user_id=chat_id, name="Conto Test", opening_balance=0)
        s.add(account)
        s.commit()
        s.add(Expense(
            user_id=chat_id, expense_date=date.today(), amount=5, name="Pranzo",
            account_id=account.id,
        ))
        s.commit()

    response = client.get("/api/privacy/export-csv")

    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    csv_text = response.get_data(as_text=True)
    assert "Pranzo" in csv_text
    assert "monthly_balance" not in csv_text.lower()


def test_privacy_export_csv_notion_backend_denied_web_access(client):
    """Gli account Notion non hanno accesso alla web app: l'endpoint risponde 401."""
    from src.dashboard.app import store

    chat_id, email = "chat_privacy_csv_notion", "privacy-csv-notion@example.com"
    _login_completed(client, store, chat_id, email, storage_backend="notion")

    response = client.get("/api/privacy/export-csv")

    assert response.status_code == 401


def test_privacy_delete_account_writes_audit_log_before_deletion(client):
    from src.dashboard.app import store
    from src.user_store import AuditLog

    chat_id, email = "chat_privacy_delete", "privacy-delete@example.com"
    _login_completed(client, store, chat_id, email)

    csrf_token = client.get("/api/csrf-token").json["csrf_token"]
    response = client.post(
        "/api/privacy/delete-account",
        json={"confirm": "DELETE"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 200
    assert response.json["ok"] is True
    assert store.get_user(chat_id) is None

    with store.Session() as s:
        log = s.query(AuditLog).filter_by(user_id=chat_id, action="delete_account").first()
        assert log is not None


def test_change_name_writes_audit_log_and_updates_name(client):
    from src.dashboard.app import store
    from src.user_store import AuditLog

    chat_id, email = "chat_change_name", "change-name@example.com"
    _login_completed(client, store, chat_id, email)

    csrf_token = client.get("/api/csrf-token").json["csrf_token"]
    response = client.post(
        "/api/settings/change-name",
        json={"first_name": "Mario", "last_name": "Rossi"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 200
    assert response.json["ok"] is True
    assert store.get_user(chat_id).username == "Mario Rossi"

    with store.Session() as s:
        log = s.query(AuditLog).filter_by(user_id=chat_id, action="change_name").first()
        assert log is not None


def test_change_name_rejects_empty_name(client):
    from src.dashboard.app import store

    chat_id, email = "chat_change_name_empty", "change-name-empty@example.com"
    _login_completed(client, store, chat_id, email)

    csrf_token = client.get("/api/csrf-token").json["csrf_token"]
    response = client.post(
        "/api/settings/change-name",
        json={"first_name": "", "last_name": "Rossi"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 400


def test_change_email_writes_audit_log_and_updates_email(client):
    from src.dashboard.app import store
    from src.user_store import AuditLog

    chat_id, email = "chat_change_email", "change-email@example.com"
    _login_completed(client, store, chat_id, email)

    csrf_token = client.get("/api/csrf-token").json["csrf_token"]
    response = client.post(
        "/api/settings/change-email",
        json={"new_email": "new-email@example.com", "current_password": "Password123"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 200
    assert response.json["ok"] is True
    assert store.get_user(chat_id).email == "new-email@example.com"

    with store.Session() as s:
        log = s.query(AuditLog).filter_by(user_id=chat_id, action="change_email").first()
        assert log is not None


def test_change_email_rejects_wrong_current_password(client):
    from src.dashboard.app import store

    chat_id, email = "chat_change_email_wrong", "change-email-wrong@example.com"
    _login_completed(client, store, chat_id, email)

    csrf_token = client.get("/api/csrf-token").json["csrf_token"]
    response = client.post(
        "/api/settings/change-email",
        json={"new_email": "new-email-2@example.com", "current_password": "WrongPassword"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 401
    assert store.get_user(chat_id).email == email


def test_change_password_writes_audit_log_and_updates_password(client):
    from src.dashboard.app import store
    from src.user_store import AuditLog

    chat_id, email = "chat_change_password", "change-password@example.com"
    _login_completed(client, store, chat_id, email)

    csrf_token = client.get("/api/csrf-token").json["csrf_token"]
    response = client.post(
        "/api/settings/change-password",
        json={"current_password": "Password123", "new_password": "NewPassword456"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 200
    assert response.json["ok"] is True
    assert store.verify_password(email, "NewPassword456") is not None

    with store.Session() as s:
        log = s.query(AuditLog).filter_by(user_id=chat_id, action="change_password").first()
        assert log is not None


def test_accept_privacy_policy_writes_audit_log(client):
    from src.dashboard.app import store
    from src.user_store import AuditLog
    from config import Config

    chat_id, email = "chat_accept_policy", "accept-policy@example.com"
    _login_completed(client, store, chat_id, email)

    csrf_token = client.get("/api/csrf-token").json["csrf_token"]
    response = client.post(
        "/api/privacy/accept-policy",
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 200
    assert response.json["privacy_policy_version_accepted"] == Config.CURRENT_PRIVACY_POLICY_VERSION

    with store.Session() as s:
        log = s.query(AuditLog).filter_by(user_id=chat_id, action="consent_change").first()
        assert log is not None


def test_accept_tos_writes_audit_log(client):
    from src.dashboard.app import store
    from src.user_store import AuditLog
    from config import Config

    chat_id, email = "chat_accept_tos", "accept-tos@example.com"
    _login_completed(client, store, chat_id, email)

    csrf_token = client.get("/api/csrf-token").json["csrf_token"]
    response = client.post(
        "/api/privacy/accept-tos",
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 200
    assert response.json["tos_version_accepted"] == Config.CURRENT_TOS_VERSION

    with store.Session() as s:
        log = (
            s.query(AuditLog)
            .filter_by(user_id=chat_id, action="consent_change")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert log is not None


def test_terms_of_service_route_redirects_to_frontend(client):
    from config import Config

    response = client.get("/terms", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"] == f"{Config.WEBAPP_BASE_URL}/it/terms"


def test_web_register_requires_both_consent_checkboxes(client, monkeypatch):
    """Senza privacy_accepted E tos_accepted, /register non crea l'utente."""
    from src.dashboard.app import store
    from config import Config

    monkeypatch.setattr(Config, "PUBLIC_REGISTRATION_ENABLED", True)
    email = "missing-consent@example.com"

    response = client.post(
        "/register",
        data={
            "first_name": "Mario",
            "last_name": "Rossi",
            "email": email,
            "password": "Password123",
            "password_confirm": "Password123",
            "privacy_accepted": "on",
            # tos_accepted mancante
        },
    )

    assert response.status_code == 200
    assert b"privacy policy e termini di servizio" in response.data
    assert store.get_user_by_email(email) is None


def test_web_register_with_both_checkboxes_creates_user_with_consents(client, monkeypatch):
    """Con entrambe le checkbox, l'utente viene creato con privacy e ToS accettati."""
    from src.dashboard.app import store
    from config import Config

    monkeypatch.setattr(Config, "PUBLIC_REGISTRATION_ENABLED", True)
    email = "full-consent@example.com"

    response = client.post(
        "/register",
        data={
            "first_name": "Mario",
            "last_name": "Rossi",
            "email": email,
            "password": "Password123",
            "password_confirm": "Password123",
            "privacy_accepted": "on",
            "tos_accepted": "on",
        },
    )

    assert response.status_code in (302, 200)
    user = store.get_user_by_email(email)
    assert user is not None
    assert user.privacy_policy_version_accepted == Config.CURRENT_PRIVACY_POLICY_VERSION
    assert user.tos_version_accepted == Config.CURRENT_TOS_VERSION

    # Non-regressione: consenso dato in fase di registrazione -> nessun redirect /consent
    # per un utente appena creato (setup completato, onboarding no).
    session_response = client.get("/api/auth/session")
    assert session_response.json["redirect_to"] != "/consent"


def test_auth_postgres_start_requires_both_consent_checkboxes(client):
    """Senza le due checkbox di consenso, /auth/postgres non consuma il reg_token né crea l'utente."""
    from src.dashboard.app import store

    chat_id = "tg_postgres_missing_consent"
    reg_token = store.create_oauth_session(chat_id)

    response = client.post(
        "/auth/postgres",
        data={
            "reg_token": reg_token,
            "email": "postgres-missing-consent@example.com",
            "password": "Password123",
            "password2": "Password123",
            "tos_accepted": "on",
            # privacy_accepted mancante
        },
    )

    assert response.status_code == 200
    assert b"privacy policy e termini di servizio" in response.data
    assert store.get_user_by_email("postgres-missing-consent@example.com") is None
    # Il reg_token non è stato consumato: resta valido.
    assert store.get_and_delete_oauth_session(reg_token) == chat_id


@patch("src.dashboard.blueprints.auth_routes.threading.Thread")
@patch("src.dashboard.blueprints.auth_routes.requests.post")
def test_auth_postgres_start_with_both_checkboxes_creates_user_with_consents(
    mock_post, mock_thread, client
):
    """Con entrambe le checkbox, /auth/postgres crea l'utente con privacy e ToS accettati."""
    from src.dashboard.app import store
    from config import Config

    mock_thread.return_value = MagicMock()

    chat_id = "tg_postgres_full_consent"
    reg_token = store.create_oauth_session(chat_id)
    email = "postgres-full-consent@example.com"

    response = client.post(
        "/auth/postgres",
        data={
            "reg_token": reg_token,
            "email": email,
            "password": "Password123",
            "password2": "Password123",
            "privacy_accepted": "on",
            "tos_accepted": "on",
        },
    )

    assert response.status_code == 302
    user = store.get_user_by_email(email)
    assert user is not None
    assert user.chat_id == chat_id
    assert user.privacy_policy_version_accepted == Config.CURRENT_PRIVACY_POLICY_VERSION
    assert user.tos_version_accepted == Config.CURRENT_TOS_VERSION


def test_login_breach_detection_after_repeated_failures(client):
    from src.dashboard.app import store
    from src.user_store import AuditLog
    from src.rate_limiter import reset_failed_logins

    email = "breach-detect@example.com"
    store.add_user(chat_id="chat_breach_detect", username="breach-user")
    store.set_credentials("chat_breach_detect", email, "Password123")
    reset_failed_logins(email)

    csrf_token = client.get("/api/csrf-token").json["csrf_token"]
    for _ in range(5):
        client.post(
            "/login",
            data={"email": email, "password": "WrongPassword"},
            headers={"X-CSRFToken": csrf_token},
        )

    with store.Session() as s:
        log = s.query(AuditLog).filter_by(user_id=email, action="breach_detection").first()
        assert log is not None


def test_login_lockout_persists_across_different_ips(client):
    """OWASP A07: il lockout per-account non deve essere bypassabile ruotando IP.

    Il rate limit di flask_limiter su /login è per-IP (5/min): un attaccante
    che ruota IP ad ogni tentativo lo bypassa banalmente. Il lockout per-email
    (ACCOUNT_LOCKOUT_THRESHOLD in app.py) deve invece contare i fallimenti
    sull'account indipendentemente dall'IP di provenienza.
    """
    from src.dashboard.app import store
    from src.rate_limiter import reset_failed_logins

    _, email, password = _create_dashboard_user(
        store, chat_id="chat_lockout", email="lockout@example.com"
    )
    reset_failed_logins(email)

    csrf_token = client.get("/api/csrf-token").json["csrf_token"]

    # 5 tentativi falliti, ognuno da un IP diverso: nessuno tocca il limite
    # per-IP di flask_limiter, ma il lockout per-account deve comunque scattare.
    for i in range(5):
        response = client.post(
            "/login",
            data={"email": email, "password": "wrong"},
            headers={"X-CSRFToken": csrf_token},
            environ_overrides={"REMOTE_ADDR": f"10.0.0.{i}"},
        )
        assert response.status_code == 200

    # Sesto tentativo, da un IP mai visto prima, con la password CORRETTA:
    # deve comunque fallire per via del lockout sull'account.
    response = client.post(
        "/login",
        data={"email": email, "password": password},
        headers={"X-CSRFToken": csrf_token},
        environ_overrides={"REMOTE_ADDR": "10.0.0.99"},
    )
    assert response.status_code == 200
    assert b"Troppi tentativi falliti" in response.data

    with client.session_transaction() as sess:
        assert "user_logged_in" not in sess


def test_admin_login_locks_out_after_threshold_failures(client):
    """OWASP A07: /admin/login usa una password singola condivisa senza lockout
    dedicato prima di questo fix — un attaccante poteva tentare brute force
    illimitato oltre il rate limit generico. Verifica che dopo 5 fallimenti
    anche la password corretta venga rifiutata.
    """
    from config import Config
    from src.rate_limiter import reset_failed_logins
    from src.dashboard.blueprints.auth_routes import ADMIN_LOCKOUT_KEY

    reset_failed_logins(ADMIN_LOCKOUT_KEY)
    csrf_token = client.get("/api/csrf-token").json["csrf_token"]

    with patch.object(Config, "DASHBOARD_PASSWORD", "correct-admin-password"):
        for _ in range(5):
            client.post(
                "/admin/login", data={"password": "wrong"},
                headers={"X-CSRFToken": csrf_token},
            )

        response = client.post(
            "/admin/login", data={"password": "correct-admin-password"},
            headers={"X-CSRFToken": csrf_token},
        )

    assert response.status_code == 200
    assert b"Troppi tentativi falliti" in response.data
    with client.session_transaction() as sess:
        assert "admin_logged_in" not in sess


def test_admin_login_lockout_persists_across_different_ips(client):
    """Come test_login_lockout_persists_across_different_ips ma per /admin/login:
    il lockout non deve essere per-IP (bypassabile ruotando IP), ma sull'unico
    account admin.
    """
    from config import Config
    from src.rate_limiter import reset_failed_logins
    from src.dashboard.blueprints.auth_routes import ADMIN_LOCKOUT_KEY

    reset_failed_logins(ADMIN_LOCKOUT_KEY)
    csrf_token = client.get("/api/csrf-token").json["csrf_token"]

    with patch.object(Config, "DASHBOARD_PASSWORD", "correct-admin-password"):
        for i in range(5):
            response = client.post(
                "/admin/login",
                data={"password": "wrong"},
                headers={"X-CSRFToken": csrf_token},
                environ_overrides={"REMOTE_ADDR": f"10.0.1.{i}"},
            )
            assert response.status_code == 200

        response = client.post(
            "/admin/login",
            data={"password": "correct-admin-password"},
            headers={"X-CSRFToken": csrf_token},
            environ_overrides={"REMOTE_ADDR": "10.0.1.99"},
        )

    assert response.status_code == 200
    assert b"Troppi tentativi falliti" in response.data
    with client.session_transaction() as sess:
        assert "admin_logged_in" not in sess


def test_safe_next_url_rejects_external_and_protocol_relative_urls():
    """OWASP A10: _safe_next_url e' l'unico punto della dashboard dove un valore
    quasi-URL arriva da querystring/form. Deve accettare solo path relativi
    interni, mai host esterni (open redirect, imparentato con SSRF).
    """
    from src.dashboard.blueprints.auth_routes import _safe_next_url

    assert _safe_next_url("/reports") == "/reports"
    assert _safe_next_url(None) is None
    assert _safe_next_url("") is None
    assert _safe_next_url("https://evil.com") is None
    assert _safe_next_url("http://evil.com/phish") is None
    assert _safe_next_url("//evil.com") is None
    assert _safe_next_url("//evil.com/path") is None
    assert _safe_next_url("javascript:alert(1)") is None


def test_login_redirect_ignores_external_next_param(client):
    """Full-stack: /login?next=<host esterno> non deve reindirizzare l'utente
    autenticato fuori dal dominio, nonostante il redirect a valle di un login
    riuscito."""
    from src.dashboard.app import store

    _, email, password = _create_dashboard_user(
        store, chat_id="chat_next_ssrf", email="next-ssrf@example.com"
    )
    csrf_token = client.get("/api/csrf-token").json["csrf_token"]

    response = client.post(
        "/login?next=https://evil.com/steal",
        data={"email": email, "password": password},
        headers={"X-CSRFToken": csrf_token},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "evil.com" not in response.headers["Location"]


def test_brevo_contact_request_target_is_fixed_host_regardless_of_payload():
    """OWASP A10: l'unica chiamata outbound che incorpora dati esterni (il lead
    Tally) deve sempre puntare all'host Brevo fisso, mai a un host derivato
    dal payload attaccante-controllato (es. un'email che assomiglia a un URL
    interno/gopher usata per tentare SSRF verso rete interna)."""
    from src import brevo_client

    malicious_emails = [
        "attacker@evil.com#@internal-service:8080/",
        "http://169.254.169.254/latest/meta-data/@example.com",
        "gopher://127.0.0.1:6379/_INFO@example.com",
    ]

    with patch("src.brevo_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=201)
        with patch.object(brevo_client.Config, "BREVO_API_KEY", "test-key"):
            for email in malicious_emails:
                brevo_client.upsert_contact(email, list_ids=[1])

    assert mock_post.call_count == len(malicious_emails)
    for call in mock_post.call_args_list:
        assert call.args[0] == "https://api.brevo.com/v3/contacts"


def test_session_authenticated_api_requires_csrf_token(app, client):
    """Verifica che le rotte /api/* autenticate via cookie di sessione siano protette da CSRF.

    Il fixture 'app' disabilita WTF_CSRF_ENABLED di default (altrimenti tutti i test
    POST esistenti dovrebbero allegare un token); qui lo riattiviamo apposta per
    provare che enforce_csrf_on_forms() blocchi davvero le richieste senza token,
    e le accetti con un token valido recuperato da /api/csrf-token.
    """
    from src.dashboard.app import store

    chat_id, email = "chat_csrf_test", "csrf-test@example.com"
    _login_completed(client, store, chat_id, email)

    app.config["WTF_CSRF_ENABLED"] = True
    try:
        # Senza token CSRF: la richiesta deve essere rifiutata.
        response = client.post("/api/settings/logout")
        assert response.status_code == 400

        # Con un token valido recuperato dall'endpoint dedicato: la richiesta passa.
        token_response = client.get("/api/csrf-token")
        assert token_response.status_code == 200
        csrf_token = token_response.json["csrf_token"]

        response = client.post(
            "/api/settings/logout",
            headers={"X-CSRFToken": csrf_token},
        )
        assert response.status_code == 200
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_telegram_init_data_api_exempt_from_csrf(client):
    """Le rotte /api/* con header X-Telegram-Init-Data restano esenti da CSRF.

    Un sito malevolo non può impostare header custom su richieste cross-origin,
    quindi questo canale di autenticazione non è sfruttabile da CSRF — non ha
    senso richiedere anche un token in questo caso.
    """
    from src.dashboard.app import app as flask_app

    flask_app.config["WTF_CSRF_ENABLED"] = True
    try:
        response = flask_app.test_client().post(
            "/api/chat/message",
            json={"text": "test"},
            headers={"X-Telegram-Init-Data": "user=invalid"},
        )
        # L'header presente esenta dal controllo CSRF: il prossimo errore (401, dati
        # non validi) è atteso, ma NON deve essere il 400 di CSRFProtect.
        assert response.status_code != 400
    finally:
        flask_app.config["WTF_CSRF_ENABLED"] = False


def test_telegram_link_requires_auth(client):
    csrf_token = client.get("/api/csrf-token").json["csrf_token"]
    response = client.post("/api/telegram/link", headers={"X-CSRFToken": csrf_token})
    assert response.status_code == 401


def test_telegram_link_already_linked_for_telegram_chat_id(client):
    from src.dashboard.app import store

    _login_completed(client, store, "chat_already_telegram", "already-telegram@example.com")

    csrf_token = client.get("/api/csrf-token").json["csrf_token"]
    response = client.post("/api/telegram/link", headers={"X-CSRFToken": csrf_token})

    assert response.status_code == 200
    assert response.json == {"already_linked": True}


def test_telegram_link_generates_deep_link_for_web_chat_id(client):
    from config import Config
    from src.dashboard.app import store

    _login_completed(client, store, "web_test123", "web-link@example.com")

    csrf_token = client.get("/api/csrf-token").json["csrf_token"]
    with patch.object(Config, "TELEGRAM_BOT_USERNAME", "expensum_test_bot"):
        response = client.post("/api/telegram/link", headers={"X-CSRFToken": csrf_token})

    assert response.status_code == 200
    body = response.json
    assert body["already_linked"] is False
    assert body["link"].startswith("https://t.me/expensum_test_bot?start=link_")

    state = body["link"].split("start=link_", 1)[1]
    assert store.get_and_delete_oauth_session(state) == "web_test123"


def test_telegram_link_returns_500_without_bot_username(client):
    from config import Config
    from src.dashboard.app import store

    _login_completed(client, store, "web_test456", "web-link-2@example.com")

    csrf_token = client.get("/api/csrf-token").json["csrf_token"]
    with patch.object(Config, "TELEGRAM_BOT_USERNAME", ""):
        response = client.post("/api/telegram/link", headers={"X-CSRFToken": csrf_token})

    assert response.status_code == 500


def test_idor_account_and_expense_scoped_by_user(client):
    """OWASP A01: un utente autenticato non deve poter leggere/modificare/cancellare
    risorse (conti, spese) di un altro utente tramite /api/space/*, anche
    conoscendone l'id — lo scoping deve avvenire lato server, non fidarsi del client.
    """
    from datetime import date
    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage

    store.add_user(chat_id="chat_user_a", username="user-a", storage_backend="postgres")
    store.add_user(chat_id="chat_user_b", username="user-b", storage_backend="postgres")

    # Seed diretto via storage layer: un conto e una spesa di proprietà di B.
    with store.Session() as s:
        pg_b = PostgresStorage(session=s, user_id="chat_user_b")
        account_b = pg_b.create_account("Conto di B", initial_balance=100.0)
        expense_b = pg_b.create_expense(
            expense_date=date(2026, 1, 1), amount=42.0, name="Spesa di B",
            category_name="", account_id=account_b["id"],
        )

    csrf_token = client.get("/api/csrf-token").json["csrf_token"]

    # A si autentica (sessione browser). token_version deve combaciare con quello
    # persistito, altrimenti _get_session_chat_id la considera revocata (401 invece
    # del 404 atteso per lo scoping IDOR).
    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = "chat_user_a"
        sess["token_version"] = store.get_token_version("chat_user_a")

    # A prova a modificare/cancellare il conto di B
    resp = client.put(
        f"/api/space/accounts/{account_b['id']}",
        json={"name": "Hacked"},
        headers={"X-CSRFToken": csrf_token},
    )
    assert resp.status_code == 404
    resp = client.delete(
        f"/api/space/accounts/{account_b['id']}",
        headers={"X-CSRFToken": csrf_token},
    )
    assert resp.status_code == 404

    # A prova a modificare/cancellare la spesa di B
    resp = client.put(
        f"/api/space/expenses/{expense_b['id']}",
        json={"name": "Hacked expense"},
        headers={"X-CSRFToken": csrf_token},
    )
    assert resp.status_code == 404
    resp = client.delete(
        f"/api/space/expenses/{expense_b['id']}",
        headers={"X-CSRFToken": csrf_token},
    )
    assert resp.status_code == 404

    # A elenca i propri conti: quello di B non deve comparire
    resp = client.get("/api/space/accounts")
    assert resp.status_code == 200
    assert account_b["id"] not in [a["id"] for a in resp.json["accounts"]]

    # Il conto e la spesa di B devono restare intatti nonostante i tentativi
    from src.storage.models import Expense as ExpenseModel

    with store.Session() as s:
        pg_b = PostgresStorage(session=s, user_id="chat_user_b")
        accounts_b = pg_b.fetch_accounts()
        assert any(
            a["id"] == account_b["id"] and a["name"] == "Conto di B" for a in accounts_b
        )
        expense_row = s.query(ExpenseModel).filter_by(id=expense_b["id"]).first()
        assert expense_row is not None
        assert expense_row.name == "Spesa di B"
        assert expense_row.user_id == "chat_user_b"


def test_report_locked_for_free_user_only_from_second_month(client):
    """Piano Free: il report del mese di iscrizione è visibile per intero, dal secondo
    mese in poi viene marcato 'locked' (sfocato lato webapp) per spingere l'upgrade."""
    from datetime import date, datetime
    from src.dashboard.app import store
    from src.storage.models import SavedReport
    from src.user_store import User

    chat_id = "chat_locked_free"
    store.add_user(chat_id=chat_id, username="locked-user", storage_backend="postgres")

    with store.Session() as s:
        user = s.query(User).filter_by(chat_id=chat_id).first()
        user.created_at = datetime(2026, 1, 10)  # iscritto a gennaio 2026

        s.add(SavedReport(
            user_id=chat_id, report_type="monthly",
            report_date=date(2026, 1, 15), text_content="report di gennaio",
        ))
        s.add(SavedReport(
            user_id=chat_id, report_type="monthly",
            report_date=date(2026, 3, 1), text_content="report di marzo",
        ))
        s.commit()

        jan_token = s.query(SavedReport).filter_by(report_date=date(2026, 1, 15)).first().share_token
        mar_token = s.query(SavedReport).filter_by(report_date=date(2026, 3, 1)).first().share_token

    # L'endpoint di dettaglio ora richiede sessione autenticata + ownership check;
    # token_version deve combaciare con quello persistito (vedi _get_session_chat_id).
    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = chat_id
        sess["token_version"] = store.get_token_version(chat_id)

    jan_resp = client.get(f"/api/reports/{jan_token}")
    mar_resp = client.get(f"/api/reports/{mar_token}")

    assert jan_resp.status_code == 200
    assert jan_resp.json["plan_type"] == "free"
    assert jan_resp.json["locked"] is False

    assert mar_resp.status_code == 200
    assert mar_resp.json["plan_type"] == "free"
    assert mar_resp.json["locked"] is True

    # user_id non deve mai essere esposto sull'endpoint
    assert "user_id" not in jan_resp.json


def test_report_never_locked_for_pro_user(client):
    """Piano Pro: nessun report va mai marcato come 'locked', a prescindere dal mese."""
    from datetime import date, datetime
    from src.dashboard.app import store
    from src.storage.models import SavedReport
    from src.user_store import User

    chat_id = "chat_locked_pro"
    store.add_user(chat_id=chat_id, username="pro-user", storage_backend="postgres")
    store.set_user_plan(chat_id, "pro")

    with store.Session() as s:
        user = s.query(User).filter_by(chat_id=chat_id).first()
        user.created_at = datetime(2026, 1, 10)
        s.add(SavedReport(
            user_id=chat_id, report_type="monthly",
            report_date=date(2026, 5, 1), text_content="report di maggio",
        ))
        s.commit()
        token = s.query(SavedReport).filter_by(report_date=date(2026, 5, 1)).first().share_token

    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = chat_id
        sess["token_version"] = store.get_token_version(chat_id)

    resp = client.get(f"/api/reports/{token}")

    assert resp.status_code == 200
    assert resp.json["plan_type"] == "pro"
    assert resp.json["locked"] is False


def test_reports_list_marks_locked_reports_for_free_user(client):
    """L'endpoint di lista /api/reports deve riportare 'locked' coerente per ogni report."""
    from datetime import date, datetime
    from src.dashboard.app import store
    from src.storage.models import SavedReport
    from src.user_store import User

    chat_id = "chat_locked_list"
    store.add_user(chat_id=chat_id, username="locked-list-user", storage_backend="postgres")

    with store.Session() as s:
        user = s.query(User).filter_by(chat_id=chat_id).first()
        user.created_at = datetime(2026, 1, 10)
        s.add(SavedReport(
            user_id=chat_id, report_type="monthly",
            report_date=date(2026, 1, 15), text_content="report di gennaio",
        ))
        s.add(SavedReport(
            user_id=chat_id, report_type="monthly",
            report_date=date(2026, 3, 1), text_content="report di marzo",
        ))
        s.commit()

    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = chat_id
        sess["token_version"] = store.get_token_version(chat_id)

    resp = client.get("/api/reports")

    assert resp.status_code == 200
    assert resp.json["plan_type"] == "free"
    locked_by_date = {r["report_date"]: r["locked"] for r in resp.json["reports"]}
    assert locked_by_date["2026-01-15"] is False
    assert locked_by_date["2026-03-01"] is True


def test_space_transfers_create_and_list(client):
    """POST /api/space/transfers crea il trasferimento e aggiorna i saldi;
    GET /api/space/transfers lo restituisce nel range di date richiesto."""
    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage

    store.add_user(chat_id="chat_transfer_user", username="transfer-user", storage_backend="postgres")
    with store.Session() as s:
        pg = PostgresStorage(session=s, user_id="chat_transfer_user")
        acc_from = pg.create_account("Corrente", initial_balance=500.0)
        acc_to = pg.create_account("Risparmio", initial_balance=0.0)

    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = "chat_transfer_user"
        sess["token_version"] = store.get_token_version("chat_transfer_user")

    csrf_token = client.get("/api/csrf-token").json["csrf_token"]

    resp = client.post(
        "/api/space/transfers",
        json={
            "amount": 150.0,
            "from_account_id": acc_from["id"],
            "to_account_id": acc_to["id"],
            "date": "2026-04-10",
            "name": "Giroconto test",
        },
        headers={"X-CSRFToken": csrf_token},
    )
    assert resp.status_code == 201

    resp = client.get("/api/space/transfers?start=2026-04-01&end=2026-04-30")
    assert resp.status_code == 200
    transfers = resp.json["transfers"]
    assert len(transfers) == 1
    assert transfers[0]["amount"] == 150.0
    assert transfers[0]["from_account_id"] == acc_from["id"]
    assert transfers[0]["to_account_id"] == acc_to["id"]

    resp = client.get("/api/space/accounts")
    balances = {a["name"]: a["current_balance"] for a in resp.json["accounts"]}
    assert balances["Corrente"] == 500.0 - 150.0
    assert balances["Risparmio"] == 0.0 + 150.0


def test_space_transfers_rejects_same_account(client):
    """POST /api/space/transfers rifiuta from_account_id == to_account_id (400)."""
    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage

    store.add_user(chat_id="chat_transfer_same", username="transfer-same", storage_backend="postgres")
    with store.Session() as s:
        pg = PostgresStorage(session=s, user_id="chat_transfer_same")
        acc = pg.create_account("Unico", initial_balance=100.0)

    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = "chat_transfer_same"
        sess["token_version"] = store.get_token_version("chat_transfer_same")

    csrf_token = client.get("/api/csrf-token").json["csrf_token"]

    resp = client.post(
        "/api/space/transfers",
        json={"amount": 10.0, "from_account_id": acc["id"], "to_account_id": acc["id"]},
        headers={"X-CSRFToken": csrf_token},
    )
    assert resp.status_code == 400


def test_space_transfers_update(client):
    """PUT /api/space/transfers/<id> aggiorna il trasferimento e ribilancia i conti."""
    from datetime import date
    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage

    store.add_user(chat_id="chat_transfer_update", username="transfer-update", storage_backend="postgres")
    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = "chat_transfer_update"
        sess["token_version"] = store.get_token_version("chat_transfer_update")
    csrf_token = client.get("/api/csrf-token").json["csrf_token"]

    with store.Session() as s:
        pg = PostgresStorage(session=s, user_id="chat_transfer_update")
        acc_from = pg.create_account("Corrente", initial_balance=500.0)
        acc_to = pg.create_account("Risparmio", initial_balance=0.0)
        created = pg.create_transfer(
            transfer_date=date(2026, 4, 10), amount=150.0,
            from_account_id=acc_from["id"], to_account_id=acc_to["id"], name="Giroconto",
        )

    resp = client.put(
        f"/api/space/transfers/{created['id']}",
        json={"amount": 200.0},
        headers={"X-CSRFToken": csrf_token},
    )
    assert resp.status_code == 200
    assert resp.json["amount"] == 200.0

    resp = client.get("/api/space/accounts")
    balances = {a["name"]: a["current_balance"] for a in resp.json["accounts"]}
    assert balances["Corrente"] == 500.0 - 200.0
    assert balances["Risparmio"] == 0.0 + 200.0


def test_space_transfers_update_rejects_same_account(client):
    """PUT /api/space/transfers/<id> rifiuta from == to (400)."""
    from datetime import date
    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage

    store.add_user(chat_id="chat_transfer_update_same", username="transfer-update-same", storage_backend="postgres")
    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = "chat_transfer_update_same"
        sess["token_version"] = store.get_token_version("chat_transfer_update_same")
    csrf_token = client.get("/api/csrf-token").json["csrf_token"]

    with store.Session() as s:
        pg = PostgresStorage(session=s, user_id="chat_transfer_update_same")
        acc_from = pg.create_account("Corrente", initial_balance=500.0)
        acc_to = pg.create_account("Risparmio", initial_balance=0.0)
        created = pg.create_transfer(
            transfer_date=date(2026, 4, 10), amount=150.0,
            from_account_id=acc_from["id"], to_account_id=acc_to["id"],
        )

    resp = client.put(
        f"/api/space/transfers/{created['id']}",
        json={"to_account_id": acc_from["id"]},
        headers={"X-CSRFToken": csrf_token},
    )
    assert resp.status_code == 400


def test_space_transfers_update_not_found(client):
    """PUT /api/space/transfers/<id> con id inesistente restituisce 404."""
    from src.dashboard.app import store

    store.add_user(chat_id="chat_transfer_update_404", username="transfer-update-404", storage_backend="postgres")
    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = "chat_transfer_update_404"
        sess["token_version"] = store.get_token_version("chat_transfer_update_404")
    csrf_token = client.get("/api/csrf-token").json["csrf_token"]

    resp = client.put(
        "/api/space/transfers/999999",
        json={"amount": 10.0},
        headers={"X-CSRFToken": csrf_token},
    )
    assert resp.status_code == 404


def test_space_transfers_delete(client):
    """DELETE /api/space/transfers/<id> elimina il trasferimento e ripristina i saldi."""
    from datetime import date
    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage

    store.add_user(chat_id="chat_transfer_delete", username="transfer-delete", storage_backend="postgres")
    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = "chat_transfer_delete"
        sess["token_version"] = store.get_token_version("chat_transfer_delete")
    csrf_token = client.get("/api/csrf-token").json["csrf_token"]

    with store.Session() as s:
        pg = PostgresStorage(session=s, user_id="chat_transfer_delete")
        acc_from = pg.create_account("Corrente", initial_balance=500.0)
        acc_to = pg.create_account("Risparmio", initial_balance=0.0)
        created = pg.create_transfer(
            transfer_date=date(2026, 4, 10), amount=150.0,
            from_account_id=acc_from["id"], to_account_id=acc_to["id"],
        )

    resp = client.delete(
        f"/api/space/transfers/{created['id']}",
        headers={"X-CSRFToken": csrf_token},
    )
    assert resp.status_code == 200

    resp = client.get("/api/space/accounts")
    balances = {a["name"]: a["current_balance"] for a in resp.json["accounts"]}
    assert balances["Corrente"] == 500.0
    assert balances["Risparmio"] == 0.0


def test_space_transfers_delete_not_found(client):
    """DELETE /api/space/transfers/<id> con id inesistente restituisce 404."""
    from src.dashboard.app import store

    store.add_user(chat_id="chat_transfer_delete_404", username="transfer-delete-404", storage_backend="postgres")
    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = "chat_transfer_delete_404"
        sess["token_version"] = store.get_token_version("chat_transfer_delete_404")
    csrf_token = client.get("/api/csrf-token").json["csrf_token"]

    resp = client.delete(
        "/api/space/transfers/999999",
        headers={"X-CSRFToken": csrf_token},
    )
    assert resp.status_code == 404


def test_space_categories_create_with_description_synthesizes_summary(client, monkeypatch):
    """POST /api/space/categories con `description` chiama la sintesi LLM una tantum
    e salva sia il testo grezzo che la sintesi."""
    from src.dashboard.app import store
    from src.mistral_client import MistralClient

    store.add_user(chat_id="chat_catdesc_create", username="catdesc-create", storage_backend="postgres")
    monkeypatch.setattr(
        MistralClient, "synthesize_category_description",
        lambda self, raw: "Spese per uscire a cena o pranzo fuori casa",
    )

    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = "chat_catdesc_create"
        sess["token_version"] = store.get_token_version("chat_catdesc_create")

    csrf_token = client.get("/api/csrf-token").json["csrf_token"]

    resp = client.post(
        "/api/space/categories",
        json={"name": "Cene/Pranzi", "description": "spese fatte per uscire fuori a cena o pranzo"},
        headers={"X-CSRFToken": csrf_token},
    )
    assert resp.status_code == 201
    assert resp.json["description"] == "spese fatte per uscire fuori a cena o pranzo"
    assert resp.json["description_summary"] == "Spese per uscire a cena o pranzo fuori casa"

    resp = client.get("/api/space/categories")
    cat = next(c for c in resp.json["categories"] if c["name"] == "Cene/Pranzi")
    assert cat["description_summary"] == "Spese per uscire a cena o pranzo fuori casa"


def test_space_categories_create_rejects_description_too_long(client):
    """La descrizione oltre il limite (500 caratteri) viene rifiutata con 400."""
    from src.dashboard.app import store

    store.add_user(chat_id="chat_catdesc_toolong", username="catdesc-toolong", storage_backend="postgres")
    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = "chat_catdesc_toolong"
        sess["token_version"] = store.get_token_version("chat_catdesc_toolong")

    csrf_token = client.get("/api/csrf-token").json["csrf_token"]

    resp = client.post(
        "/api/space/categories",
        json={"name": "Shopping", "description": "x" * 501},
        headers={"X-CSRFToken": csrf_token},
    )
    assert resp.status_code == 400


def test_space_categories_update_without_description_keeps_existing(client, monkeypatch):
    """PUT senza `description` nel body non tocca la descrizione già salvata
    (aggiorna solo monthly_budget, come per name/monthly_budget)."""
    from src.dashboard.app import store
    from src.mistral_client import MistralClient

    store.add_user(chat_id="chat_catdesc_update", username="catdesc-update", storage_backend="postgres")
    monkeypatch.setattr(
        MistralClient, "synthesize_category_description", lambda self, raw: "Sigarette e svapo",
    )

    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = "chat_catdesc_update"
        sess["token_version"] = store.get_token_version("chat_catdesc_update")

    csrf_token = client.get("/api/csrf-token").json["csrf_token"]

    created = client.post(
        "/api/space/categories",
        json={"name": "Fumo", "description": "sigarette, tabacco e liquidi da svapo"},
        headers={"X-CSRFToken": csrf_token},
    ).json

    resp = client.put(
        f"/api/space/categories/{created['id']}",
        json={"monthly_budget": 50.0},
        headers={"X-CSRFToken": csrf_token},
    )
    assert resp.status_code == 200
    assert resp.json["monthly_budget"] == 50.0
    assert resp.json["description_summary"] == "Sigarette e svapo"


def _login_chat_user(client, store, chat_id):
    """Sessione autenticata minimale (storage postgres) per gli endpoint /api/chat/*."""
    store.add_user(chat_id=chat_id, username=chat_id, storage_backend="postgres")
    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = chat_id
        sess["token_version"] = store.get_token_version(chat_id)
    return client.get("/api/csrf-token").json["csrf_token"]


def test_chat_quick_expenses_requires_authentication(client):
    """I suggerimenti rapidi chat non sono disponibili senza una sessione valida."""
    response = client.get("/api/chat/quick-expenses")

    assert response.status_code == 401
    assert response.json == {"error": "Unauthorized"}


def test_chat_quick_expenses_ranks_non_subscription_expenses(client, monkeypatch):
    """Il ranking usa frequenza, poi ultima occorrenza, ed esclude gli abbonamenti."""
    from datetime import date
    from src.dashboard.blueprints import chat_routes as app_module
    from src.dashboard.app import store

    _login_chat_user(client, store, "quick_expenses")
    fake_storage = MagicMock()
    fake_storage.fetch_all_transactions.return_value = [
        {"name": "Pranzo", "account_id": "1", "date": date(2026, 8, 20)},
        {"name": " benzina ", "account_id": "1", "date": date(2026, 8, 19)},
        {"name": "Pranzo", "account_id": "2", "date": date(2026, 8, 21)},
        {"name": "Benzina", "account_id": "1", "date": date(2026, 8, 21)},
        {"name": "Netflix", "account_id": "1", "date": date(2026, 8, 22)},
        {"name": "Senza conto", "date": date(2026, 8, 22)},
        {"name": "Senza data", "account_id": "1"},
    ]
    fake_storage.fetch_subscriptions.return_value = [{"name": "  netflix  "}]
    fake_storage.fetch_accounts.return_value = [
        {"id": "1", "name": "Conto"},
        {"id": "2", "name": "Carta"},
    ]
    monkeypatch.setattr(app_module, "_get_storage_for_chat", lambda _chat_id: fake_storage)

    response = client.get("/api/chat/quick-expenses")

    assert response.status_code == 200
    assert response.json["quick_expenses"] == [
        {
            "label": "Pranzo", "name": "Pranzo", "category": "", "account_id": "2",
            "account_name": "Carta", "source": "auto",
        },
    ]


def test_chat_quick_expenses_closes_storage_after_read(client, monkeypatch):
    """Il suggerimento rapido rilascia lo storage tramite l'interfaccia pubblica."""
    from datetime import date
    from src.dashboard.blueprints import chat_routes as app_module
    from src.dashboard.app import store

    _login_chat_user(client, store, "quick_expenses_close")
    fake_storage = MagicMock()
    fake_storage.fetch_all_transactions.return_value = [
        {"name": "Pranzo", "account_id": "1", "date": date(2026, 8, 22)},
    ]
    fake_storage.fetch_subscriptions.return_value = []
    fake_storage.fetch_accounts.return_value = [{"id": "1", "name": "Conto"}]
    monkeypatch.setattr(app_module, "_get_storage_for_chat", lambda _chat_id: fake_storage)

    response = client.get("/api/chat/quick-expenses")

    assert response.status_code == 200
    fake_storage.close.assert_called_once_with()


def test_chat_quick_expenses_returns_generic_error_when_storage_build_fails(client, monkeypatch):
    """Un errore di costruzione storage non espone dettagli interni al client."""
    from src.dashboard.blueprints import chat_routes as app_module
    from src.dashboard.app import store

    _login_chat_user(client, store, "quick_expenses_build_error")

    def _raise_storage_build_error(_chat_id):
        raise RuntimeError("database credentials unavailable")

    monkeypatch.setattr(app_module, "_get_storage_for_chat", _raise_storage_build_error)

    response = client.get("/api/chat/quick-expenses")

    assert response.status_code == 500
    assert response.json == {"error": "Impossibile caricare i suggerimenti"}


def test_chat_quick_expenses_returns_empty_without_eligible_expenses(client, monkeypatch):
    """Righe incomplete o legate ad abbonamenti non generano chip rapidi."""
    from datetime import date
    from src.dashboard.blueprints import chat_routes as app_module
    from src.dashboard.app import store

    _login_chat_user(client, store, "quick_expenses_empty")
    fake_storage = MagicMock()
    fake_storage.fetch_all_transactions.return_value = [
        {"name": "Netflix", "account_id": "1", "date": date(2026, 8, 22)},
        {"name": "", "account_id": "1", "date": date(2026, 8, 22)},
        {"name": "Pranzo", "account_id": None, "date": date(2026, 8, 22)},
    ]
    fake_storage.fetch_subscriptions.return_value = [{"name": "Netflix"}]
    fake_storage.fetch_accounts.return_value = [{"id": "1", "name": "Conto"}]
    monkeypatch.setattr(app_module, "_get_storage_for_chat", lambda _chat_id: fake_storage)

    response = client.get("/api/chat/quick-expenses")

    assert response.status_code == 200
    assert response.json == {"quick_expenses": []}


def test_chat_quick_expenses_custom_create_list_delete(client):
    """Ciclo completo del bottone personalizzato: creazione, comparsa in elenco, cancellazione."""
    from src.dashboard.app import store
    from src.storage.models import UserCategory, Account

    csrf = _login_chat_user(client, store, "quick_expenses_custom")
    with store.Session() as s:
        cat = UserCategory(user_id="quick_expenses_custom", name="Sport")
        acc = Account(user_id="quick_expenses_custom", name="Conto Test", opening_balance=0)
        s.add_all([cat, acc])
        s.commit()
        category_id, account_id = cat.id, acc.id

    create_resp = client.post(
        "/api/chat/quick-expenses/custom",
        json={"name": "Palestra abbonamento", "category_id": category_id, "account_id": account_id},
        headers={"X-CSRFToken": csrf},
    )
    assert create_resp.status_code == 201
    shortcut_id = create_resp.json["id"]

    list_resp = client.get("/api/chat/quick-expenses")
    assert list_resp.status_code == 200
    custom_entries = [q for q in list_resp.json["quick_expenses"] if q["source"] == "custom"]
    assert custom_entries == [
        {
            "id": shortcut_id, "label": "Palestra abbonamento", "name": "Palestra abbonamento",
            "category": "Sport", "account_id": str(account_id), "account_name": "Conto Test",
            "source": "custom",
        },
    ]

    delete_resp = client.delete(
        f"/api/chat/quick-expenses/custom/{shortcut_id}", headers={"X-CSRFToken": csrf}
    )
    assert delete_resp.status_code == 200

    list_after = client.get("/api/chat/quick-expenses")
    assert [q for q in list_after.json["quick_expenses"] if q["source"] == "custom"] == []


def test_chat_quick_expenses_custom_reorder(client):
    """Il riordino (tocca-e-trascina in chat) persiste e si riflette nell'elenco."""
    from src.dashboard.app import store

    csrf = _login_chat_user(client, store, "quick_expenses_reorder")
    ids = []
    for name in ("Prima", "Seconda", "Terza"):
        r = client.post(
            "/api/chat/quick-expenses/custom", json={"name": name}, headers={"X-CSRFToken": csrf}
        )
        ids.append(r.json["id"])

    # Ordine iniziale = ordine di creazione.
    initial = [q["name"] for q in client.get("/api/chat/quick-expenses").json["quick_expenses"] if q["source"] == "custom"]
    assert initial == ["Prima", "Seconda", "Terza"]

    reversed_ids = list(reversed(ids))
    reorder_resp = client.put(
        "/api/chat/quick-expenses/custom/reorder", json={"order": reversed_ids}, headers={"X-CSRFToken": csrf}
    )
    assert reorder_resp.status_code == 200

    after = [q["name"] for q in client.get("/api/chat/quick-expenses").json["quick_expenses"] if q["source"] == "custom"]
    assert after == ["Terza", "Seconda", "Prima"]


def test_chat_quick_expenses_custom_reorder_ignores_foreign_ids(client):
    """Un id che non appartiene all'utente viene ignorato, non rompe il riordino."""
    from src.dashboard.app import store

    csrf_a = _login_chat_user(client, store, "quick_expenses_reorder_a")
    r = client.post("/api/chat/quick-expenses/custom", json={"name": "Mio"}, headers={"X-CSRFToken": csrf_a})
    my_id = r.json["id"]

    resp = client.put(
        "/api/chat/quick-expenses/custom/reorder",
        json={"order": [999999, my_id]},
        headers={"X-CSRFToken": csrf_a},
    )
    assert resp.status_code == 200

    names = [q["name"] for q in client.get("/api/chat/quick-expenses").json["quick_expenses"] if q["source"] == "custom"]
    assert names == ["Mio"]


def test_chat_quick_expenses_custom_create_requires_name(client):
    from src.dashboard.app import store

    csrf = _login_chat_user(client, store, "quick_expenses_custom_noname")
    resp = client.post(
        "/api/chat/quick-expenses/custom", json={"name": "  "}, headers={"X-CSRFToken": csrf}
    )
    assert resp.status_code == 400


def test_chat_quick_expenses_custom_requires_authentication(client):
    resp = client.post("/api/chat/quick-expenses/custom", json={"name": "Palestra"})
    assert resp.status_code == 401
    resp = client.delete("/api/chat/quick-expenses/custom/1")
    assert resp.status_code == 401


def test_chat_quick_expenses_custom_create_rejects_invalid_ids(client):
    """category_id/account_id non numerici devono essere rifiutati con 400, non 500."""
    from src.dashboard.app import store

    csrf = _login_chat_user(client, store, "quick_expenses_custom_badids")
    resp = client.post(
        "/api/chat/quick-expenses/custom",
        json={"name": "Palestra", "category_id": "not-an-int"},
        headers={"X-CSRFToken": csrf},
    )
    assert resp.status_code == 400

    resp = client.post(
        "/api/chat/quick-expenses/custom",
        json={"name": "Palestra", "account_id": "also-not-an-int"},
        headers={"X-CSRFToken": csrf},
    )
    assert resp.status_code == 400


def test_chat_quick_expenses_custom_delete_nonexistent_returns_404(client):
    from src.dashboard.app import store

    csrf = _login_chat_user(client, store, "quick_expenses_del_missing")
    resp = client.delete("/api/chat/quick-expenses/custom/999999", headers={"X-CSRFToken": csrf})
    assert resp.status_code == 404


def test_chat_quick_expenses_custom_delete_ignores_other_users_shortcut(client):
    """Un utente non può cancellare il bottone personalizzato di un altro utente."""
    from src.dashboard.app import store

    csrf_a = _login_chat_user(client, store, "quick_expenses_del_owner")
    r = client.post(
        "/api/chat/quick-expenses/custom", json={"name": "Suo"}, headers={"X-CSRFToken": csrf_a}
    )
    other_id = r.json["id"]

    csrf_b = _login_chat_user(client, store, "quick_expenses_del_attacker")
    resp = client.delete(
        f"/api/chat/quick-expenses/custom/{other_id}", headers={"X-CSRFToken": csrf_b}
    )
    assert resp.status_code == 404

    # Rimane ancora visibile per il proprietario originale.
    _login_chat_user(client, store, "quick_expenses_del_owner")
    names = [
        q["name"]
        for q in client.get("/api/chat/quick-expenses").json["quick_expenses"]
        if q["source"] == "custom"
    ]
    assert names == ["Suo"]


def test_chat_quick_expenses_custom_reorder_rejects_non_list_order(client):
    from src.dashboard.app import store

    csrf = _login_chat_user(client, store, "quick_expenses_reorder_badtype")
    resp = client.put(
        "/api/chat/quick-expenses/custom/reorder",
        json={"order": "not-a-list"},
        headers={"X-CSRFToken": csrf},
    )
    assert resp.status_code == 400


def test_chat_quick_expenses_custom_reorder_requires_authentication(client):
    resp = client.put("/api/chat/quick-expenses/custom/reorder", json={"order": []})
    assert resp.status_code == 401


def _fake_parsed(**overrides):
    from datetime import date as _date

    base = {
        "type": "expense",
        "date": _date(2026, 4, 10),
        "amount": 20.0,
        "category": "Ristoranti",
        "name": "Pizza",
        "income_type": None,
        "from_account": None,
        "to_account": None,
    }
    base.update(overrides)
    return base


def test_chat_message_multi_transaction(client):
    """Un messaggio con più spese restituisce più item in 'transactions' (bot.py:1769-1791)."""
    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage
    from src.expense_parser import ExpenseParser

    csrf_token = _login_chat_user(client, store, "chat_multi_user")
    with store.Session() as s:
        pg = PostgresStorage(session=s, user_id="chat_multi_user")
        pg.create_account("Corrente", initial_balance=100.0)

    transactions = [
        _fake_parsed(name="Pizza", amount=20.0),
        _fake_parsed(name="Benzina", amount=15.0, category="Trasporti"),
    ]
    with patch.object(ExpenseParser, "parse_multi_with_usage", return_value=(transactions, {})):
        resp = client.post(
            "/api/chat/message",
            json={"text": "Ho speso 20€ pizza e 15€ benzina"},
            headers={"X-CSRFToken": csrf_token},
        )

    assert resp.status_code == 200
    body = resp.json
    assert body["ok"] is True
    assert len(body["transactions"]) == 2
    names = {tx["parsed"]["name"] for tx in body["transactions"]}
    assert names == {"Pizza", "Benzina"}
    assert all(tx["awaiting_confirm"] for tx in body["transactions"])


def test_chat_message_reports_category_promotion_after_threshold(client, monkeypatch):
    """/api/chat/message espone category_promotion su una transazione quando la
    categorizzazione adattiva (src/category_matcher.py) raggiunge la soglia —
    stessa logica condivisa col bot Telegram, qui esercitata via webapp."""
    from config import Config
    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage
    from src.expense_parser import ExpenseParser

    monkeypatch.setattr(Config, "CATEGORY_PROMOTION_THRESHOLD", 1)

    csrf_token = _login_chat_user(client, store, "chat_catpromote_user")
    with store.Session() as s:
        pg = PostgresStorage(session=s, user_id="chat_catpromote_user")
        pg.create_account("Corrente", initial_balance=100.0)

    transactions = [_fake_parsed(name="Pizza Speciale", amount=20.0, category="Ristoranti Nuovi")]
    with patch.object(ExpenseParser, "parse_multi_with_usage", return_value=(transactions, {})):
        resp = client.post(
            "/api/chat/message",
            json={"text": "20€ pizza speciale"},
            headers={"X-CSRFToken": csrf_token},
        )

    assert resp.status_code == 200
    tx = resp.json["transactions"][0]
    promotion = tx.get("category_promotion")
    assert promotion is not None
    assert promotion["suggested_name"] == "Pizza Speciale"
    assert isinstance(promotion["candidate_id"], int)


def test_chat_category_confirm_yes_creates_category(client, monkeypatch):
    """/api/chat/category-confirm con decision=yes crea davvero la categoria."""
    from config import Config
    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage
    from src.storage.models import UserCategory
    from src.expense_parser import ExpenseParser

    monkeypatch.setattr(Config, "CATEGORY_PROMOTION_THRESHOLD", 1)

    csrf_token = _login_chat_user(client, store, "chat_catconfirm_user")
    with store.Session() as s:
        pg = PostgresStorage(session=s, user_id="chat_catconfirm_user")
        pg.create_account("Corrente", initial_balance=100.0)

    transactions = [_fake_parsed(name="Abbonamento Palestra", amount=40.0, category="Sport Nuovo")]
    with patch.object(ExpenseParser, "parse_multi_with_usage", return_value=(transactions, {})):
        resp = client.post(
            "/api/chat/message",
            json={"text": "40€ palestra"},
            headers={"X-CSRFToken": csrf_token},
        )
    candidate_id = resp.json["transactions"][0]["category_promotion"]["candidate_id"]

    confirm_resp = client.post(
        "/api/chat/category-confirm",
        json={"candidate_id": candidate_id, "decision": "yes"},
        headers={"X-CSRFToken": csrf_token},
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json["ok"] is True

    with store.Session() as s:
        assert s.query(UserCategory).filter_by(
            user_id="chat_catconfirm_user", name="Abbonamento Palestra",
        ).first() is not None


def test_chat_category_confirm_no_resets_occurrences(client, monkeypatch):
    """/api/chat/category-confirm con decision=no azzera il contatore, nessuna categoria creata."""
    from config import Config
    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage
    from src.storage.models import CategoryCandidate, UserCategory
    from src.expense_parser import ExpenseParser

    monkeypatch.setattr(Config, "CATEGORY_PROMOTION_THRESHOLD", 1)

    csrf_token = _login_chat_user(client, store, "chat_catdecline_user")
    with store.Session() as s:
        pg = PostgresStorage(session=s, user_id="chat_catdecline_user")
        pg.create_account("Corrente", initial_balance=100.0)

    transactions = [_fake_parsed(name="Rivista Mensile", amount=5.0, category="Edicola Nuova")]
    with patch.object(ExpenseParser, "parse_multi_with_usage", return_value=(transactions, {})):
        resp = client.post(
            "/api/chat/message",
            json={"text": "5€ rivista"},
            headers={"X-CSRFToken": csrf_token},
        )
    candidate_id = resp.json["transactions"][0]["category_promotion"]["candidate_id"]

    decline_resp = client.post(
        "/api/chat/category-confirm",
        json={"candidate_id": candidate_id, "decision": "no"},
        headers={"X-CSRFToken": csrf_token},
    )
    assert decline_resp.status_code == 200
    assert decline_resp.json["ok"] is True

    with store.Session() as s:
        candidate = s.query(CategoryCandidate).filter_by(id=candidate_id).one()
        assert candidate.status == "pending"
        assert candidate.occurrences == 0
        assert s.query(UserCategory).filter_by(
            user_id="chat_catdecline_user", name="Rivista Mensile",
        ).first() is None


def test_chat_confirm_expense_requires_account_id(client):
    """/api/chat/confirm rifiuta una spesa senza account_id esplicito (niente default silenzioso)."""
    from src.dashboard.app import store

    csrf_token = _login_chat_user(client, store, "chat_noaccount_user")

    resp = client.post(
        "/api/chat/confirm",
        json={"parsed": {"type": "expense", "amount": 20.0, "date": "2026-04-10", "name": "Pizza"}},
        headers={"X-CSRFToken": csrf_token},
    )
    assert resp.status_code == 400


def test_chat_confirm_expense_saves_with_category_override(client):
    """/api/chat/confirm salva la categoria scelta dal picker rapido, non quella originale."""
    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage
    from src.storage.models import Expense as ExpenseModel

    csrf_token = _login_chat_user(client, store, "chat_category_user")
    with store.Session() as s:
        pg = PostgresStorage(session=s, user_id="chat_category_user")
        acc = pg.create_account("Corrente", initial_balance=100.0)

    resp = client.post(
        "/api/chat/confirm",
        json={
            "parsed": {"type": "expense", "amount": 20.0, "date": "2026-04-10", "name": "Pizza", "category": "Altro"},
            "account_id": acc["id"],
            "category": "Ristoranti & Fast Food",
        },
        headers={"X-CSRFToken": csrf_token},
    )
    assert resp.status_code == 200
    assert resp.json["saved"] is True

    from src.storage.models import UserCategory

    with store.Session() as s:
        row = s.query(ExpenseModel).filter_by(user_id="chat_category_user").first()
        assert row is not None
        cat_name = s.query(UserCategory.name).filter(UserCategory.id == row.category_id).scalar()
        assert cat_name == "Ristoranti & Fast Food"


def test_chat_confirm_transfer_creates_transfer_not_income(client):
    """/api/chat/confirm con type=transfer crea un Transfer, non un'entrata (bug fix)."""
    from datetime import date as _date
    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage
    from src.storage.models import Income as IncomeModel

    csrf_token = _login_chat_user(client, store, "chat_transfer_confirm_user")
    with store.Session() as s:
        pg = PostgresStorage(session=s, user_id="chat_transfer_confirm_user")
        acc_from = pg.create_account("Corrente", initial_balance=200.0)
        acc_to = pg.create_account("Risparmio", initial_balance=0.0)

    resp = client.post(
        "/api/chat/confirm",
        json={
            "parsed": {
                "type": "transfer", "amount": 50.0, "date": "2026-04-10", "name": "Giroconto",
                "resolved_from_account_name": "Corrente", "resolved_to_account_name": "Risparmio",
            },
            "from_account_id": acc_from["id"],
            "to_account_id": acc_to["id"],
        },
        headers={"X-CSRFToken": csrf_token},
    )
    assert resp.status_code == 200
    assert resp.json["saved"] is True

    with store.Session() as s:
        pg = PostgresStorage(session=s, user_id="chat_transfer_confirm_user")
        transfers = pg.fetch_transfers(_date(2026, 4, 1), _date(2026, 4, 30))
        assert len(transfers) == 1
        assert transfers[0]["amount"] == 50.0
        incomes = s.query(IncomeModel).filter_by(user_id="chat_transfer_confirm_user").count()
        assert incomes == 0


def test_chat_confirm_transfer_rejects_same_account(client):
    """/api/chat/confirm rifiuta un trasferimento con from_account_id == to_account_id."""
    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage

    csrf_token = _login_chat_user(client, store, "chat_transfer_same_user")
    with store.Session() as s:
        pg = PostgresStorage(session=s, user_id="chat_transfer_same_user")
        acc = pg.create_account("Unico", initial_balance=100.0)

    resp = client.post(
        "/api/chat/confirm",
        json={
            "parsed": {"type": "transfer", "amount": 10.0, "date": "2026-04-10", "name": "Giroconto"},
            "from_account_id": acc["id"],
            "to_account_id": acc["id"],
        },
        headers={"X-CSRFToken": csrf_token},
    )
    assert resp.status_code == 400


def test_chat_message_transfer_needs_second_account(client):
    """Con un solo conto, un trasferimento riconosciuto viene bloccato con needs_second_account."""
    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage
    from src.expense_parser import ExpenseParser

    csrf_token = _login_chat_user(client, store, "chat_transfer_single_acc_user")
    with store.Session() as s:
        pg = PostgresStorage(session=s, user_id="chat_transfer_single_acc_user")
        pg.create_account("Unico", initial_balance=100.0)

    transactions = [_fake_parsed(type="transfer", name="Giroconto", amount=50.0, category=None)]
    with patch.object(ExpenseParser, "parse_multi_with_usage", return_value=(transactions, {})):
        resp = client.post(
            "/api/chat/message",
            json={"text": "Trasferisci 50€"},
            headers={"X-CSRFToken": csrf_token},
        )

    assert resp.status_code == 200
    tx = resp.json["transactions"][0]
    assert tx["needs_second_account"] is True
    assert tx["awaiting_confirm"] is False


def test_chat_message_no_account_blocks_batch(client):
    """Senza nessun conto configurato, l'intero messaggio viene bloccato (no_account)."""
    from src.dashboard.app import store
    from src.expense_parser import ExpenseParser

    csrf_token = _login_chat_user(client, store, "chat_no_account_at_all_user")

    transactions = [_fake_parsed(name="Pizza", amount=20.0)]
    with patch.object(ExpenseParser, "parse_multi_with_usage", return_value=(transactions, {})):
        resp = client.post(
            "/api/chat/message",
            json={"text": "Ho speso 20€ pizza"},
            headers={"X-CSRFToken": csrf_token},
        )

    assert resp.status_code == 200
    assert resp.json["type"] == "no_account"
    assert resp.json["ok"] is False


def test_space_transfers_requires_auth(client):
    """GET /api/space/transfers senza sessione/init-data valido risponde 401."""
    resp = client.get("/api/space/transfers")
    assert resp.status_code == 401


def test_chat_message_income_exposes_income_categories_for_picker(client):
    """/api/chat/message per un'entrata popola parsed['categories'] con le categorie
    entrata dell'utente (_build_chat_parse_result + ramo income di
    _build_transaction_payload) — replica il picker "Cambia categoria" già esistente
    per le spese, ora anche per le entrate."""
    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage
    from src.expense_parser import ExpenseParser

    csrf_token = _login_chat_user(client, store, "chat_income_categories_user")
    with store.Session() as s:
        pg = PostgresStorage(session=s, user_id="chat_income_categories_user")
        pg.create_account("Corrente", initial_balance=100.0)
        # "Stipendio" ecc. sono già seminate di default per un nuovo utente
        # (DEFAULT_INCOME_CATEGORIES): qui aggiungiamo una categoria custom per
        # verificare che il fetch arrivi davvero da get_income_category_names()
        # e non da un elenco statico.
        pg.create_income_category("Consulenza Extra")

    transactions = [_fake_parsed(
        type="income", name="Stipendio marzo", amount=1500.0,
        category=None, income_type="Stipendio",
    )]
    with patch.object(ExpenseParser, "parse_multi_with_usage", return_value=(transactions, {})):
        resp = client.post(
            "/api/chat/message",
            json={"text": "stipendio 1500"},
            headers={"X-CSRFToken": csrf_token},
        )

    assert resp.status_code == 200
    tx = resp.json["transactions"][0]
    assert tx["type"] == "income"
    assert "Consulenza Extra" in tx["parsed"]["categories"]
    assert "Stipendio" in tx["parsed"]["categories"]


def test_chat_message_expense_does_not_leak_income_categories(client):
    """Il ramo spesa di _build_transaction_payload deve continuare a esporre le
    categorie spesa, non quelle entrata, anche ora che entrambe vengono caricate
    da _build_chat_parse_result."""
    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage
    from src.expense_parser import ExpenseParser

    csrf_token = _login_chat_user(client, store, "chat_expense_categories_user")
    with store.Session() as s:
        pg = PostgresStorage(session=s, user_id="chat_expense_categories_user")
        pg.create_account("Corrente", initial_balance=100.0)

    transactions = [_fake_parsed(name="Pizza", amount=20.0, category="Ristoranti")]
    with patch.object(ExpenseParser, "parse_multi_with_usage", return_value=(transactions, {})):
        resp = client.post(
            "/api/chat/message",
            json={"text": "20€ pizza"},
            headers={"X-CSRFToken": csrf_token},
        )

    assert resp.status_code == 200
    tx = resp.json["transactions"][0]
    assert "Stipendio" not in tx["parsed"]["categories"]


def test_chat_confirm_income_with_category_correction_records_reason(client):
    """/api/chat/confirm per un'entrata con category_was_corrected=true propaga
    reason='category_corrected' a record_tx_event (parità col ramo spesa)."""
    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage
    from src.user_store import TxEvent

    csrf_token = _login_chat_user(client, store, "chat_income_corrected_user")
    with store.Session() as s:
        pg = PostgresStorage(session=s, user_id="chat_income_corrected_user")
        acc = pg.create_account("Corrente", initial_balance=100.0)

    resp = client.post(
        "/api/chat/confirm",
        json={
            "parsed": {
                "type": "income", "amount": 1500.0, "date": "2026-04-10",
                "name": "Stipendio", "income_type": "Stipendio",
            },
            "account_id": acc["id"],
            "category_was_corrected": True,
        },
        headers={"X-CSRFToken": csrf_token},
    )
    assert resp.status_code == 200
    assert resp.json["saved"] is True

    with store.Session() as s:
        event = s.query(TxEvent).filter_by(
            chat_id="chat_income_corrected_user", tx_type="income", outcome="confirmed",
        ).order_by(TxEvent.id.desc()).first()
        assert event is not None
        assert event.reason == "category_corrected"


def test_chat_confirm_expense_without_correction_flag_has_no_reason(client):
    """Comportamento invariato: senza category_was_corrected nel payload,
    record_tx_event riceve reason=None esattamente come prima dell'introduzione
    del picker categoria per le entrate."""
    from src.dashboard.app import store
    from src.storage.postgres_storage import PostgresStorage
    from src.user_store import TxEvent

    csrf_token = _login_chat_user(client, store, "chat_expense_no_correction_user")
    with store.Session() as s:
        pg = PostgresStorage(session=s, user_id="chat_expense_no_correction_user")
        acc = pg.create_account("Corrente", initial_balance=100.0)

    resp = client.post(
        "/api/chat/confirm",
        json={
            "parsed": {
                "type": "expense", "amount": 20.0, "date": "2026-04-10",
                "name": "Pizza", "category": "Ristoranti",
            },
            "account_id": acc["id"],
        },
        headers={"X-CSRFToken": csrf_token},
    )
    assert resp.status_code == 200
    assert resp.json["saved"] is True

    with store.Session() as s:
        event = s.query(TxEvent).filter_by(
            chat_id="chat_expense_no_correction_user", tx_type="expense", outcome="confirmed",
        ).order_by(TxEvent.id.desc()).first()
        assert event is not None
        assert event.reason is None
