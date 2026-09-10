"""
tests/test_mistral_client_plan_generation.py — Copertura dedicata per la selezione del
modello Mistral nelle funzioni generative (report mensile, piani settimanale/mensile,
categorie lifestyle) e per `_normalize_usage_metadata`.

Contesto: `Config.MISTRAL_SMALL_MODEL` è a 0 req/min sul piano Free attuale, quindi
tutte le funzioni generative di `mistral_client.py` sono state spostate su
`Config.MISTRAL_EXPENSE_PARSER_MODEL`. `_normalize_usage_metadata` non deve più
hardcodare `Config.MISTRAL_SMALL_MODEL` nel dict di usage: il ledger dei costi/token
fa lookup del prezzo per nome modello (`UserStore.finalize_llm_usage`), quindi un
valore sbagliato attribuirebbe il costo al modello errato.

Nessuna chiamata reale a Mistral: mocka `self._client.chat.complete`.
"""

import pytest
from unittest.mock import MagicMock, patch

from config import Config
from src.mistral_client import MistralClient, _normalize_usage_metadata

pytestmark = pytest.mark.unit


def _make_response(content: str, prompt_tokens: int = 10, completion_tokens: int = 20):
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    response.usage = MagicMock(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    return response


class TestNormalizeUsageMetadataModelParam:
    """`model` deve essere propagato nel dict, non hardcodato."""

    def test_defaults_to_mistral_small_model_when_not_passed(self):
        response = _make_response("qualsiasi")
        usage = _normalize_usage_metadata(response)
        assert usage["model"] == Config.MISTRAL_SMALL_MODEL

    def test_propagates_explicit_model_argument(self):
        response = _make_response("qualsiasi")
        usage = _normalize_usage_metadata(response, model=Config.MISTRAL_EXPENSE_PARSER_MODEL)
        assert usage["model"] == Config.MISTRAL_EXPENSE_PARSER_MODEL
        assert usage["model"] != Config.MISTRAL_SMALL_MODEL

    def test_propagates_arbitrary_model_string(self):
        """Nessun accoppiamento a un set fisso di modelli noti: qualunque stringa passata
        deve finire tale e quale nel dict, a garanzia che il ledger non venga corrotto."""
        response = _make_response("qualsiasi")
        usage = _normalize_usage_metadata(response, model="un-modello-futuro-qualsiasi")
        assert usage["model"] == "un-modello-futuro-qualsiasi"

    def test_returns_empty_dict_when_no_usage_regardless_of_model(self):
        response = MagicMock()
        response.usage = None
        usage = _normalize_usage_metadata(response, model=Config.MISTRAL_EXPENSE_PARSER_MODEL)
        assert usage == {}


class TestGenerateWeeklyPlanUsesExpenseParserModel:
    def test_calls_chat_complete_with_expense_parser_model(self):
        with patch.object(MistralClient, "__init__", lambda self: None):
            client = MistralClient()
            client._client = MagicMock()
            client._client.chat.complete.return_value = _make_response(
                '{"tips": ["Consiglio di test"]}'
            )
            client.generate_weekly_plan("dati piano", "01/09 → 07/09")

        _, kwargs = client._client.chat.complete.call_args
        assert kwargs["model"] == Config.MISTRAL_EXPENSE_PARSER_MODEL
        assert kwargs["model"] != Config.MISTRAL_SMALL_MODEL

    def test_usage_metadata_reports_expense_parser_model(self):
        with patch.object(MistralClient, "__init__", lambda self: None):
            client = MistralClient()
            client._client = MagicMock()
            client._client.chat.complete.return_value = _make_response(
                '{"tips": ["Consiglio di test"]}'
            )
            _, usage = client.generate_weekly_plan("dati piano", "01/09 → 07/09")

        assert usage["model"] == Config.MISTRAL_EXPENSE_PARSER_MODEL
        assert usage["model"] != Config.MISTRAL_SMALL_MODEL


class TestGenerateMonthlyPlanUsesExpenseParserModel:
    def test_calls_chat_complete_with_expense_parser_model(self):
        with patch.object(MistralClient, "__init__", lambda self: None):
            client = MistralClient()
            client._client = MagicMock()
            client._client.chat.complete.return_value = _make_response(
                '{"tips": ["Consiglio di test"]}'
            )
            client.generate_monthly_plan("dati piano", "Settembre 2026")

        _, kwargs = client._client.chat.complete.call_args
        assert kwargs["model"] == Config.MISTRAL_EXPENSE_PARSER_MODEL
        assert kwargs["model"] != Config.MISTRAL_SMALL_MODEL

    def test_usage_metadata_reports_expense_parser_model(self):
        with patch.object(MistralClient, "__init__", lambda self: None):
            client = MistralClient()
            client._client = MagicMock()
            client._client.chat.complete.return_value = _make_response(
                '{"tips": ["Consiglio di test"]}'
            )
            _, usage = client.generate_monthly_plan("dati piano", "Settembre 2026")

        assert usage["model"] == Config.MISTRAL_EXPENSE_PARSER_MODEL
        assert usage["model"] != Config.MISTRAL_SMALL_MODEL


class TestAnalyzeAndGenerateReportUsesExpenseParserModel:
    """Aggiornato: anche il report mensile è stato spostato su
    MISTRAL_EXPENSE_PARSER_MODEL (MISTRAL_SMALL_MODEL è a 0 req/min sul piano Free),
    allineandosi a generate_weekly_plan/generate_monthly_plan."""

    def test_calls_chat_complete_with_expense_parser_model(self):
        with patch.object(MistralClient, "__init__", lambda self: None):
            client = MistralClient()
            client._client = MagicMock()
            client._client.chat.complete.return_value = _make_response(
                '{"trend_paragraphs": ["Paragrafo di test"], "tips": ["Consiglio di test"]}'
            )
            client.analyze_and_generate_report(
                data_text="dati",
                accounts_text="conti",
                forecast_text="previsione",
                current_month_label="Settembre 2026",
                next_month_label="Ottobre 2026",
                total_income="1000",
                total_amount="500",
                total_accounts_balance="2000",
            )

        _, kwargs = client._client.chat.complete.call_args
        assert kwargs["model"] == Config.MISTRAL_EXPENSE_PARSER_MODEL
        assert kwargs["model"] != Config.MISTRAL_SMALL_MODEL

    def test_usage_metadata_reports_expense_parser_model(self):
        with patch.object(MistralClient, "__init__", lambda self: None):
            client = MistralClient()
            client._client = MagicMock()
            client._client.chat.complete.return_value = _make_response(
                '{"trend_paragraphs": ["Paragrafo di test"], "tips": ["Consiglio di test"]}'
            )
            _, usage = client.analyze_and_generate_report(
                data_text="dati",
                accounts_text="conti",
                forecast_text="previsione",
                current_month_label="Settembre 2026",
                next_month_label="Ottobre 2026",
                total_income="1000",
                total_amount="500",
                total_accounts_balance="2000",
            )

        assert usage["model"] == Config.MISTRAL_EXPENSE_PARSER_MODEL
        assert usage["model"] != Config.MISTRAL_SMALL_MODEL


class TestGenerateLifestyleCategoriesUsesExpenseParserModel:
    """generate_lifestyle_categories non traccia usage/ledger (nessuna chiamata a
    _normalize_usage_metadata), ma il modello passato a chat.complete deve comunque
    essere MISTRAL_EXPENSE_PARSER_MODEL, non MISTRAL_SMALL_MODEL."""

    def test_calls_chat_complete_with_expense_parser_model(self):
        with patch.object(MistralClient, "__init__", lambda self: None):
            client = MistralClient()
            client._client = MagicMock()
            client._client.chat.complete.return_value = _make_response(
                '["Alimentari", "Ristoranti"]'
            )
            client.generate_lifestyle_categories({"transport": "auto"})

        _, kwargs = client._client.chat.complete.call_args
        assert kwargs["model"] == Config.MISTRAL_EXPENSE_PARSER_MODEL
        assert kwargs["model"] != Config.MISTRAL_SMALL_MODEL
