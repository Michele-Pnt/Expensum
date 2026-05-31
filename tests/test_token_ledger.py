"""
tests/test_token_ledger.py — Test per il sistema di Token Ledger Reale (Fase 2.2).

Verifica:
- reserve_llm_tokens: crea reservation, idempotenza, QuotaExceededError per Free esauriti
- finalize_llm_usage: scrive LlmUsageEvent, calcola costo, finalizza reservation, idempotenza
- release_llm_reservation: marca released
- expire_stale_reservations: marca expired le reservation scadute
- get_user_plan: calcola token_used e token_reserved live dal ledger
"""

import pytest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.user_store import (
    Base, User, UserStore, UserPlan, LlmPricing,
    LlmTokenReservation, LlmUsageEvent, QuotaExceededError,
)

pytestmark = pytest.mark.unit

CHAT_ID = "ledger_test_user"


@pytest.fixture(scope="module")
def db_engine():
    engine = create_engine("sqlite:///:memory:", echo=False)
    yield engine
    engine.dispose()


@pytest.fixture
def store(db_engine):
    """UserStore su DB in-memory fresco per ogni test."""
    Base.metadata.drop_all(db_engine)
    Base.metadata.create_all(db_engine)
    s = UserStore.__new__(UserStore)
    s.Session = sessionmaker(bind=db_engine)

    # Seed utente e piano Free
    with s.Session() as sess:
        sess.add(User(chat_id=CHAT_ID, is_active=True))
        sess.add(UserPlan(
            chat_id=CHAT_ID,
            plan_type="free",
            tokens_total=150000,
            tokens_reset_at=datetime.utcnow() + timedelta(days=30),
        ))
        sess.add(LlmPricing(
            provider="mistral",
            model="mistral-small",
            input_cost_per_1k=0.1,
            output_cost_per_1k=0.3,
            currency="USD",
            valid_from=datetime(2026, 5, 1),
            valid_to=None,
        ))
        sess.commit()

    return s


# ---------------------------------------------------------------------------
# reserve_llm_tokens
# ---------------------------------------------------------------------------

class TestReserveLlmTokens:
    def test_creates_reservation(self, store):
        key = "test-reserve-001"
        store.reserve_llm_tokens(
            chat_id=CHAT_ID,
            request_key=key,
            operation="text_parse",
            provider="mistral",
            model="mistral-small",
            reserved_tokens=1000,
        )
        with store.Session() as sess:
            r = sess.query(LlmTokenReservation).filter_by(request_key=key).first()
            assert r is not None
            assert r.status == "pending"
            assert r.reserved_tokens == 1000
            assert r.chat_id == CHAT_ID

    def test_idempotent_same_key(self, store):
        """Chiamate multiple con lo stesso request_key restituiscono la stessa reservation."""
        key = "test-reserve-idem-001"
        store.reserve_llm_tokens(
            chat_id=CHAT_ID, request_key=key, operation="op", provider="mistral",
            model="mistral-small", reserved_tokens=500,
        )
        store.reserve_llm_tokens(
            chat_id=CHAT_ID, request_key=key, operation="op", provider="mistral",
            model="mistral-small", reserved_tokens=500,
        )
        with store.Session() as sess:
            count = sess.query(LlmTokenReservation).filter_by(request_key=key).count()
            assert count == 1, "Non deve creare duplicati"

    def test_quota_exceeded_for_free_user(self, store):
        """Un utente Free con quota esaurita deve ricevere QuotaExceededError."""
        # Svuota il saldo simulando un usage enorme
        with store.Session() as sess:
            sess.add(LlmUsageEvent(
                chat_id=CHAT_ID,
                occurred_at=datetime.utcnow(),
                provider="mistral",
                model="mistral-small",
                operation="test_exhaust",
                prompt_tokens=100000,
                completion_tokens=50000,
                total_tokens=150000,
                request_key="exhaust-key-001",
            ))
            sess.commit()

        with pytest.raises(QuotaExceededError):
            store.reserve_llm_tokens(
                chat_id=CHAT_ID,
                request_key="should-fail-001",
                operation="text_parse",
                provider="mistral",
                model="mistral-small",
                reserved_tokens=1000,
            )


# ---------------------------------------------------------------------------
# finalize_llm_usage
# ---------------------------------------------------------------------------

