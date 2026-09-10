"""
tests/test_gamification_hooks.py — Gli innesti del motore nel resto del codebase.

Verifica che gli eventi di dominio arrivino davvero ai contatori: è la parte che
un test sul solo motore non copre, e dove è più facile che una modifica futura
scolleghi silenziosamente un hook.

Copre anche il tracking server-side dei report, che sostituisce l'evento PostHog
lato frontend (inaffidabile perché subordinato al consenso cookie).
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.gamification import engine
from src.gamification import metrics as M
from src.user_store import ReportEvent, UserAchievement


def _unlocked(store, chat_id):
    with store.Session() as s:
        return s.query(UserAchievement).filter_by(chat_id=chat_id).all()

pytestmark = pytest.mark.integration


@pytest.fixture
def store(mock_db_session):
    mock_db_session.add_user(chat_id="u1")
    return mock_db_session


class TestExpenseHook:
    def test_confirmed_expense_bumps_volume_and_channel(self, store):
        store.record_tx_event("u1", "expense", "photo", "confirmed", "telegram")

        counters = engine.get_metrics(store, "u1")
        assert counters[M.EXPENSES_TOTAL] == 1
        assert counters[M.TX_PHOTO] == 1

    def test_income_does_not_count_as_expense(self, store):
        """Il volume misura le spese: le entrate alimentano solo la streak."""
        store.record_tx_event("u1", "income", "text", "confirmed", "telegram")

        assert engine.get_metrics(store, "u1").get(M.EXPENSES_TOTAL, 0) == 0

    def test_cancelled_and_failed_do_not_count(self, store):
        store.record_tx_event("u1", "expense", "text", "cancelled", "telegram")
        store.record_tx_event("u1", "expense", "text", "failed", "telegram",
                              reason="save_error")

        assert engine.get_metrics(store, "u1") == {}

    def test_transfer_does_not_count(self, store):
        store.record_tx_event("u1", "transfer", "text", "confirmed", "telegram")
        assert engine.get_metrics(store, "u1") == {}

    def test_returns_achievements_when_threshold_reached(self, store):
        for _ in range(24):
            store.record_tx_event("u1", "expense", "text", "confirmed", "telegram")
        result = store.record_tx_event("u1", "expense", "text", "confirmed", "telegram")

        assert result is not None
        codes = {a["code"] for a in result["achievements"]}
        assert "volume_expenses_25" in codes

    def test_returns_none_when_nothing_happened(self, store):
        """Il caso normale: nessuna streak completata e nessuna soglia raggiunta."""
        assert store.record_tx_event("u1", "expense", "text", "confirmed", "telegram") is None


class TestFeedbackHook:
    def test_saving_feedback_unlocks_achievement(self, store):
        store.save_feedback("u1", "bel prodotto")

        assert engine.get_metrics(store, "u1")[M.FEEDBACK_SENT] == 1
        state = engine.get_user_state(store, "u1")
        onboarding = next(f for f in state["families"] if f["code"] == "onboarding")
        feedback = next(
            a for a in onboarding["achievements"] if a["code"] == "onboarding_feedback_sent"
        )
        assert feedback["state"] == "unlocked"


class TestReportEvents:
    def test_generated_event_is_recorded_and_counted(self, store):
        store.record_report_event("u1", "token-1", "monthly", "generated", "job")

        with store.Session() as s:
            assert s.query(ReportEvent).count() == 1
        assert engine.get_metrics(store, "u1")[M.REPORTS_GENERATED] == 1

    def test_first_generated_unlocks_achievement(self, store):
        unlocks = store.record_report_event("u1", "token-1", "monthly", "generated", "job")
        assert {u["code"] for u in unlocks} == {"reports_first_generated"}

    def test_regenerating_the_same_report_does_not_double_count(self, store):
        """`save_report` è un upsert: lo stesso token può ripresentarsi."""
        store.record_report_event("u1", "token-1", "monthly", "generated", "job")
        assert store.record_report_event("u1", "token-1", "monthly", "generated", "job") == []

        assert engine.get_metrics(store, "u1")[M.REPORTS_GENERATED] == 1

    def test_reopening_does_not_double_count(self, store):
        """Il refresh della pagina non è una seconda apertura."""
        store.record_report_event("u1", "token-1", "monthly", "opened", "webapp")
        store.record_report_event("u1", "token-1", "monthly", "opened", "webapp")

        assert engine.get_metrics(store, "u1")[M.REPORTS_OPENED] == 1

    def test_generated_and_opened_are_distinct_events(self, store):
        store.record_report_event("u1", "token-1", "monthly", "generated", "job")
        store.record_report_event("u1", "token-1", "monthly", "opened", "webapp")

        counters = engine.get_metrics(store, "u1")
        assert counters[M.REPORTS_GENERATED] == 1
        assert counters[M.REPORTS_OPENED] == 1

    def test_eighth_opened_report_unlocks_the_tier(self, store):
        """Le milestone contano le APERTURE: i generati arrivano dal job, non dall'utente."""
        for i in range(7):
            store.record_report_event("u1", f"t{i}", "monthly", "opened", "webapp")
        unlocks = store.record_report_event("u1", "t7", "monthly", "opened", "webapp")

        assert {u["code"] for u in unlocks} == {"reports_opened_8"}

    def test_generated_reports_do_not_unlock_tiers(self, store):
        """Ricevere venti report automatici non deve valere una milestone."""
        for i in range(20):
            store.record_report_event("u1", f"g{i}", "weekly", "generated", "job")

        codes = {a.code for a in _unlocked(store, "u1")}
        assert codes == {"reports_first_generated"}

    def test_first_open_can_unlock_two_achievements_at_once(self, store):
        """Una sola apertura può far scattare più soglie della stessa famiglia."""
        engine.bump_metrics(store, "u1", absolute={M.REPORTS_OPENED: 7})
        unlocks = store.record_report_event("u1", "tok", "weekly", "opened", "webapp")

        codes = {u["code"] for u in unlocks}
        assert {"reports_first_opened", "reports_opened_8"} <= codes


