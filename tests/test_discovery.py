import sys
import os
from unittest.mock import MagicMock, patch

# Aggiungiamo src al path per importare notion_client
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from src.notion_client import NotionFinanceClient

def test_strategia_1_virgin_account():
    print("--- Esecuzione Test Automatico: STRATEGIA 1 (Utente Vergine con Template) ---")
    
    # Dati fittizi simulating il block list di Notion per la Master Page
    mock_blocks = {
        "results": [
            {"type": "child_database", "id": "exp_id", "child_database": {"title": "Expense"}},
            {"type": "child_database", "id": "inc_id", "child_database": {"title": "Income"}},
            {"type": "child_database", "id": "cat_id", "child_database": {"title": "Categories"}},
            {"type": "child_database", "id": "mb_id", "child_database": {"title": "Monthly Balance"}},
            {"type": "child_database", "id": "acc_id", "child_database": {"title": "Accounts"}},
            {"type": "child_database", "id": "sub_id", "child_database": {"title": "Subscriptions"}},
            {"type": "child_database", "id": "pay_id", "child_database": {"title": "Pay/Transfer"}},
            {"type": "paragraph", "id": "random_id", "paragraph": {"text": "bla bla"}}
        ]
    }

    # Patchiamo l'inizializzazione del Client di notion-client in modo che non faccia chiamate HTTP vere
    with patch("notion_client.Client") as MockClient:
        # Configuriamo il finto client per restituire i blocchi
        mock_instance = MockClient.return_value
        mock_instance.blocks.children.list.return_value.get.return_value = mock_blocks["results"]

        # 1. L'utente arriva dall'OAuth con il suo duplicated_template_id!
        fake_template_id = "page_123456789"
        
        # 2. Eseguiamo la funzione
        discovered = NotionFinanceClient.discover_databases(
            access_token="fake_token", 
            template_page_id=fake_template_id
        )

        # 3. Verifichiamo i risultati attesi come Assertions
        assert "expense_db_id" in discovered
        assert discovered["expense_db_id"] == "exp_id"
        assert discovered["categories_db_id"] == "cat_id"
        assert len(discovered) == 7
        
        print("✅ TEST SUPERATO: Il sistema ha letto tutti i 7 DB figli diretti dal duplicated_template_id bypassando ogni altra ricerca complessa!")
        print("Dizionario restituito:", discovered)


if __name__ == "__main__":
    try:
        test_strategia_1_virgin_account()
    except AssertionError as e:
        print("❌ TEST FALLITO:", e)