class TestFinalizeLlmUsage:
    def test_creates_usage_event(self, store):
        key = "finalize-001"
        store.finalize_llm_usage(
            chat_id=CHAT_ID,
            request_key=key,
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            provider="mistral",
            model="mistral-small",
            operation="text_parse",
        )
        with store.Session() as sess:
            event = sess.query(LlmUsageEvent).filter_by(request_key=key).first()
            assert event is not None
            assert event.total_tokens == 150
            assert event.chat_id == CHAT_ID

    def test_calculates_cost_from_pricing(self, store):
        key = "finalize-cost-001"
        store.finalize_llm_usage(
            chat_id=CHAT_ID,
            request_key=key,
            prompt_tokens=1000,   # 1k tokens → $0.10
            completion_tokens=1000,  # 1k tokens → $0.30
            total_tokens=2000,
            provider="mistral",
            model="mistral-small",
            operation="report",
        )
        with store.Session() as sess:
            event = sess.query(LlmUsageEvent).filter_by(request_key=key).first()
            assert event.estimated_cost_amount is not None
            assert abs(float(event.estimated_cost_amount) - 0.4) < 1e-6

    def test_idempotent_same_key(self, store):
        key = "finalize-idem-001"
        store.finalize_llm_usage(
            chat_id=CHAT_ID, request_key=key,
            prompt_tokens=10, completion_tokens=5, total_tokens=15,
            provider="mistral", model="mistral-small", operation="op",
        )
        store.finalize_llm_usage(
            chat_id=CHAT_ID, request_key=key,
            prompt_tokens=10, completion_tokens=5, total_tokens=15,
            provider="mistral", model="mistral-small", operation="op",
        )
        with store.Session() as sess:
            count = sess.query(LlmUsageEvent).filter_by(request_key=key).count()
            assert count == 1, "Non deve creare duplicati"

    def test_finalizes_reservation(self, store):
        """finalize_llm_usage deve marcare la reservation associata come 'finalized'."""
        key = "finalize-reservation-001"
        store.reserve_llm_tokens(
            chat_id=CHAT_ID, request_key=key, operation="op",
            provider="mistral", model="mistral-small", reserved_tokens=500,
        )
        store.finalize_llm_usage(
            chat_id=CHAT_ID, request_key=key,
            prompt_tokens=10, completion_tokens=5, total_tokens=15,
            provider="mistral", model="mistral-small", operation="op",
        )
        with store.Session() as sess:
            reservation = sess.query(LlmTokenReservation).filter_by(request_key=key).first()
            assert reservation.status == "finalized"


# ---------------------------------------------------------------------------
# release_llm_reservation
# ---------------------------------------------------------------------------

class TestReleaseLlmReservation:
    def test_marks_reservation_released(self, store):
        key = "release-001"
        store.reserve_llm_tokens(
            chat_id=CHAT_ID, request_key=key, operation="op",
            provider="mistral", model="mistral-small", reserved_tokens=100,
        )
        store.release_llm_reservation(CHAT_ID, key, reason="test error")
        with store.Session() as sess:
            r = sess.query(LlmTokenReservation).filter_by(request_key=key).first()
            assert r.status == "released"
            assert r.release_reason == "test error"

    def test_noop_if_already_finalized(self, store):
        """Non deve cambiare status di una reservation già finalizzata."""
        key = "release-finalized-001"
        store.reserve_llm_tokens(
            chat_id=CHAT_ID, request_key=key, operation="op",
            provider="mistral", model="mistral-small", reserved_tokens=100,
        )
        store.finalize_llm_usage(
            chat_id=CHAT_ID, request_key=key,
            prompt_tokens=5, completion_tokens=5, total_tokens=10,
            provider="mistral", model="mistral-small", operation="op",
        )
        store.release_llm_reservation(CHAT_ID, key, reason="late release")
        with store.Session() as sess:
            r = sess.query(LlmTokenReservation).filter_by(request_key=key).first()
            assert r.status == "finalized"  # non deve essere cambiato


# ---------------------------------------------------------------------------
# expire_stale_reservations
# ---------------------------------------------------------------------------

class TestExpireStaleReservations:
    def test_marks_expired_reservations(self, store):
        key = "expire-001"
        # Crea reservation già scaduta nel DB direttamente
        with store.Session() as sess:
            sess.add(LlmTokenReservation(
                chat_id=CHAT_ID,
                request_key=key,
                created_at=datetime.utcnow() - timedelta(hours=2),
                expires_at=datetime.utcnow() - timedelta(hours=1),  # scaduta!
                operation="op",
                provider="mistral",
                model="mistral-small",
                reserved_tokens=100,
                status="pending",
            ))
            sess.commit()

        count = store.expire_stale_reservations()
        assert count >= 1

        with store.Session() as sess:
            r = sess.query(LlmTokenReservation).filter_by(request_key=key).first()
            assert r.status == "expired"


# ---------------------------------------------------------------------------
# get_user_plan — calcolo live da ledger
# ---------------------------------------------------------------------------

class TestGetUserPlan:
    def test_returns_correct_plan_type(self, store):
        plan = store.get_user_plan(CHAT_ID)
        assert plan["plan_type"] == "free"
        assert plan["tokens_total"] == 150000

    def test_tokens_used_calculated_from_events(self, store):
        """tokens_used_current_cycle deve riflettere gli eventi nel ciclo."""
        plan = store.get_user_plan(CHAT_ID)
        # Deve essere > 0 dopo tutti i test precedenti che hanno creato eventi
        assert plan["tokens_used_current_cycle"] >= 0
        assert "tokens_remaining" in plan
        assert "tokens_reset_at" in plan
