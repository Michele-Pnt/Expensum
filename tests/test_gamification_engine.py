"""
tests/test_gamification_engine.py — Il motore di valutazione degli achievement.

Le due proprietà che contano più di tutte:
1. **Idempotenza**: rivalutare non duplica sblocchi né raddoppia l'XP. È ciò che
   rende sicuro rieseguire il backfill e la riconciliazione notturna.
2. **Non solleva mai**: la gamification è un ornamento, un suo errore non deve
   poter far fallire il salvataggio di una spesa.
"""

import pytest

from src.gamification import engine
from src.gamification import metrics as M
from src.gamification.registry import BY_CODE
from src.user_store import UserAchievement, UserGamificationProfile, UserMetricCounter

pytestmark = pytest.mark.integration


@pytest.fixture
def store(mock_db_session):
    mock_db_session.add_user(chat_id="u1")
    return mock_db_session


class TestBumpMetrics:
    def test_creates_counter_on_first_bump(self, store):
        """Regressione: l'espressione SQL `value = value + n` è valida solo in UPDATE."""
        assert engine.bump_metrics(store, "u1", {M.EXPENSES_TOTAL: 1}) == {
            M.EXPENSES_TOTAL: 1
        }

    def test_accumulates_across_calls(self, store):
        engine.bump_metrics(store, "u1", {M.EXPENSES_TOTAL: 1})
        engine.bump_metrics(store, "u1", {M.EXPENSES_TOTAL: 2})
        assert engine.get_metrics(store, "u1")[M.EXPENSES_TOTAL] == 3

    def test_absolute_overwrites(self, store):
        engine.bump_metrics(store, "u1", {M.CLEAN_MONTHS_STREAK: 5})
        engine.bump_metrics(store, "u1", absolute={M.CLEAN_MONTHS_STREAK: 0})
        assert engine.get_metrics(store, "u1")[M.CLEAN_MONTHS_STREAK] == 0

    def test_returns_all_counters_not_just_touched_ones(self, store):
        engine.bump_metrics(store, "u1", {M.TX_TEXT: 1})
        result = engine.bump_metrics(store, "u1", {M.TX_VOICE: 1})
        assert result == {M.TX_TEXT: 1, M.TX_VOICE: 1}


