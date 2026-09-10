"""
tests/test_mistral_client_category_description.py — Sintesi LLM one-shot della
descrizione categoria (MistralClient.synthesize_category_description) e generazione
descrizione per categorie auto-promosse (generate_category_description_from_name).

Nessuna chiamata reale a Mistral: mocka `self._client.chat.complete`. Entrambe le
funzioni non chiamano `_normalize_usage_metadata` (nessun tracking usage/ledger), ma
il modello passato a `chat.complete` deve comunque essere MISTRAL_EXPENSE_PARSER_MODEL
(vedi tests/test_mistral_client_plan_generation.py per il contesto dello spostamento).
"""

import pytest
from unittest.mock import MagicMock, patch

from config import Config
from src.mistral_client import MistralClient

pytestmark = pytest.mark.unit


def _make_response(content: str):
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    return response


class TestSynthesizeCategoryDescription:
    def test_returns_synthesized_text_on_success(self):
        with patch.object(MistralClient, "__init__", lambda self: None):
            client = MistralClient()
            client._client = MagicMock()
            client._client.chat.complete.return_value = _make_response(
                "Spese per uscire a cena o pranzo fuori casa"
            )
            result = client.synthesize_category_description(
                "spese fatte per uscire fuori a cena o pranzo"
            )
        assert result == "Spese per uscire a cena o pranzo fuori casa"

    def test_calls_chat_complete_with_expense_parser_model(self):
        with patch.object(MistralClient, "__init__", lambda self: None):
            client = MistralClient()
            client._client = MagicMock()
            client._client.chat.complete.return_value = _make_response(
                "Spese per uscire a cena o pranzo fuori casa"
            )
            client.synthesize_category_description("descrizione originale")

        _, kwargs = client._client.chat.complete.call_args
        assert kwargs["model"] == Config.MISTRAL_EXPENSE_PARSER_MODEL
        assert kwargs["model"] != Config.MISTRAL_SMALL_MODEL

    def test_keeps_raw_text_out_of_prompt_context_on_llm_failure(self):
        with patch.object(MistralClient, "__init__", lambda self: None):
            client = MistralClient()
            client._client = MagicMock()
            client._client.chat.complete.side_effect = RuntimeError("rate limited")
            result = client.synthesize_category_description("sigarette e liquidi da svapo")
        assert result is None

    def test_keeps_raw_text_out_of_prompt_context_on_empty_response(self):
        with patch.object(MistralClient, "__init__", lambda self: None):
            client = MistralClient()
            client._client = MagicMock()
            client._client.chat.complete.return_value = _make_response("")
            result = client.synthesize_category_description("descrizione originale")
        assert result is None


class TestGenerateCategoryDescriptionFromName:
    """Categorie auto-promosse (category_matcher._promote_candidate): nessun testo
    utente da cui partire, solo il nome — vedi generate_category_description_from_name."""

    def test_returns_generated_text_on_success(self):
        with patch.object(MistralClient, "__init__", lambda self: None):
            client = MistralClient()
            client._client = MagicMock()
            client._client.chat.complete.return_value = _make_response(
                "Spese per caffè e bevande al bar"
            )
            result = client.generate_category_description_from_name("Cappuccino")
        assert result == "Spese per caffè e bevande al bar"

    def test_calls_chat_complete_with_expense_parser_model(self):
        with patch.object(MistralClient, "__init__", lambda self: None):
            client = MistralClient()
            client._client = MagicMock()
            client._client.chat.complete.return_value = _make_response(
                "Spese per caffè e bevande al bar"
            )
            client.generate_category_description_from_name("Cappuccino")

        _, kwargs = client._client.chat.complete.call_args
        assert kwargs["model"] == Config.MISTRAL_EXPENSE_PARSER_MODEL
        assert kwargs["model"] != Config.MISTRAL_SMALL_MODEL

    def test_returns_none_on_llm_failure(self):
        """A differenza di synthesize_category_description, qui non c'è un testo
        originale su cui ripiegare: il fallback è None, non una stringa troncata."""
        with patch.object(MistralClient, "__init__", lambda self: None):
            client = MistralClient()
            client._client = MagicMock()
            client._client.chat.complete.side_effect = RuntimeError("rate limited")
            result = client.generate_category_description_from_name("Cappuccino")
        assert result is None

    def test_returns_none_on_empty_response(self):
        with patch.object(MistralClient, "__init__", lambda self: None):
            client = MistralClient()
            client._client = MagicMock()
            client._client.chat.complete.return_value = _make_response("")
            result = client.generate_category_description_from_name("Cappuccino")
        assert result is None
