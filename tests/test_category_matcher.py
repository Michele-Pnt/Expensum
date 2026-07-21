"""
tests/test_category_matcher.py — Unit test per la logica pura di categorizzazione
adattiva (normalizzazione, scoring). Nessuna dipendenza da DB/SQLAlchemy: le funzioni
testate qui non aprono sessioni né toccano `category_candidates`.
"""

import pytest

from src.category_matcher import (
    compute_historical_score,
    compute_llm_confidence,
    normalize_event_name,
    score_categorization,
)

pytestmark = pytest.mark.unit


class TestNormalizeEventName:
    def test_lowercase_and_strip(self):
        assert normalize_event_name("  Pizza Mario  ") == "pizza mario"

    def test_removes_punctuation(self):
        assert normalize_event_name("Pizza, Mario!!") == "pizza mario"

    def test_collapses_multiple_spaces(self):
        assert normalize_event_name("Pizza    Mario") == "pizza mario"

    def test_removes_purely_numeric_tokens(self):
        assert normalize_event_name("Pizza Mario 2") == "pizza mario"

    def test_keeps_alphanumeric_tokens(self):
        # Un token misto lettere+numeri non va scartato, solo quelli puramente numerici
        assert normalize_event_name("Sky Q4") == "sky q4"

    def test_empty_input(self):
        assert normalize_event_name("") == ""
        assert normalize_event_name(None) == ""


class TestComputeLlmConfidence:
    def test_exact_match_scores_one(self):
        score = compute_llm_confidence("Cibo", ["Cibo", "Trasporti"])
        assert score == 1.0

    def test_case_insensitive_exact_match(self):
        score = compute_llm_confidence("cibo", ["Cibo", "Trasporti"])
        assert score == 1.0

    def test_fuzzy_match_scores_between_zero_and_one(self):
        score = compute_llm_confidence("ristorante", ["Ristoranti", "Trasporti"])
        assert 0.0 < score < 1.0

    def test_no_match_scores_zero(self):
        score = compute_llm_confidence("Criptovalute", ["Cibo", "Trasporti"])
        assert score == 0.0

    def test_none_category_scores_zero(self):
        assert compute_llm_confidence(None, ["Cibo"]) == 0.0

    def test_no_known_categories_scores_zero(self):
        assert compute_llm_confidence("Cibo", []) == 0.0


class TestComputeHistoricalScore:
    def test_empty_normalized_name_short_circuits_without_querying_db(self):
        # Nessuna sessione reale necessaria: il ramo su nome vuoto ritorna prima
        # di toccare `session`, quindi None è un valore sicuro per questo test.
        score, candidate = compute_historical_score(None, "any_user", "")
        assert score == 0.0
        assert candidate is None


class TestScoreCategorization:
    def test_default_weights_are_fifty_fifty(self):
        assert score_categorization(1.0, 0.0) == 0.5
        assert score_categorization(0.0, 1.0) == 0.5
        assert score_categorization(1.0, 1.0) == 1.0
        assert score_categorization(0.0, 0.0) == 0.0

    def test_custom_weights(self):
        score = score_categorization(1.0, 0.0, weight_llm=0.7, weight_historical=0.3)
        assert score == pytest.approx(0.7)

    def test_only_llm_signal(self):
        score = score_categorization(0.8, 0.4, weight_llm=1.0, weight_historical=0.0)
        assert score == pytest.approx(0.8)

    def test_only_historical_signal(self):
        score = score_categorization(0.8, 0.4, weight_llm=0.0, weight_historical=1.0)
        assert score == pytest.approx(0.4)

    def test_clamped_to_zero_one_range(self):
        # Pesi/valori fuori range non devono produrre uno score fuori [0, 1]
        assert score_categorization(1.0, 1.0, weight_llm=0.9, weight_historical=0.9) == 1.0
        assert score_categorization(0.0, 0.0, weight_llm=-1.0, weight_historical=-1.0) == 0.0