class TestEvaluate:
    def test_unlocks_when_threshold_reached(self, store):
        engine.bump_metrics(store, "u1", absolute={M.EXPENSES_TOTAL: 25})
        unlocks = engine.evaluate(store, "u1", families=("volume",))
        assert [u.definition.code for u in unlocks] == ["volume_expenses_25"]

    def test_does_not_unlock_below_threshold(self, store):
        engine.bump_metrics(store, "u1", absolute={M.EXPENSES_TOTAL: 24})
        assert engine.evaluate(store, "u1", families=("volume",)) == []

    def test_is_idempotent(self, store):
        engine.bump_metrics(store, "u1", absolute={M.EXPENSES_TOTAL: 25})
        engine.evaluate(store, "u1", families=("volume",))

        assert engine.evaluate(store, "u1", families=("volume",)) == []
        with store.Session() as s:
            assert s.query(UserAchievement).count() == 1
            # XP letti dal registry: una ricalibrazione non deve rompere il test.
            assert s.query(UserGamificationProfile).one().total_xp == BY_CODE["volume_expenses_25"].xp

    def test_unlocks_multiple_tiers_in_one_pass(self, store):
        """Chi arriva da un backfill può scavalcare più soglie insieme."""
        engine.bump_metrics(store, "u1", absolute={M.EXPENSES_TOTAL: 120})
        codes = {u.definition.code for u in engine.evaluate(store, "u1", families=("volume",))}
        assert codes == {"volume_expenses_25", "volume_expenses_50", "volume_expenses_100"}

    def test_already_unlocked_does_not_discard_new_unlocks(self, store):
        """Regressione: un duplicato in mezzo al ciclo non deve annullare i vicini.

        Con `session.rollback()` al posto del SAVEPOINT, l'IntegrityError su un
        achievement già presente annullava l'intera transazione — quindi anche gli
        sblocchi inseriti prima nello stesso giro. `evaluate` li restituiva
        comunque: l'utente riceveva la notifica di un badge mai scritto a DB, e se
        lo rivedeva notificare a ogni riconciliazione notturna.
        """
        engine.bump_metrics(store, "u1", absolute={M.EXPENSES_TOTAL: 25})
        engine.evaluate(store, "u1", families=("volume",))

        # Ora `channel` (alfabeticamente prima) ha un nuovo sblocco e `volume` ne
        # ha uno già presente: l'ordine di valutazione li interlaccia.
        engine.bump_metrics(store, "u1", absolute={M.TX_TEXT: 50, M.EXPENSES_TOTAL: 50})
        returned = {u.definition.code for u in
                    engine.evaluate(store, "u1", families=("volume", "channel"))}

        with store.Session() as s:
            persisted = {r.code for r in s.query(UserAchievement).all()}
            total_xp = s.query(UserGamificationProfile).one().total_xp

        assert returned == {"channel_text_50", "volume_expenses_50"}
        # Ciò che viene notificato deve esistere davvero a DB.
        assert returned <= persisted
        assert persisted == {"volume_expenses_25", "channel_text_50", "volume_expenses_50"}
        assert total_xp == sum(BY_CODE[c].xp for c in persisted)

    def test_families_filter_limits_the_work(self, store):
        engine.bump_metrics(store, "u1", absolute={
            M.EXPENSES_TOTAL: 25, M.FEEDBACK_SENT: 1,
        })
        codes = {u.definition.code for u in engine.evaluate(store, "u1", families=("volume",))}
        assert codes == {"volume_expenses_25"}
        assert "onboarding_feedback_sent" not in codes

    def test_grand_slam_needs_all_three_channels(self, store):
        engine.bump_metrics(store, "u1", absolute={M.TX_TEXT: 50, M.TX_PHOTO: 50})
        codes = {u.definition.code for u in engine.evaluate(store, "u1", families=("channel",))}
        assert "channel_grand_slam" not in codes

        engine.bump_metrics(store, "u1", absolute={M.TX_VOICE: 50})
        codes = {u.definition.code for u in engine.evaluate(store, "u1", families=("channel",))}
        assert "channel_grand_slam" in codes

    def test_xp_accumulates_and_raises_level(self, store):
        engine.bump_metrics(store, "u1", absolute={M.EXPENSES_TOTAL: 200})
        unlocks = engine.evaluate(store, "u1", families=("volume",))

        total = sum(u.xp for u in unlocks)
        with store.Session() as s:
            profile = s.query(UserGamificationProfile).one()
        assert profile.total_xp == total
        assert profile.level >= 2
        # Il level-up viene segnalato una sola volta, sullo sblocco che lo causa.
        assert sum(1 for u in unlocks if u.new_level) >= 1

    def test_notified_flag_is_honoured(self, store):
        engine.bump_metrics(store, "u1", absolute={M.EXPENSES_TOTAL: 25})
        engine.evaluate(store, "u1", families=("volume",), source="backfill", notified=True)

        with store.Session() as s:
            row = s.query(UserAchievement).one()
        assert row.notified_telegram is True
        assert row.source == "backfill"
        assert row.seen_at is None, "il profilo deve apparire nuovo alla prima apertura"


class TestAward:
    def test_repeatable_unlocks_once_per_dedup_key(self, store):
        assert engine.award(store, "u1", "goal_reached", "goal:1") is not None
        assert engine.award(store, "u1", "goal_reached", "goal:2") is not None
        assert engine.award(store, "u1", "goal_reached", "goal:1") is None

        with store.Session() as s:
            assert s.query(UserAchievement).filter_by(code="goal_reached").count() == 2

    def test_unknown_code_returns_none(self, store):
        assert engine.award(store, "u1", "non_esiste") is None


class TestRecordEvent:
    def test_expense_bumps_volume_and_channel(self, store):
        engine.record_event(store, "u1", "expense_confirmed:voice")
        counters = engine.get_metrics(store, "u1")
        assert counters[M.EXPENSES_TOTAL] == 1
        assert counters[M.TX_VOICE] == 1
        assert M.TX_TEXT not in counters

    def test_unknown_input_method_still_counts_volume(self, store):
        engine.record_event(store, "u1", "expense_confirmed:button")
        counters = engine.get_metrics(store, "u1")
        assert counters[M.EXPENSES_TOTAL] == 1

    def test_goal_event_unlocks_both_tier_and_repeatable(self, store):
        codes = {
            u.definition.code for u in
            engine.record_event(store, "u1", "savings_goal_completed", dedup_key="goal:7")
        }
        assert codes == {"goals_completed_1", "goal_reached"}

    def test_unknown_event_is_ignored(self, store):
        assert engine.record_event(store, "u1", "evento_inventato") == []


