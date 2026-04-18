import pytest
from unittest.mock import patch, MagicMock

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

@patch("src.dashboard.app.requests.post")
@patch("src.notion_client.NotionFinanceClient.discover_db_schemas")
@patch("src.notion_client.NotionFinanceClient.discover_databases")
@patch("src.user_store.UserStore.get_and_delete_oauth_session")
@patch("src.user_store.UserStore.add_user")
def test_oauth_callback_success(mock_add_user, mock_get_sess, mock_discover, mock_discover_schemas, mock_post, client):
    """
    Simula un flusso OAuth completo andato a buon fine.
    """
    # 1. Setup Mock
    mock_get_sess.return_value = "chat_123"
    
    # Mock della risposta token di Notion
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "access_token": "ntn_access_token",
        "workspace_id": "ws_123",
        "duplicated_template_id": "tpl_456"
    }
    
    # Mock del discovery DB
    mock_discover.return_value = (
        {
            "expense_db_id": "db_exp",
            "income_db_id": "db_inc",
            "categories_db_id": "db_cat",
            "monthly_balance_db_id": "db_mb",
            "accounts_db_id": "db_acc",
            "subscriptions_db_id": "db_sub",
            "pay_transfer_db_id": "db_pay"
        },
        ["Expenses", "Income"]
    )
    mock_discover_schemas.return_value = {
        "accounts_db_id": {"title_property": "Name", "properties": {"Name": "title"}},
        "categories_db_id": {"title_property": "Name", "properties": {"Name": "title"}},
        "subscriptions_db_id": {"title_property": "Name", "properties": {"Name": "title"}},
    }
    
    # 2. Eseguiamo la chiamata alla callback con lo state e il code
    response = client.get("/auth/notion/callback?code=notion_code&state=RT-magic_token")
    
    # 3. Verifiche
    assert response.status_code == 200
    assert b"Traky \xc3\xa8 Configurato" in response.data or b"Configurato" in response.data
    
    # Verifichiamo che i dati siano stati salvati nel DB mockato
    assert mock_add_user.called
    args, kwargs = mock_add_user.call_args
    assert kwargs["chat_id"] == "chat_123"
    assert kwargs["notion_access_token"] == "ntn_access_token"
    assert kwargs["expense_db_id"] == "db_exp"
