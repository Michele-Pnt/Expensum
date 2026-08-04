"""
tests/test_subscription_detector.py — Test per il rilevamento abbonamenti
ricorrenti (src/subscription_detector.py).

Le funzioni pure (keyword categoria, etichette cadenza) sono unit test senza DB.
`evaluate_and_track`/`confirm_candidate`/`dismiss_candidate` scrivono su
`subscription_candidates`: integration test su un file SQLite condiviso, stesso
schema di `tests/test_category_candidates_integration.py`.
"""

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src import subscription_detector
from src.storage.base import FinancialStorage
from src.storage.models import SubscriptionCandidate
from src.user_store import Base, User

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Funzioni pure
# ---------------------------------------------------------------------------

class TestIsSubscriptionProneCategory:
    def test_matches_known_keywords(self):
        assert subscription_detector.is_subscription_prone_category("Abbonamenti")
        assert subscription_detector.is_subscription_prone_category("Streaming video")
        assert subscription_detector.is_subscription_prone_category("Palestra")
        assert subscription_detector.is_subscription_prone_category("Assicurazione auto")
        assert subscription_detector.is_subscription_prone_category("Bollette")
        assert subscription_detector.is_subscription_prone_category("Utenze")

    def test_case_insensitive(self):
        assert subscription_detector.is_subscription_prone_category("ABBONAMENTI")

    def test_unrelated_category_does_not_match(self):
        assert not subscription_detector.is_subscription_prone_category("Bar")
        assert not subscription_detector.is_subscription_prone_category("Ristoranti")

    def test_none_or_empty(self):
        assert not subscription_detector.is_subscription_prone_category(None)
        assert not subscription_detector.is_subscription_prone_category("")


class TestCadenceLabelIt:
    def test_known_cadences(self):
        assert subscription_detector.cadence_label_it("monthly") == "al mese"
        assert subscription_detector.cadence_label_it("weekly") == "a settimana"
        assert subscription_detector.cadence_label_it("quarterly") == "al trimestre"
        assert subscription_detector.cadence_label_it("yearly") == "all'anno"

    def test_unknown_or_none_falls_back(self):
        assert subscription_detector.cadence_label_it(None) == "periodicamente"
        assert subscription_detector.cadence_label_it("boh") == "periodicamente"


# ---------------------------------------------------------------------------
# Fixtures DB (integration)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    Base.metadata.drop_all(db_engine)
    Base.metadata.create_all(db_engine)
    Session = sessionmaker(bind=db_engine)
    session = Session()
    session.add(User(chat_id="test_user_1", username="testuser", is_active=True))
    session.commit()
    yield session
    session.close()


@pytest.fixture
def mock_storage():
    storage = MagicMock(spec=FinancialStorage)
    storage.create_subscription.side_effect = lambda name, **kwargs: {"id": 42, "name": name}
    return storage


# ---------------------------------------------------------------------------
# evaluate_and_track
# ---------------------------------------------------------------------------

class TestEvaluateAndTrack:
    def test_non_subscription_category_is_ignored(self, db_session):
        result = subscription_detector.evaluate_and_track(
            db_session, "test_user_1", date(2026, 1, 1), 9.99, "Bar", "Caffè"
        )
        assert result.candidate_id is None
        assert db_session.query(SubscriptionCandidate).count() == 0

    def test_zero_or_missing_amount_is_ignored(self, db_session):
        result = subscription_detector.evaluate_and_track(
            db_session, "test_user_1", date(2026, 1, 1), 0, "Abbonamenti", "Netflix"
        )
        assert result.candidate_id is None
        assert db_session.query(SubscriptionCandidate).count() == 0

    def test_first_occurrence_creates_pending_candidate(self, db_session):
        result = subscription_detector.evaluate_and_track(
            db_session, "test_user_1", date(2026, 1, 1), 9.99, "Abbonamenti", "Netflix"
        )
        assert result.candidate_id is not None
        assert result.awaiting_confirmation is False
        candidate = db_session.get(SubscriptionCandidate, result.candidate_id)
        assert candidate.status == "pending"
        assert candidate.occurrences == 1
        assert candidate.cadence is None

    def test_second_occurrence_within_monthly_band_reaches_threshold(self, db_session):
        subscription_detector.evaluate_and_track(
            db_session, "test_user_1", date(2026, 1, 1), 9.99, "Abbonamenti", "Netflix"
        )
        result = subscription_detector.evaluate_and_track(
            db_session, "test_user_1", date(2026, 1, 31), 9.99, "Abbonamenti", "Netflix"
        )
        assert result.awaiting_confirmation is True
        assert result.cadence == "monthly"
        candidate = db_session.get(SubscriptionCandidate, result.candidate_id)
        assert candidate.status == "awaiting_confirm"
        assert candidate.occurrences == 2

    def test_gap_outside_any_band_creates_separate_candidate(self, db_session):
        """Un acquisto casuale 15gg dopo (fuori da ogni banda di cadenza) non deve
        gonfiare le occorrenze del primo candidate: deve restarne isolato."""
        first = subscription_detector.evaluate_and_track(
            db_session, "test_user_1", date(2026, 1, 1), 9.99, "Abbonamenti", "Netflix"
        )
        second = subscription_detector.evaluate_and_track(
            db_session, "test_user_1", date(2026, 1, 16), 9.99, "Abbonamenti", "Netflix"
        )
        assert second.candidate_id != first.candidate_id
        assert db_session.query(SubscriptionCandidate).count() == 2

    def test_amount_outside_tolerance_creates_separate_candidate(self, db_session):
        first = subscription_detector.evaluate_and_track(
            db_session, "test_user_1", date(2026, 1, 1), 9.99, "Abbonamenti", "Netflix"
        )
        second = subscription_detector.evaluate_and_track(
            db_session, "test_user_1", date(2026, 1, 31), 15.99, "Abbonamenti", "Disney+"
        )
        assert second.candidate_id != first.candidate_id

    def test_amount_within_tolerance_merges(self, db_session):
        first = subscription_detector.evaluate_and_track(
            db_session, "test_user_1", date(2026, 1, 1), 10.00, "Abbonamenti", "Netflix"
        )
        # 3% di 10.00 = 0.30, ma il minimo assoluto è 0.50: 10.40 rientra comunque.
        second = subscription_detector.evaluate_and_track(
            db_session, "test_user_1", date(2026, 1, 31), 10.40, "Abbonamenti", "Netflix"
        )
        assert second.candidate_id == first.candidate_id

    def test_confirmed_candidate_is_not_reopened(self, db_session):
        result = subscription_detector.evaluate_and_track(
            db_session, "test_user_1", date(2026, 1, 1), 9.99, "Abbonamenti", "Netflix"
        )
        candidate = db_session.get(SubscriptionCandidate, result.candidate_id)
        candidate.status = "confirmed"
        db_session.commit()

        second = subscription_detector.evaluate_and_track(
            db_session, "test_user_1", date(2026, 1, 31), 9.99, "Abbonamenti", "Netflix"
        )
        assert second.candidate_id != result.candidate_id

    def test_established_cadence_requires_same_band_to_keep_merging(self, db_session):
        """Dopo che la cadenza mensile è nota, un gap trimestrale non deve
        riattaccarsi allo stesso candidate solo perché importo/categoria combaciano."""
        subscription_detector.evaluate_and_track(
            db_session, "test_user_1", date(2026, 1, 1), 9.99, "Abbonamenti", "Netflix"
        )
        second = subscription_detector.evaluate_and_track(
            db_session, "test_user_1", date(2026, 1, 31), 9.99, "Abbonamenti", "Netflix"
        )
        assert second.cadence == "monthly"
        third = subscription_detector.evaluate_and_track(
            db_session, "test_user_1", date(2026, 5, 1), 9.99, "Abbonamenti", "Netflix"
        )
        assert third.candidate_id != second.candidate_id


