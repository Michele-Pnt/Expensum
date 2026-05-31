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
    """Verifica che la home (/) ridiriga al login se l'utente non è autenticato."""
    response = client.get("/")
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
