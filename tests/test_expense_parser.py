import pytest
from unittest.mock import patch
from src.expense_parser import ExpenseParser
from datetime import date

pytestmark = pytest.mark.unit

def test_expense_parser_logic_with_mocked_mistral():
    """
    Test del parser di spese con Mistral mockato.
    """
    categories = ["Cibo", "Trasporti", "Divertimento"]

    with patch.object(
        ExpenseParser,
        "_call_mistral",
        return_value=(
            '{"type": "expense", "amount": 10.5, "category": "Cibo", "name": "Pizza", "date": "2026-03-25"}',
            {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "provider": "mistral", "model": "mistral-small-latest"},
        ),
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

def test_parse_multi_with_usage_single_transaction_no_wrapper():
    """Se l'LLM rileva una sola transazione, risponde con l'oggetto singolo (senza wrapper)."""
    categories = ["Cibo", "Trasporti"]

    with patch.object(
        ExpenseParser,
        "_call_mistral",
        return_value=(
            '{"type": "expense", "amount": 10.5, "category": "Cibo", "income_type": null, "name": "Pizza", "date": "2026-03-25"}',
            {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "provider": "mistral", "model": "mistral-small-latest"},
        ),
    ):
        parser = ExpenseParser(categories)
        results, usage = parser.parse_multi_with_usage("Ho speso 10.50 euro per una pizza")

        assert results is not None
        assert len(results) == 1
        assert results[0]["amount"] == 10.5
        assert results[0]["name"] == "Pizza"
        assert usage["provider"] == "mistral"


def test_parse_multi_with_usage_multiple_transactions():
    """Se l'LLM rileva più transazioni, risponde con il wrapper 'transactions' e ognuna viene normalizzata."""
    categories = ["Cibo", "Trasporti", "Bar"]

    raw_response = """{"transactions": [
        {"type": "expense", "amount": 10.0, "category": "Cibo", "income_type": null, "name": "Pranzo", "date": "2026-04-09"},
        {"type": "expense", "amount": 20.0, "category": "Trasporti", "income_type": null, "name": "Benzina", "date": "2026-04-09"},
        {"type": "expense", "amount": 5.0, "category": "Bar", "income_type": null, "name": "Caffe", "date": "2026-04-09"}
    ]}"""

    with patch.object(
        ExpenseParser,
        "_call_mistral",
        return_value=(
            raw_response,
            {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "provider": "mistral", "model": "mistral-small-latest"},
        ),
    ):
        parser = ExpenseParser(categories)
        results, usage = parser.parse_multi_with_usage(
            "Ho speso 10 euro per il pranzo, 20 di benzina e 5 di caffè ieri"
        )

        assert results is not None
        assert len(results) == 3
        assert [r["amount"] for r in results] == [10.0, 20.0, 5.0]
        assert [r["name"] for r in results] == ["Pranzo", "Benzina", "Caffe"]
        assert all(r["date"] == date(2026, 4, 9) for r in results)


def test_parse_multi_with_usage_not_an_expense():
    """Se il messaggio non è una transazione, restituisce None (comportamento invariato)."""
    with patch.object(
        ExpenseParser,
        "_call_mistral",
        return_value=('{"error": "not_expense"}', {}),
    ):
        parser = ExpenseParser(["Cibo"])
        results, _usage = parser.parse_multi_with_usage("ciao come stai")
        assert results is None


def test_parses_transfer_with_both_accounts():
    """Un trasferimento con conto origine e destinazione espliciti viene riconosciuto come tale."""
    with patch.object(
        ExpenseParser,
        "_call_mistral",
        return_value=(
            '{"type": "transfer", "amount": 100.0, "category": null, "income_type": null, '
            '"name": "Trasferimento", "date": "2026-03-22", '
            '"from_account": "conto corrente", "to_account": "conto risparmio"}',
            {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "provider": "mistral", "model": "mistral-small-latest"},
        ),
    ):
        parser = ExpenseParser([])
        res = parser.parse("sposta 100 euro dal conto corrente al conto risparmio")

        assert res is not None
        assert res["type"] == "transfer"
        assert res["amount"] == 100.0
        assert res["from_account"] == "conto corrente"
        assert res["to_account"] == "conto risparmio"
        assert res["category"] is None
        assert res["income_type"] is None


def test_parses_transfer_with_missing_from_account():
    """Se l'utente non menziona il conto di origine, from_account resta None."""
    with patch.object(
        ExpenseParser,
        "_call_mistral",
        return_value=(
            '{"type": "transfer", "amount": 300.0, "category": null, "income_type": null, '
            '"name": "Bonifico interno", "date": "2026-03-22", '
            '"from_account": null, "to_account": "conto risparmio"}',
            {},
        ),
    ):
        parser = ExpenseParser([])
        res = parser.parse("bonifico interno 300 euro verso il conto risparmio")

        assert res["type"] == "transfer"
        assert res["from_account"] is None
        assert res["to_account"] == "conto risparmio"


def test_expense_and_income_have_null_account_hints():
    """Per spesa/entrata from_account e to_account restano sempre None."""
    with patch.object(
        ExpenseParser,
        "_call_mistral",
        return_value=(
            '{"type": "expense", "amount": 10.0, "category": "Cibo", "income_type": null, '
            '"name": "Pizza", "date": "2026-03-25"}',
            {},
        ),
    ):
        parser = ExpenseParser(["Cibo"])
        res = parser.parse("pizza 10 euro")

        assert res["from_account"] is None
        assert res["to_account"] is None


def test_extract_json_garbage():
    """Testa cosa succede se l'AI risponde con spazzatura totale."""
    from src.expense_parser import _extract_json
    
    assert _extract_json("Spiacente, non posso aiutarti.") is None
    assert _extract_json("--- { 'not': 'valid' } ---") is None
    assert _extract_json("") is None