class TestNeverBreaksTheCaller:
    def test_record_tx_event_survives_a_broken_engine(self, store, monkeypatch):
        """Un errore del motore non deve far fallire la registrazione della spesa."""
        def boom(*args, **kwargs):
            raise RuntimeError("motore rotto")

        monkeypatch.setattr(engine, "record_event", boom)

        # Nessuna eccezione propagata, e il TxEvent viene comunque scritto.
        assert store.record_tx_event("u1", "expense", "text", "confirmed", "telegram") is None
        from src.user_store import TxEvent
        with store.Session() as s:
            assert s.query(TxEvent).count() == 1

    def test_streak_reward_survives_a_broken_engine(self, store, monkeypatch):
        """Anche col motore rotto la streak deve continuare a concedere il Pro."""
        from src.user_store import UserStreak

        with store.Session() as s:
            s.add(UserStreak(
                chat_id="u1", current_streak_days=13, streak_target_days=14,
                last_qualifying_date=(datetime.now(ZoneInfo("Europe/Rome")).date() - timedelta(days=1)),
                cycle_state="counting", today_count=1,
                today_date=datetime.now(ZoneInfo("Europe/Rome")).date(),
            ))
            s.commit()

        def boom(*args, **kwargs):
            raise RuntimeError("motore rotto")

        monkeypatch.setattr(engine, "record_event", boom)
        result = store.record_tx_event("u1", "expense", "text", "confirmed", "telegram")

        assert result["cycle_completed_days"] == 14
        assert result["achievements"] == []

    def test_report_event_survives_a_broken_engine(self, store, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("motore rotto")

        monkeypatch.setattr(engine, "record_event", boom)
        assert store.record_report_event("u1", "t1", "monthly", "generated", "job") == []
        with store.Session() as s:
            assert s.query(ReportEvent).count() == 1
