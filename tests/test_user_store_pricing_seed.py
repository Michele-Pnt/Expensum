"""
tests/test_user_store_pricing_seed.py — Copertura dedicata per
UserStore._seed_default_pricing.

Nessun test esistente verificava questo metodo (era coperto solo implicitamente
tramite l'inizializzazione di UserStore in altri test, senza asserzioni dirette
sulle righe di pricing create). Verifica: creazione di tutte le righe attese
(inclusi i modelli parser spese configurabili via env), valori di costo corretti,
e non-sovrascrittura al secondo avvio (niente righe duplicate né valid_to popolato).

Tier integration: richiede un engine SQLite reale (create_all + query), non solo
mock in-memory di puro Python.
"""

import pytest

from config import Config
from src.user_store import LlmPricing, UserStore

pytestmark = pytest.mark.integration


@pytest.fixture
def store():
    """UserStore su SQLite in-memory, inizializzazione completa (incluso seed)."""
    return UserStore("sqlite:///:memory:")


def _pricing_row(store: UserStore, provider: str, model: str) -> LlmPricing | None:
    with store.Session() as session:
        return (
            session.query(LlmPricing)
            .filter(LlmPricing.provider == provider, LlmPricing.model == model)
            .first()
        )


class TestSeedDefaultPricing:
    def test_creates_row_for_expense_parser_primary_model(self, store):
        row = _pricing_row(store, "mistral", Config.MISTRAL_EXPENSE_PARSER_MODEL)
        assert row is not None
        assert float(row.input_cost_per_1k) == pytest.approx(0.0002)
        assert float(row.output_cost_per_1k) == pytest.approx(0.0002)
        assert row.valid_to is None

    def test_creates_row_for_expense_parser_fallback_model(self, store):
        row = _pricing_row(store, "mistral", Config.MISTRAL_EXPENSE_PARSER_FALLBACK_MODEL)
        assert row is not None
        assert float(row.input_cost_per_1k) == pytest.approx(0.00015)
        assert float(row.output_cost_per_1k) == pytest.approx(0.00015)
        assert row.valid_to is None

    def test_still_creates_legacy_small_and_large_rows(self, store):
        assert _pricing_row(store, "mistral", Config.MISTRAL_SMALL_MODEL) is not None
        assert _pricing_row(store, "mistral", Config.MISTRAL_LARGE_MODEL) is not None

    def test_does_not_duplicate_rows_on_repeated_seed(self, store):
        # _seed_default_pricing gira già una volta in __init__; lo richiamiamo a mano
        # per simulare un secondo avvio del processo (restart bot/dashboard).
        store._seed_default_pricing()
        with store.Session() as session:
            count = (
                session.query(LlmPricing)
                .filter(
                    LlmPricing.provider == "mistral",
                    LlmPricing.model == Config.MISTRAL_EXPENSE_PARSER_MODEL,
                )
                .count()
            )
        assert count == 1

    def test_does_not_overwrite_manually_edited_pricing(self, store):
        # Se un admin corregge manualmente il prezzo (es. listino aggiornato), il
        # seed successivo non deve resettarlo: filtra su valid_to IS NULL e fa
        # skip se trova già una riga attiva.
        with store.Session() as session:
            row = (
                session.query(LlmPricing)
                .filter(
                    LlmPricing.provider == "mistral",
                    LlmPricing.model == Config.MISTRAL_EXPENSE_PARSER_MODEL,
                )
                .first()
            )
            row.input_cost_per_1k = 0.0009
            session.commit()

        store._seed_default_pricing()

        with store.Session() as session:
            row = (
                session.query(LlmPricing)
                .filter(
                    LlmPricing.provider == "mistral",
                    LlmPricing.model == Config.MISTRAL_EXPENSE_PARSER_MODEL,
                )
                .first()
            )
            assert float(row.input_cost_per_1k) == pytest.approx(0.0009)
