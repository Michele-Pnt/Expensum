import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.e2e

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
