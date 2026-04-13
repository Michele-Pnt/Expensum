import pytest
from unittest.mock import MagicMock, patch
from src.notion_client import NotionFinanceClient

@pytest.fixture
def mock_notion_client():
    with patch("notion_client.Client") as mock:
        yield mock

def test_discover_databases_strategy_1(mock_notion_client):
    """Test Strategia 1: Discovery tramite child_database di una pagina template."""
    mock_instance = mock_notion_client.return_value
    
    # Simuliamo i blocchi figli del template
    mock_instance.blocks.children.list.return_value = {
        "results": [
            {"type": "child_database", "id": "exp_id", "child_database": {"title": "Expense"}},
            {"type": "child_database", "id": "inc_id", "child_database": {"title": "Income"}},
            {"type": "child_database", "id": "cat_id", "child_database": {"title": "Categories"}},
            {"type": "child_database", "id": "mb_id", "child_database": {"title": "Monthly Balance"}},
            {"type": "child_database", "id": "acc_id", "child_database": {"title": "Accounts"}},
            {"type": "child_database", "id": "sub_id", "child_database": {"title": "Subscriptions"}},
            {"type": "child_database", "id": "pay_id", "child_database": {"title": "Pay/Transfer"}},
        ]
    }
    
    discovered = NotionFinanceClient.discover_databases("fake_token", template_page_id="tpl_123")
    
    assert len(discovered) == 7
    assert discovered["expense_db_id"] == "exp_id"
    assert discovered["categories_db_id"] == "cat_id"
    # Verifichiamo che non abbia provato la strategia 2 (nessuna chiamata a search)
    assert mock_instance.search.call_count == 0

def test_discover_databases_strategy_2(mock_notion_client):
    """Test Strategia 2: Fallback alla ricerca della pagina 'Finance Tracker'."""
    mock_instance = mock_notion_client.return_value
    
    # 1. Search trova la pagina "Finance Tracker"
    mock_instance.search.return_value = {
        "results": [
            {"object": "page", "id": "finance_page_id", "parent": {"type": "workspace"}}
        ]
    }
    
    # 2. I blocchi di quella pagina contengono i DB
    mock_instance.blocks.children.list.return_value = {
        "results": [
            {"type": "child_database", "id": "exp_id", "child_database": {"title": "Expense"}},
            {"type": "child_database", "id": "inc_id", "child_database": {"title": "Income"}},
            {"type": "child_database", "id": "cat_id", "child_database": {"title": "Categories"}},
            {"type": "child_database", "id": "mb_id", "child_database": {"title": "Monthly Balance"}},
            {"type": "child_database", "id": "acc_id", "child_database": {"title": "Accounts"}},
            {"type": "child_database", "id": "sub_id", "child_database": {"title": "Subscriptions"}},
            {"type": "child_database", "id": "pay_id", "child_database": {"title": "Pay/Transfer"}},
        ]
    }
    
    # Chiamiamo SENZA template_page_id per forzare S2
    discovered = NotionFinanceClient.discover_databases("fake_token")
    
    assert len(discovered) == 7
    assert discovered["expense_db_id"] == "exp_id"
    assert mock_instance.search.called

def test_discover_databases_strategy_3(mock_notion_client):
    """Test Strategia 3: Ricerca manuale per nome dei database (data_source)."""
    mock_instance = mock_notion_client.return_value
    
    # Simuliamo che S2 fallisca (nessuna pagina trovata o blocchi vuoti)
    # mock_instance.search.side_effect = ... (usiamo side_effect per gestire più chiamate)
    
    def side_effect_search(query=None, **kwargs):
        if query in ["Finance Tracker", "Dashboard", "Traky"]:
            return {"results": []} # S2 fallisce
        
        # S3 cerca per nome singolo
        mapping = {
            "Expense": "exp_id",
            "Income": "inc_id",
            "Categories": "cat_id",
            "Monthly Balance": "mb_id",
            "Accounts": "acc_id",
            "Subscriptions": "sub_id",
            "Pay": "pay_id"
        }
        if query in mapping:
            return {
                "results": [
                    {
                        "object": "data_source", 
                        "id": mapping[query], 
                        "title": [{"plain_text": query}]
                    }
                ]
            }
        return {"results": []}

    mock_instance.search.side_effect = side_effect_search
    
    discovered = NotionFinanceClient.discover_databases("fake_token")
    
    assert len(discovered) == 7
    assert discovered["expense_db_id"] == "exp_id"
    assert discovered["categories_db_id"] == "cat_id"
