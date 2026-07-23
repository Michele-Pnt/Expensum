"""
tests/test_category_candidates_integration.py — Integration test per la
categorizzazione adattiva (src/category_matcher.py).

Usa un file SQLite temporaneo (non `:memory:`): `category_matcher.evaluate_and_track`
scrive su una sessione locale mentre `UserStore.upsert_user_categories` (chiamato in
fase di promozione) ne apre una propria — serve un vero file condiviso, non una singola
connessione `:memory:`, per riprodurre fedelmente l'interazione multi-sessione che si
verifica in produzione (bot.py apre una sessione dedicata, UserStore le sue).
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config import Config
from src import category_matcher
from src.storage.base import FinancialStorage
from src.storage.models import CategoryCandidate, UserCategory
from src.user_store import Base, User, UserStore

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_path(tmp_path_factory):
    return str(tmp_path_factory.mktemp("category_candidates") / "test.db")


@pytest.fixture(scope="module")
def db_engine(db_path):
    """Engine SQLite su file condiviso per tutto il modulo."""
    engine = create_engine(f"sqlite:///{db_path}")
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """Schema azzerato e utente di test reinserito a ogni test."""
    Base.metadata.drop_all(db_engine)
    Base.metadata.create_all(db_engine)
    Session = sessionmaker(bind=db_engine)
    session = Session()

    session.add(User(chat_id="test_user_1", username="testuser", is_active=True))
    session.commit()

    yield session
    session.close()


@pytest.fixture
def user_store(db_path, db_session):
    """UserStore sullo stesso file: le sue scritture (upsert_user_categories, in
    fase di promozione) devono essere visibili anche dalla sessione di test."""
    return UserStore(db_url=f"sqlite:///{db_path}")


@pytest.fixture
def mock_storage():
    """FinancialStorage mockato: isola il test dalla logica di storage reale
    (già coperta in test_postgres_storage.py), verificando solo che il matcher
    chiami create_category invece di toccare Notion/Postgres direttamente."""
    storage = MagicMock(spec=FinancialStorage)
    storage.create_category.side_effect = lambda name: {"id": 999, "name": name}
    return storage


@pytest.fixture(autouse=True)
def reset_thresholds(monkeypatch):
    """Soglie basse e deterministiche per velocizzare i test, indipendenti dai
    default di produzione in config.py."""
    monkeypatch.setattr(Config, "CATEGORY_PROMOTION_THRESHOLD", 3)
    monkeypatch.setattr(Config, "CATEGORY_PROMOTION_WINDOW_DAYS", 90)
    monkeypatch.setattr(Config, "CATEGORY_MATCH_THRESHOLD", 0.70)
    monkeypatch.setattr(Config, "CATEGORY_CANDIDATE_CLUSTER_CUTOFF", 0.8)
    monkeypatch.setattr(Config, "CATEGORY_MATCH_WEIGHT_LLM", 0.5)
    monkeypatch.setattr(Config, "CATEGORY_MATCH_WEIGHT_HISTORY", 0.5)


def _evaluate(session, storage, user_store, raw_name, category_from_llm, known_categories=None):
    return category_matcher.evaluate_and_track(
        session, storage, user_store, "test_user_1",
        raw_name, category_from_llm, known_categories or ["Altro"],
        fallback_category_name="Altro",
    )


# ---------------------------------------------------------------------------
# 1. Ciclo completo: N occorrenze sotto soglia -> auto-creazione categoria
# ---------------------------------------------------------------------------

class TestPromotionCycle:
    def test_below_threshold_stays_on_fallback_and_tracks_occurrences(
        self, db_session, user_store, mock_storage,
    ):
        for _ in range(2):
            result = _evaluate(db_session, mock_storage, user_store, "Ciabatte", "Scarpe")
            assert result.category_name == "Altro"
            assert result.promoted is False

        mock_storage.create_category.assert_not_called()

        candidate = (
            db_session.query(CategoryCandidate)
            .filter_by(user_id="test_user_1", normalized_name="ciabatte")
            .one()
        )
        assert candidate.occurrences == 2
        assert candidate.status == "pending"

    def test_reaching_threshold_promotes_to_real_category(
        self, db_session, user_store, mock_storage,
    ):
        for _ in range(2):
            _evaluate(db_session, mock_storage, user_store, "Ciabatte", "Scarpe")

        result = _evaluate(db_session, mock_storage, user_store, "Ciabatte", "Scarpe")

        assert result.promoted is True
        assert result.category_name == "Ciabatte"
        mock_storage.create_category.assert_called_once_with("Ciabatte")

        candidate = (
            db_session.query(CategoryCandidate)
            .filter_by(user_id="test_user_1", normalized_name="ciabatte")
            .one()
        )
        assert candidate.status == "promoted"
        assert candidate.occurrences == 3
        assert candidate.promoted_category_id is not None

    def test_llm_proposing_the_fallback_itself_still_tracks_and_promotes(
        self, db_session, user_store, mock_storage,
    ):
        """Il parser sceglie sempre una categoria dalla lista nota (vincolo di prompt),
        quindi per una spesa sconosciuta propone il fallback stesso ("Altro") — un match
        esatto con confidenza 1.0 contro le categorie note. Senza l'eccezione nel gate
        primario di evaluate_and_track, questo bloccava il tracking per sempre: qualunque
        spesa sconosciuta restava su "Altro" a vita, mai promossa."""
        for _ in range(2):
            result = _evaluate(db_session, mock_storage, user_store, "Scorie radioattive", "Altro")
            assert result.category_name == "Altro"
            assert result.promoted is False

        result = _evaluate(db_session, mock_storage, user_store, "Scorie radioattive", "Altro")

        assert result.promoted is True
        assert result.category_name == "Scorie radioattive"
        mock_storage.create_category.assert_called_once_with("Scorie radioattive")

    def test_mirror_updated_immediately_after_promotion(
        self, db_session, user_store, mock_storage,
    ):
        """Regressione sul punto critico: senza l'upsert esplicito nel matcher, la
        categoria promossa resterebbe invisibile a _get_parser fino al sync notturno."""
        for _ in range(3):
            _evaluate(db_session, mock_storage, user_store, "Ciabatte", "Scarpe")

        names = user_store.get_user_category_names("test_user_1")
        assert "Ciabatte" in names

    def test_next_occurrence_after_promotion_matches_new_category_directly(
        self, db_session, user_store, mock_storage,
    ):
        for _ in range(3):
            _evaluate(db_session, mock_storage, user_store, "Ciabatte", "Scarpe")
        mock_storage.create_category.reset_mock()

        # Ora "Ciabatte" è tra le known_categories (come farebbe bot.py rileggendola
        # da user_store dopo la promozione)
        known = user_store.get_user_category_names("test_user_1")
        result = _evaluate(db_session, mock_storage, user_store, "Ciabatte", "Ciabatte", known_categories=known)

        assert result.category_name == "Ciabatte"
        assert result.promoted is False
        mock_storage.create_category.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Finestra temporale: occorrenze troppo distanziate non si sommano
# ---------------------------------------------------------------------------

class TestPromotionWindow:
    def test_occurrence_outside_window_resets_counter(self, db_session, user_store, mock_storage):
        _evaluate(db_session, mock_storage, user_store, "Ciabatte", "Scarpe")
        _evaluate(db_session, mock_storage, user_store, "Ciabatte", "Scarpe")

        candidate = (
            db_session.query(CategoryCandidate)
            .filter_by(user_id="test_user_1", normalized_name="ciabatte")
            .one()
        )
        assert candidate.occurrences == 2

        # Simula un'occorrenza precedente molto vecchia, fuori dalla finestra di 90gg
        candidate.last_seen_at = datetime.utcnow() - timedelta(days=200)
        db_session.commit()

        result = _evaluate(db_session, mock_storage, user_store, "Ciabatte", "Scarpe")
        assert result.promoted is False

        db_session.refresh(candidate)
        assert candidate.occurrences == 1


# ---------------------------------------------------------------------------
# 3. Clustering fuzzy tra pattern simili vs pattern scorrelati
# ---------------------------------------------------------------------------

class TestClustering:
    def test_similar_names_increment_the_same_candidate(
        self, monkeypatch, db_session, user_store, mock_storage,
    ):
        # Cutoff più permissivo per isolare il test dal valore esatto del ratio
        # difflib tra le due varianti — qui vogliamo provare il path di fuzzy
        # clustering (nomi diversi dopo la normalizzazione), non il match esatto.
        monkeypatch.setattr(Config, "CATEGORY_CANDIDATE_CLUSTER_CUTOFF", 0.6)

        from src.category_matcher import normalize_event_name
        assert normalize_event_name("Pizza Mario") != normalize_event_name("Pizza da Mario")

        _evaluate(db_session, mock_storage, user_store, "Pizza Mario", "Ristoranti")
        _evaluate(db_session, mock_storage, user_store, "Pizza da Mario", "Ristoranti")

        candidates = db_session.query(CategoryCandidate).filter_by(user_id="test_user_1").all()
        assert len(candidates) == 1
        assert candidates[0].occurrences == 2

    def test_unrelated_name_creates_a_separate_candidate(self, db_session, user_store, mock_storage):
        _evaluate(db_session, mock_storage, user_store, "Pizza Mario", "Ristoranti")
        _evaluate(db_session, mock_storage, user_store, "Bolletta luce", "Bollette")

        candidates = db_session.query(CategoryCandidate).filter_by(user_id="test_user_1").all()
        assert len(candidates) == 2
        assert {c.occurrences for c in candidates} == {1, 1}


# ---------------------------------------------------------------------------
# 4. Score sopra soglia: nessuna scrittura, categoria accettata invariata
# ---------------------------------------------------------------------------

class TestPromotionNotionMirror:
    def test_notion_page_id_is_recorded_on_promotion(self, db_session, user_store):
        """Se storage.create_category ritorna un id stringa (comportamento di
        NotionStorage, un vero page_id Notion), va salvato in
        user_category_notion_links per evitare una fetch live superflua."""
        from src.storage.models import UserCategoryNotionLink

        notion_like_storage = MagicMock(spec=FinancialStorage)
        notion_like_storage.create_category.side_effect = (
            lambda name: {"id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890", "name": name}
        )

        for _ in range(3):
            _evaluate(db_session, notion_like_storage, user_store, "Ciabatte", "Scarpe")

        category = db_session.query(UserCategory).filter_by(
            user_id="test_user_1", name="Ciabatte",
        ).one()
        link = db_session.query(UserCategoryNotionLink).filter_by(category_id=category.id).first()
        assert link is not None
        assert link.notion_page_id == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


class TestAlreadyPromotedCandidate:
    def test_returns_promoted_category_even_if_known_categories_is_stale(
        self, db_session, user_store, mock_storage,
    ):
        """Se le known_categories passate da bot.py non sono ancora state ricaricate
        dopo una promozione precedente, il matcher deve comunque riconoscere il
        candidate già promosso tramite lo storico, senza tentare una ri-promozione."""
        for _ in range(3):
            _evaluate(db_session, mock_storage, user_store, "Ciabatte", "Scarpe")
        mock_storage.create_category.reset_mock()

        # known_categories volutamente non aggiornata (non contiene "Ciabatte")
        result = _evaluate(db_session, mock_storage, user_store, "Ciabatte", "Scarpe", known_categories=["Altro"])

        assert result.category_name == "Ciabatte"
        assert result.promoted is False
        mock_storage.create_category.assert_not_called()


class TestAboveThreshold:
    def test_exact_category_match_is_accepted_without_tracking(self, db_session, user_store, mock_storage):
        result = _evaluate(
            db_session, mock_storage, user_store, "Spesa settimanale", "Supermercato",
            known_categories=["Supermercato", "Altro"],
        )

        assert result.category_name == "Supermercato"
        assert result.promoted is False
        assert db_session.query(CategoryCandidate).count() == 0
        mock_storage.create_category.assert_not_called()
