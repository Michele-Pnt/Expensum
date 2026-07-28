"""
tests/test_mistral_client_category_description.py — Sintesi LLM one-shot della
descrizione categoria (MistralClient.synthesize_category_description).

Nessuna chiamata reale a Mistral: mocka `self._client.chat.complete`.
"""

import pytest
from unittest.mock import MagicMock, patch

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

    def test_falls_back_to_truncated_raw_on_llm_failure(self):
        with patch.object(MistralClient, "__init__", lambda self: None):
            client = MistralClient()
            client._client = MagicMock()
            client._client.chat.complete.side_effect = RuntimeError("rate limited")
            result = client.synthesize_category_description("sigarette e liquidi da svapo")
        assert result == "sigarette e liquidi da svapo"

    def test_falls_back_to_truncated_raw_on_empty_response(self):
        with patch.object(MistralClient, "__init__", lambda self: None):
            client = MistralClient()
            client._client = MagicMock()
            client._client.chat.complete.return_value = _make_response("")
            result = client.synthesize_category_description("descrizione originale")
        assert result == "descrizione originale"


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
