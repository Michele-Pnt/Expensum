import os

import pytest

from config import Config
from src.expense_parser import ExpenseParser

pytestmark = pytest.mark.gemini_live


def test_expense_parser_live_gemini_smoke():
    """Smoke test opzionale per Gemini, eseguito solo in sede separata."""
    if os.getenv("RUN_GEMINI_LIVE_TESTS") != "1":
        pytest.skip("Gemini live smoke test disabilitato per la suite standard")
    if not Config.GEMINI_API_KEY:
        pytest.skip("GEMINI_API_KEY mancante per il smoke test Gemini live")

    parser = ExpenseParser(["Cibo", "Trasporti", "Divertimento"])

    result = parser.parse("15 euro per il taxi")

    assert result is not None
    assert result["type"] == "expense"
    assert result["amount"] == 15.0
    assert "taxi" in result["name"].lower()