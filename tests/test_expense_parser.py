import pytest
from unittest.mock import patch
from src.expense_parser import ExpenseParser
from datetime import date

pytestmark = pytest.mark.unit

def test_expense_parser_logic_with_mocked_gemini():
    """
    Test del parser di spese con Gemini mockato.
    """
    categories = ["Cibo", "Trasporti", "Divertimento"]

    with patch.object(
        ExpenseParser,
        "_call_gemini",
        return_value='{"type": "expense", "amount": 10.5, "category": "Cibo", "name": "Pizza", "date": "2026-03-25"}',
    ):
        parser = ExpenseParser(categories)
        res = parser.parse("Ho speso 10.50 euro per una pizza ieri")

        assert res is not None
        assert res["amount"] == 10.5
        assert res["category"] == "Cibo"
        assert res["name"] == "Pizza"

def test_extract_json_robustness():
    """Testa se la funzione interna _extract_json è in grado di pulire l'output dell'AI."""
    from src.expense_parser import _extract_json
    
    dirty_json = "Ecco il risultato:\n```json\n{\"amount\": 10, \"name\": \"Test\"}\n```\nSpero sia utile."
    res = _extract_json(dirty_json)
    assert res["amount"] == 10
    assert res["name"] == "Test"

def test_extreme_parser_inputs():
    """Test con input estremi: emoji, caratteri rari, importi enormi."""
    from src.expense_parser import _extract_json
    
    # 1. Emoji e caratteri speciali nel JSON finto dell'AI
    emoji_json = '{"type": "expense", "amount": 50.0, "category": "Cibo", "name": "Sushi 🍣 Buffet 🔥", "date": "2026-03-25"}'
    res = _extract_json(emoji_json)
    assert res["name"] == "Sushi 🍣 Buffet 🔥"

    # 2. Numeri enormi (Overflow check)
    large_num_json = '{"type": "expense", "amount": 9999999999.99, "category": "Investimenti", "name": "Yacht", "date": "2026-03-25"}'
    res = _extract_json(large_num_json)
    assert res["amount"] == 9999999999.99

def test_normalization_extreme_cases():
    """Testa la robustezza della normalizzazione dei dati."""
    categories = ["Supermercato", "Ristoranti", "Affitto"]
    parser = ExpenseParser(categories)
    
    # Caso 1: Categoria scritta male (Fuzzy Matching)
    # Ristoranti -> Ristorante (dovrebbe matchare)
    bad_data = {"type": "expense", "amount": 25.5, "category": "ristorante", "name": "Cena", "date": "2026-03-25"}
    normalized = parser._normalize(bad_data, date(2026, 3, 25))
    assert normalized["category"] == "Ristoranti" # Matchato correttamente

    # Caso 2: Importo come stringa sporca
    bad_data = {"type": "expense", "amount": "1.234,56", "category": "Affitto", "name": "Test", "date": "2026-03-25"}
    # Nota: il parser attuale prova a fare float(), che fallirebbe su "1.234,56" 
    # Questo test serve a documentare il limite attuale o verificare fix futuri
    normalized = parser._normalize(bad_data, date(2026, 3, 25))
    # Il codice attuale restituisce None se float() fallisce.
    
    # Caso 3: Campi mancanti o null
    minimal_data = {"type": "expense", "amount": None, "category": None, "name": None}
    normalized = parser._normalize(minimal_data, date(2026, 3, 25))
    assert normalized["name"] == "Spesa" # Default value
    assert normalized["amount"] is None

def test_extract_json_garbage():
    """Testa cosa succede se l'AI risponde con spazzatura totale."""
    from src.expense_parser import _extract_json
    
    assert _extract_json("Spiacente, non posso aiutarti.") is None
    assert _extract_json("--- { 'not': 'valid' } ---") is None
    assert _extract_json("") is None
