"""
tests/test_gamification_backfill.py — Ricalcolo contatori e backfill retroattivo.

Il backfill è la parte più delicata del rilascio: gli utenti beta hanno mesi di
storico e devono ritrovarsi il profilo già popolato, senza però ricevere trenta
notifiche di congratulazioni in fila. E deve essere rieseguibile senza raddoppiare
nulla, perché in produzione girerà dopo il deploy, quando eventi live potrebbero
già aver scritto qualcosa.
"""

import pytest
from datetime import date, datetime, timedelta

from src.gamification import backfill
from src.gamification import engine
from src.gamification import metrics as M
from src.user_store import (
    Feedback, PlanChange, ReportEvent, TxEvent, UserAchievement,
    UserGamificationProfile, UserStreak,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def store(mock_db_session):
    mock_db_session.add_user(chat_id="u1")
    return mock_db_session


class FakeStorage:
    """Storage finanziario minimale: solo ciò che il backfill interroga."""

    def __init__(self, expenses=None, reports=None, goals=None):
        self._expenses = expenses or []
        self._reports = reports or []
        self._goals = goals or []

    def fetch_all_transactions(self, start_date, end_date):
        return [e for e in self._expenses if start_date <= e["date"] <= end_date]

    def get_reports_for_user(self, user_id, limit=24):
        return self._reports[:limit]

    def fetch_savings_goals(self, status=None):
        return [g for g in self._goals if status is None or g.get("status") == status]


def _expense(day, category="Spesa"):
    return {"date": day, "amount": 10.0, "category": category}


class TestRecomputeMetrics:
    def test_counts_channels_from_tx_events(self, store):
        with store.Session() as s:
            for method in ("text", "text", "voice"):
                s.add(TxEvent(chat_id="u1", tx_type="expense", input_method=method,
                              outcome="confirmed", source="telegram"))
            # Le transazioni fallite non contano.
            s.add(TxEvent(chat_id="u1", tx_type="expense", input_method="photo",
                          outcome="failed", source="telegram"))
            s.commit()

        counters = backfill.recompute_metrics(store, "u1")
        assert counters[M.TX_TEXT] == 2
        assert counters[M.TX_VOICE] == 1
        assert counters[M.TX_PHOTO] == 0

    def test_expenses_total_takes_the_larger_source(self, store):
        """Lo storico pre-tx_events vive solo nelle spese vere: non va perso."""
        with store.Session() as s:
            s.add(TxEvent(chat_id="u1", tx_type="expense", input_method="text",
                          outcome="confirmed", source="telegram"))
            s.commit()
        storage = FakeStorage(expenses=[_expense(date(2026, 1, 1)) for _ in range(50)])

        counters = backfill.recompute_metrics(store, "u1", storage)
        assert counters[M.EXPENSES_TOTAL] == 50

    def test_streak_cycles_derived_from_plan_changes(self, store):
        with store.Session() as s:
            for _ in range(3):
                s.add(PlanChange(chat_id="u1", from_plan="pro", to_plan="pro",
                                 change_type="streak_reward", changed_at=datetime.utcnow()))
            s.add(PlanChange(chat_id="u1", from_plan="free", to_plan="pro",
                             change_type="upgrade", changed_at=datetime.utcnow()))
            s.commit()

        assert backfill.recompute_metrics(store, "u1")[M.STREAK_CYCLES] == 3

    def test_streak_max_days_from_current_target(self, store):
        with store.Session() as s:
            s.add(UserStreak(chat_id="u1", streak_target_days=42, current_streak_days=5))
            s.commit()
        assert backfill.recompute_metrics(store, "u1")[M.STREAK_MAX_DAYS] == 28

    def test_telegram_linked_from_chat_id_shape(self, mock_db_session):
        mock_db_session.add_user(chat_id="web_only")
        mock_db_session.add_user(chat_id="123456")

        assert backfill.recompute_metrics(mock_db_session, "web_only")[M.TELEGRAM_LINKED] == 0
        assert backfill.recompute_metrics(mock_db_session, "123456")[M.TELEGRAM_LINKED] == 1

    def test_counts_feedback(self, store):
        with store.Session() as s:
            s.add(Feedback(chat_id="u1", message="ottimo"))
            s.commit()
        assert backfill.recompute_metrics(store, "u1")[M.FEEDBACK_SENT] == 1


class TestCleanMonths:
    def test_month_without_fallback_is_clean(self):
        storage = FakeStorage(expenses=[_expense(date(2026, 6, i + 1)) for i in range(10)])
        assert backfill.is_clean_month(storage, 2026, 6, "Altro") is True

    def test_single_fallback_expense_dirties_the_month(self):
        expenses = [_expense(date(2026, 6, i + 1)) for i in range(10)]
        expenses.append(_expense(date(2026, 6, 20), category="Altro"))
        storage = FakeStorage(expenses=expenses)
        assert backfill.is_clean_month(storage, 2026, 6, "Altro") is False

    def test_too_few_expenses_is_not_evaluable(self):
        """Senza soglia basterebbe non registrare nulla per collezionare la serie."""
        storage = FakeStorage(expenses=[_expense(date(2026, 6, 1))])
        assert backfill.is_clean_month(storage, 2026, 6, "Altro") is None

    def test_cycles_are_awarded_for_every_clean_month(self, store):
        """Ogni mese pulito è un ciclo a sé: non si esauriscono mai."""
        today = date(2026, 7, 15)
        expenses = []
        for month in (4, 5, 6):
            expenses += [_expense(date(2026, month, i + 1)) for i in range(10)]
        storage = FakeStorage(expenses=expenses)

        backfill.backfill_cycles(store, "u1", storage, today)

        counters = engine.get_metrics(store, "u1")
        assert counters[M.CLEAN_MONTHS_TOTAL] == 3
        assert counters[M.ACTIVE_MONTHS_TOTAL] == 3
        assert counters[M.CLEAN_MONTHS_STREAK] == 3

    def test_dirty_month_breaks_the_streak_but_keeps_the_total(self, store):
        """La differenza fra serie e totale: la prima si rompe, il secondo no."""
        today = date(2026, 7, 15)
        expenses = []
        for month in (4, 5, 6):
            expenses += [_expense(date(2026, month, i + 1)) for i in range(10)]
        expenses.append(_expense(date(2026, 5, 20), category="Altro"))
        storage = FakeStorage(expenses=expenses)

        backfill.backfill_cycles(store, "u1", storage, today)

        counters = engine.get_metrics(store, "u1")
        assert counters[M.ACTIVE_MONTHS_TOTAL] == 3, "tutti e tre i mesi sono attivi"
        assert counters[M.CLEAN_MONTHS_TOTAL] == 2, "aprile e giugno restano in cassa"
        assert counters[M.CLEAN_MONTHS_STREAK] == 1, "ma la serie riparte da giugno"

    def test_cycles_are_idempotent(self, store):
        """Rieseguire il backfill non premia due volte lo stesso mese."""
        today = date(2026, 7, 15)
        storage = FakeStorage(expenses=[_expense(date(2026, 6, i + 1)) for i in range(10)])

        backfill.backfill_cycles(store, "u1", storage, today)
        backfill.backfill_cycles(store, "u1", storage, today)

        assert engine.get_metrics(store, "u1")[M.CLEAN_MONTHS_TOTAL] == 1
        with store.Session() as s:
            assert s.query(UserAchievement).filter_by(code="cycle_clean_month").count() == 1

    def test_month_below_threshold_is_not_a_cycle(self, store):
        """Due spese in un mese non fanno un mese attivo: sarebbe gratis."""
        today = date(2026, 7, 15)
        storage = FakeStorage(expenses=[_expense(date(2026, 6, 1)), _expense(date(2026, 6, 2))])

        backfill.backfill_cycles(store, "u1", storage, today)

        assert engine.get_metrics(store, "u1").get(M.ACTIVE_MONTHS_TOTAL, 0) == 0


class TestBackfillReportEvents:
    def test_creates_generated_events(self, store):
        storage = FakeStorage(reports=[
            {"share_token": "t1", "report_type": "monthly", "created_at": "2026-06-01T08:00:00"},
            {"share_token": "t2", "report_type": "weekly", "created_at": "2026-06-08T08:00:00"},
        ])
        assert backfill.backfill_report_events(store, "u1", storage) == 2

        with store.Session() as s:
            rows = s.query(ReportEvent).all()
        assert {r.event_type for r in rows} == {"generated"}
        assert all(r.occurred_at.year == 2026 for r in rows)

    def test_reruns_do_not_duplicate(self, store):
        storage = FakeStorage(reports=[
            {"share_token": "t1", "report_type": "monthly", "created_at": None},
        ])
        backfill.backfill_report_events(store, "u1", storage)
        backfill.backfill_report_events(store, "u1", storage)

        with store.Session() as s:
            assert s.query(ReportEvent).count() == 1

    def test_opened_is_never_invented(self, store):
        """L'apertura di un report passato non è ricostruibile: si parte da zero."""
        storage = FakeStorage(reports=[
            {"share_token": "t1", "report_type": "monthly", "created_at": None},
        ])
        backfill.backfill_report_events(store, "u1", storage)
        counters = backfill.recompute_metrics(store, "u1", storage)

        assert counters[M.REPORTS_GENERATED] == 1
        assert counters[M.REPORTS_OPENED] == 0


class TestBackfillUser:
    def _storage_with_history(self):
        return FakeStorage(
            expenses=[_expense(date(2026, 1, 1)) for _ in range(120)],
            reports=[
                {"share_token": f"t{i}", "report_type": "monthly", "created_at": None}
                for i in range(8)
            ],
            goals=[{"id": 1, "status": "completed"}, {"id": 2, "status": "completed"}],
        )

    def test_unlocks_retroactive_achievements(self, store):
        result = backfill.backfill_user(store, "u1", self._storage_with_history())

        codes = set(result["codes"])
        assert {"volume_expenses_25", "volume_expenses_50", "volume_expenses_100"} <= codes
        assert "goals_completed_1" in codes
        assert "goal_reached" in codes
        # I report generati non sbloccano milestone: quelle contano le aperture.
        assert not any(c.startswith("reports_opened_") for c in codes)

    def test_is_silent_by_default(self, store):
        """Un beta con mesi di storico non deve ricevere trenta messaggi."""
        backfill.backfill_user(store, "u1", self._storage_with_history())

        with store.Session() as s:
            rows = s.query(UserAchievement).all()
        assert rows
        assert all(r.notified_telegram is True for r in rows)
        assert all(r.source == "backfill" for r in rows)
        # Non visti: il profilo deve apparire nuovo alla prima apertura della UI.
        assert all(r.seen_at is None for r in rows)

    def test_rerun_does_not_duplicate_or_double_xp(self, store):
        storage = self._storage_with_history()
        backfill.backfill_user(store, "u1", storage)

        with store.Session() as s:
            first_count = s.query(UserAchievement).count()
            first_xp = s.query(UserGamificationProfile).one().total_xp

        second = backfill.backfill_user(store, "u1", storage)

        assert second["unlocked"] == 0
        with store.Session() as s:
            assert s.query(UserAchievement).count() == first_count
            assert s.query(UserGamificationProfile).one().total_xp == first_xp

    def test_works_without_storage(self, store):
        """Utente Notion: si ricalcola solo ciò che non richiede lo storage."""
        with store.Session() as s:
            s.add(Feedback(chat_id="u1", message="ciao"))
            s.commit()

        result = backfill.backfill_user(store, "u1", None)
        assert "onboarding_feedback_sent" in result["codes"]

    def test_backfill_all_covers_every_active_user(self, mock_db_session):
        store = mock_db_session
        for chat_id in ("a", "b"):
            store.add_user(chat_id=chat_id)
            with store.Session() as s:
                s.add(Feedback(chat_id=chat_id, message="ciao"))
                s.commit()

        summary = backfill.backfill_all(store, storage_factory=lambda _cid: None)
        assert summary["users"] == 2
        assert summary["unlocked"] >= 2
