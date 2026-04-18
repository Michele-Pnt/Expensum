import pytest
from unittest.mock import patch, MagicMock
from src.expense_parser import ExpenseParser
from datetime import date

def test_expense_parser_logic_with_real_ai_option(use_real_ai):
    """
    Test del parser di spese. 
    Se lanciato con --real-ai (pytest --real-ai), interroga l'AI vera.
    Altrimenti usa un mock pre-configurato.
    """
    categories = ["Cibo", "Trasporti", "Divertimento"]
    
    if not use_real_ai:
        # --- MODALITÀ MOCK ---
        # Mocking della chiamata all'AI (Gemini o Ollama a seconda della config)
        with patch.object(ExpenseParser, '_call_gemini', return_value='{"type": "expense", "amount": 10.5, "category": "Cibo", "name": "Pizza", "date": "2026-03-25"}'), \
             patch.object(ExpenseParser, '_call_ollama', return_value='{"type": "expense", "amount": 10.5, "category": "Cibo", "name": "Pizza", "date": "2026-03-25"}'):
            
            parser = ExpenseParser(categories)
            res = parser.parse("Ho speso 10.50 euro per una pizza ieri")
            
            assert res is not None
            assert res["amount"] == 10.5
            assert res["category"] == "Cibo"
            assert res["name"] == "Pizza"
    else:
        # --- MODALITÀ REALE (Interroghiamo AI) ---
        # Assicurati di avere GEMINI_API_KEY nel tuo .env!
        parser = ExpenseParser(categories)
        
        # Test 1: Spesa semplice
        res = parser.parse("15 euro per il taxi")
        assert res is not None
        assert res["type"] == "expense"
        assert res["amount"] == 15.0
        # Il nome può variare a seconda dell'AI ma dovrebbe contenere 'Taxi'
        assert "taxi" in res["name"].lower()
        
        # Test 2: Entrata
        res = parser.parse("ho ricevuto un rimborso di 50 euro")
        assert res is not None
        assert res["type"] == "income"
        assert res["amount"] == 50.0

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