# ---------------------------------------------------------------------------
# confirm_candidate / dismiss_candidate
# ---------------------------------------------------------------------------

class TestConfirmCandidate:
    def _make_awaiting_candidate(self, db_session) -> int:
        subscription_detector.evaluate_and_track(
            db_session, "test_user_1", date(2026, 1, 1), 9.99, "Abbonamenti", "Netflix"
        )
        result = subscription_detector.evaluate_and_track(
            db_session, "test_user_1", date(2026, 1, 31), 9.99, "Abbonamenti", "Netflix"
        )
        assert result.awaiting_confirmation is True
        return result.candidate_id

    def test_confirm_creates_subscription_via_storage(self, db_session, mock_storage):
        candidate_id = self._make_awaiting_candidate(db_session)
        candidate = subscription_detector.confirm_candidate(db_session, mock_storage, candidate_id)

        mock_storage.create_subscription.assert_called_once()
        _, kwargs = mock_storage.create_subscription.call_args
        assert kwargs["sub_type"] == "monthly"
        assert kwargs["category_name"] == "Abbonamenti"
        assert candidate.status == "confirmed"
        assert candidate.promoted_subscription_id == 42

    def test_confirm_unknown_candidate_returns_none(self, db_session, mock_storage):
        assert subscription_detector.confirm_candidate(db_session, mock_storage, 999999) is None

    def test_confirm_failure_reverts_to_awaiting_and_raises(self, db_session, mock_storage):
        candidate_id = self._make_awaiting_candidate(db_session)
        mock_storage.create_subscription.side_effect = RuntimeError("Notion down")

        with pytest.raises(RuntimeError):
            subscription_detector.confirm_candidate(db_session, mock_storage, candidate_id)

        candidate = db_session.get(SubscriptionCandidate, candidate_id)
        assert candidate.status == "awaiting_confirm"


class TestDismissCandidate:
    def test_dismiss_sets_status(self, db_session):
        subscription_detector.evaluate_and_track(
            db_session, "test_user_1", date(2026, 1, 1), 9.99, "Abbonamenti", "Netflix"
        )
        result = subscription_detector.evaluate_and_track(
            db_session, "test_user_1", date(2026, 1, 31), 9.99, "Abbonamenti", "Netflix"
        )
        subscription_detector.dismiss_candidate(db_session, result.candidate_id)
        candidate = db_session.get(SubscriptionCandidate, result.candidate_id)
        assert candidate.status == "dismissed"

    def test_dismiss_unknown_candidate_is_noop(self, db_session):
        subscription_detector.dismiss_candidate(db_session, 999999)  # non deve sollevare


class TestGetAwaitingConfirmationCandidates:
    def test_returns_only_awaiting_confirm(self, db_session):
        pending = subscription_detector.evaluate_and_track(
            db_session, "test_user_1", date(2026, 1, 1), 19.99, "Abbonamenti", "Spotify"
        )
        subscription_detector.evaluate_and_track(
            db_session, "test_user_1", date(2026, 1, 1), 9.99, "Abbonamenti", "Netflix"
        )
        awaiting = subscription_detector.evaluate_and_track(
            db_session, "test_user_1", date(2026, 1, 31), 9.99, "Abbonamenti", "Netflix"
        )
        results = subscription_detector.get_awaiting_confirmation_candidates(db_session, "test_user_1")
        result_ids = {c.id for c in results}
        assert awaiting.candidate_id in result_ids
        assert pending.candidate_id not in result_ids
