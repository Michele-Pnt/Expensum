import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.e2e


def _create_dashboard_user(store, chat_id="chat_123", email="test@example.com", password="Password123"):
    store.add_user(chat_id=chat_id, username="test-user", storage_backend="postgres")
    store.set_credentials(chat_id, email, password)
    return chat_id, email, password


def test_web_login_success_redirects_to_setup(client):
    from src.dashboard.app import store

    _, email, password = _create_dashboard_user(store)

    response = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)

    assert response.status_code == 302
    assert "/setup?reg_token=" in response.headers["Location"]


def test_web_login_completed_user_redirects_to_chat(client):
    from src.dashboard.app import store

    chat_id, email, password = _create_dashboard_user(
        store,
        chat_id="chat_completed",
        email="completed@example.com",
    )
    store.mark_setup_completed(chat_id)

    response = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/chat")


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


def test_web_login_session_guard_uses_user_logged_in(client):
    from src.dashboard.app import store

    _, email, password = _create_dashboard_user(store, chat_id="chat_guard", email="guard@example.com")

    login_response = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
    assert login_response.status_code == 302

    response = client.get("/login", follow_redirects=False)

    assert response.status_code == 302
    assert "/setup?reg_token=" in response.headers["Location"]


def test_web_login_session_guard_redirects_completed_user_to_chat(client):
    from src.dashboard.app import store

    chat_id, email, password = _create_dashboard_user(
        store,
        chat_id="chat_guard_completed",
        email="guard-completed@example.com",
    )
    store.mark_setup_completed(chat_id)

    login_response = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
    assert login_response.status_code == 302

    response = client.get("/login", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/chat")


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


def test_web_app_entry_redirects_completed_users_to_chat(client):
    from src.dashboard.app import store

    chat_id, email, password = _create_dashboard_user(
        store,
        chat_id="chat_app_done",
        email="app-done@example.com",
    )
    store.mark_setup_completed(chat_id)

    login_response = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
    assert login_response.status_code == 302

    response = client.get("/app", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/chat")


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


def test_api_auth_session_returns_chat_for_completed_browser_session(client):
    from src.dashboard.app import store

    chat_id, email, password = _create_dashboard_user(
        store,
        chat_id="chat_auth_done",
        email="auth-done@example.com",
    )
    store.mark_setup_completed(chat_id)

    login_response = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
    assert login_response.status_code == 302

    response = client.get("/api/auth/session")

    assert response.status_code == 200
    assert response.json["authorized"] is True
    assert response.json["auth_mode"] == "browser"
    assert response.json["redirect_to"] is None


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
    assert response.json == {"reports": []}


def test_telegram_login_template_has_mobile_keyboard_guards(client):
    from src.dashboard.app import store

    state = store.create_oauth_session("chat_keyboard")
    response = client.get(f"/auth/telegram-login?state={state}")

    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'inputmode="email"' in html
    assert 'autocapitalize="none"' in html
    assert 'autocorrect="off"' in html
    assert 'spellcheck="false"' in html
    assert 'enterkeyhint="next"' in html
    assert 'enterkeyhint="go"' in html

def test_telegram_login_reassigns_account_to_new_chat_id(client):
    from src.dashboard.app import store

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

@patch("src.dashboard.app.threading.Thread")
@patch("src.dashboard.app.requests.post")
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


def test_privacy_export_json_requires_auth(client):
    response = client.get("/api/privacy/export-json")
    assert response.status_code == 401


def test_privacy_export_json_excludes_secrets_and_includes_financial_data(client):
    from src.storage.models import Account, Expense
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
        s.commit()

    response = client.get("/api/privacy/export-json")

    assert response.status_code == 200
    body = response.json
    assert body["account"]["email"] == email
    assert "password_hash" not in body["account"]
    assert "notion_access_token" not in body["account"]
    assert len(body["financial_data"]["expenses"]) == 1
    assert body["financial_data"]["expenses"][0]["name"] == "Caffè"
    assert "your_rights" in body

    with store.Session() as s:
        from src.user_store import AuditLog
        log = s.query(AuditLog).filter_by(user_id=chat_id, action="export_json").first()
        assert log is not None


def test_privacy_export_json_notion_backend_does_not_call_notion_api(client):
    from src.dashboard.app import store

    chat_id, email = "chat_privacy_json_notion", "privacy-json-notion@example.com"
    _login_completed(client, store, chat_id, email, storage_backend="notion")

    response = client.get("/api/privacy/export-json")

    assert response.status_code == 200
    assert "note" in response.json["financial_data"]


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


def test_privacy_export_csv_notion_backend_returns_404(client):
    from src.dashboard.app import store

    chat_id, email = "chat_privacy_csv_notion", "privacy-csv-notion@example.com"
    _login_completed(client, store, chat_id, email, storage_backend="notion")

    response = client.get("/api/privacy/export-csv")

    assert response.status_code == 404


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
    from src.dashboard.app import store, Config

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
    from src.dashboard.app import store, Config

    _login_completed(client, store, "web_test456", "web-link-2@example.com")

    csrf_token = client.get("/api/csrf-token").json["csrf_token"]
    with patch.object(Config, "TELEGRAM_BOT_USERNAME", ""):
        response = client.post("/api/telegram/link", headers={"X-CSRFToken": csrf_token})

    assert response.status_code == 500