class TestNeverRaises:
    """Il contratto più importante: nessun errore può propagare al chiamante."""

    class _BrokenStore:
        def Session(self):
            raise RuntimeError("database irraggiungibile")

    def test_record_event_swallows_errors(self):
        assert engine.record_event(self._BrokenStore(), "u1", "report_generated") == []

    def test_evaluate_swallows_errors(self):
        assert engine.evaluate(self._BrokenStore(), "u1") == []

    def test_bump_metrics_swallows_errors(self):
        assert engine.bump_metrics(self._BrokenStore(), "u1", {M.EXPENSES_TOTAL: 1}) == {}

    def test_award_swallows_errors(self):
        assert engine.award(self._BrokenStore(), "u1", "goal_reached", "goal:1") is None

    def test_get_profile_returns_neutral_profile_on_error(self):
        profile = engine.get_profile(self._BrokenStore(), "u1")
        assert profile["level"] == 1
        assert profile["total_xp"] == 0

    def test_mark_seen_swallows_errors(self):
        assert engine.mark_seen(self._BrokenStore(), "u1") == 0


class TestUserState:
    def test_payload_contains_full_catalogue(self, store):
        state = engine.get_user_state(store, "u1")
        total = sum(f["total"] for f in state["families"])
        assert total > 40, "il catalogo completo, non solo gli sbloccati"
        assert state["profile"]["level"] == 1

    def test_goals_family_unavailable_for_free_notion_user(self, store):
        state = engine.get_user_state(store, "u1", backend="notion", plan_type="free")
        goals = next(f for f in state["families"] if f["code"] == "goals")
        assert goals["state"] == "unavailable"
        assert goals["unavailable_reason"] == "requires_postgres_pro"
        assert goals["achievements"], "la famiglia resta visibile, come teaser"

    def test_goals_family_available_for_pro_postgres_user(self, store):
        state = engine.get_user_state(store, "u1", backend="postgres", plan_type="pro")
        goals = next(f for f in state["families"] if f["code"] == "goals")
        assert goals["state"] == "available"

    def test_progress_is_reported_for_locked_achievements(self, store):
        engine.bump_metrics(store, "u1", absolute={M.EXPENSES_TOTAL: 10})
        state = engine.get_user_state(store, "u1")
        volume = next(f for f in state["families"] if f["code"] == "volume")
        first = volume["achievements"][0]
        assert first["state"] == "locked"
        assert first["progress"] == {"current": 10, "target": 25, "pct": 40.0}

    def test_repeatable_exposes_instances(self, store):
        engine.award(store, "u1", "goal_reached", "goal:1")
        engine.award(store, "u1", "goal_reached", "goal:2")

        state = engine.get_user_state(store, "u1", backend="postgres", plan_type="pro")
        goals = next(f for f in state["families"] if f["code"] == "goals")
        item = next(a for a in goals["achievements"] if a["code"] == "goal_reached")
        assert item["count"] == 2
        assert len(item["instances"]) == 2


class TestSummary:
    def test_next_up_lists_closest_achievements(self, store):
        engine.bump_metrics(store, "u1", absolute={M.EXPENSES_TOTAL: 20, M.TX_TEXT: 5})
        summary = engine.get_summary(store, "u1")

        codes = [n["code"] for n in summary["next_up"]]
        assert "volume_expenses_25" in codes
        # Ordinati per vicinanza: 20/25 batte 5/50.
        assert codes[0] == "volume_expenses_25"
        assert len(summary["next_up"]) <= 3

    def test_unseen_unlocks_are_surfaced_then_cleared(self, store):
        engine.bump_metrics(store, "u1", absolute={M.EXPENSES_TOTAL: 25})
        engine.evaluate(store, "u1", families=("volume",))

        assert len(engine.get_summary(store, "u1")["unseen_unlocks"]) == 1
        assert engine.mark_seen(store, "u1") == 1
        assert engine.get_summary(store, "u1")["unseen_unlocks"] == []
