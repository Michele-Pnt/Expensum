"""Test per la streak giornaliera (≥2 transazioni/giorno) e il reward Pro.

Cicli sequenziali a target crescente (14 → 28 → 42gg...) separati da una pausa
(cycle_state='reward_active') che coincide col reward Pro. Vedi
UserStore.record_streak_activity per la logica completa.
"""
import pytest
from datetime import date, datetime, timedelta

from src.user_store import User, UserStreak, PlanChange

pytestmark = pytest.mark.integration


def _prep_streak(store, chat_id, **kwargs):
    """Crea/aggiorna direttamente la riga UserStreak per preparare lo stato di un test."""
    with store.Session() as s:
        streak = s.query(UserStreak).filter_by(chat_id=chat_id).first()
        if not streak:
            streak = UserStreak(chat_id=chat_id)
            s.add(streak)
        for key, value in kwargs.items():
            setattr(streak, key, value)
        s.commit()


def test_two_transactions_same_day_count_as_one_qualifying_day(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="s1")

    assert store.record_streak_activity("s1") is None  # 1ª tx del giorno
    result = store.record_streak_activity("s1")  # 2ª tx del giorno -> qualifica
    assert result is None  # target 14, non ancora raggiunto

    with store.Session() as s:
        streak = s.query(UserStreak).filter_by(chat_id="s1").first()
        assert streak.current_streak_days == 1
        assert streak.last_qualifying_date == date.today()


def test_third_transaction_same_day_does_not_advance_twice(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="s2")

    store.record_streak_activity("s2")
    store.record_streak_activity("s2")
    store.record_streak_activity("s2")  # 3ª tx stesso giorno

    with store.Session() as s:
        streak = s.query(UserStreak).filter_by(chat_id="s2").first()
        assert streak.current_streak_days == 1
        assert streak.today_count == 3


def test_consecutive_day_increments_streak(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="s3")
    yesterday = date.today() - timedelta(days=1)
    _prep_streak(
        store, "s3",
        current_streak_days=5, streak_target_days=14,
        last_qualifying_date=yesterday, cycle_state="counting",
    )

    store.record_streak_activity("s3")
    store.record_streak_activity("s3")

    with store.Session() as s:
        streak = s.query(UserStreak).filter_by(chat_id="s3").first()
        assert streak.current_streak_days == 6
        assert streak.last_qualifying_date == date.today()


def test_gap_resets_streak_to_zero_keeping_same_target(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="s4")
    three_days_ago = date.today() - timedelta(days=3)
    _prep_streak(
        store, "s4",
        current_streak_days=8, streak_target_days=14,
        last_qualifying_date=three_days_ago, cycle_state="counting",
    )

    store.record_streak_activity("s4")
    store.record_streak_activity("s4")

    with store.Session() as s:
        streak = s.query(UserStreak).filter_by(chat_id="s4").first()
        assert streak.current_streak_days == 1  # riparte da 1, non da 0+8
        assert streak.streak_target_days == 14  # il target non scala per un tentativo fallito


def test_reaching_target_grants_reward_and_pauses_cycle(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="s5")
    yesterday = date.today() - timedelta(days=1)
    _prep_streak(
        store, "s5",
        current_streak_days=13, streak_target_days=14,
        last_qualifying_date=yesterday, cycle_state="counting",
    )

    store.record_streak_activity("s5")
    result = store.record_streak_activity("s5")

    assert result == {"cycle_completed_days": 14, "next_target_days": 28}

    with store.Session() as s:
        streak = s.query(UserStreak).filter_by(chat_id="s5").first()
        assert streak.cycle_state == "reward_active"
        assert streak.current_streak_days == 0
        assert streak.streak_target_days == 28
        assert streak.reward_active_until is not None

        plan_change = s.query(PlanChange).filter_by(
            chat_id="s5", change_type="streak_reward"
        ).first()
        assert plan_change is not None

    plan = store.get_user_plan("s5")
    assert plan["plan_type"] == "pro"
    assert plan["is_trial"] is True


def test_transactions_during_reward_active_are_ignored(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="s6")
    _prep_streak(
        store, "s6",
        current_streak_days=0, streak_target_days=28,
        cycle_state="reward_active",
        reward_active_until=datetime.utcnow() + timedelta(days=1),
    )

    result = store.record_streak_activity("s6")
    assert result is None

    with store.Session() as s:
        streak = s.query(UserStreak).filter_by(chat_id="s6").first()
        assert streak.cycle_state == "reward_active"
        assert streak.current_streak_days == 0


def test_first_transaction_after_reward_expiry_resumes_counting_at_new_target(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="s7")
    _prep_streak(
        store, "s7",
        current_streak_days=0, streak_target_days=28,
        cycle_state="reward_active",
        reward_active_until=datetime.utcnow() - timedelta(minutes=1),
        last_qualifying_date=date.today() - timedelta(days=20),
    )

    store.record_streak_activity("s7")  # 1ª tx dopo la scadenza: riattiva il ciclo
    with store.Session() as s:
        streak = s.query(UserStreak).filter_by(chat_id="s7").first()
        assert streak.cycle_state == "counting"
        assert streak.current_streak_days == 0
        assert streak.streak_target_days == 28

    store.record_streak_activity("s7")  # 2ª tx: qualifica il primo giorno del nuovo ciclo
    with store.Session() as s:
        streak = s.query(UserStreak).filter_by(chat_id="s7").first()
        assert streak.current_streak_days == 1


def test_record_tx_event_returns_streak_result_only_for_expense_and_income(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="s8")
    yesterday = date.today() - timedelta(days=1)
    _prep_streak(
        store, "s8",
        current_streak_days=13, streak_target_days=14,
        last_qualifying_date=yesterday, cycle_state="counting",
    )

    assert store.record_tx_event("s8", "transfer", "text", "confirmed", "telegram") is None
    store.record_tx_event("s8", "expense", "text", "confirmed", "telegram")
    result = store.record_tx_event("s8", "income", "text", "confirmed", "telegram")

    assert result == {"cycle_completed_days": 14, "next_target_days": 28}


def test_get_user_streak_default_when_no_row(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="s9")

    streak = store.get_user_streak("s9")
    assert streak == {
        "current_streak_days": 0,
        "streak_target_days": 14,
        "cycle_state": "counting",
    }


def test_reset_stale_streaks_resets_only_counting_users_with_gap(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="s10")  # gap: da resettare
    store.add_user(chat_id="s11")  # ancora valido (last_qualifying_date = ieri)
    store.add_user(chat_id="s12")  # reward_active: non va toccato

    _prep_streak(
        store, "s10",
        current_streak_days=5, streak_target_days=14, cycle_state="counting",
        last_qualifying_date=date.today() - timedelta(days=3),
    )
    _prep_streak(
        store, "s11",
        current_streak_days=5, streak_target_days=14, cycle_state="counting",
        last_qualifying_date=date.today() - timedelta(days=1),
    )
    _prep_streak(
        store, "s12",
        current_streak_days=0, streak_target_days=28, cycle_state="reward_active",
        reward_active_until=datetime.utcnow() + timedelta(days=1),
    )

    reset_users = store.reset_stale_streaks()
    assert reset_users == [("s10", 5)]

    with store.Session() as s:
        assert s.query(UserStreak).filter_by(chat_id="s10").first().current_streak_days == 0
        assert s.query(UserStreak).filter_by(chat_id="s11").first().current_streak_days == 5
        assert s.query(UserStreak).filter_by(chat_id="s12").first().current_streak_days == 0


def test_build_streak_bar_boundaries():
    from bot import _build_streak_bar

    assert _build_streak_bar(0, 14, "counting") == "⬜" * 14
    assert _build_streak_bar(1, 14, "counting") == "🟩" + "⬜" * 13
    assert _build_streak_bar(13, 14, "counting") == "🟩" * 13 + "⬜"
    assert _build_streak_bar(14, 14, "counting") == "🟩" * 14
    assert _build_streak_bar(0, 28, "reward_active") == "🟩" * 14


def test_build_streak_section_explains_the_bar(monkeypatch, mock_db_session):
    import bot

    monkeypatch.setattr(bot, "_user_store", mock_db_session)
    mock_db_session.add_user(chat_id="s13")

    section_counting = bot._build_streak_section("s13")
    assert "prossimo premio Pro" in section_counting
    assert "⬜" * 14 in section_counting

    _prep_streak(
        mock_db_session, "s13",
        current_streak_days=0, streak_target_days=28, cycle_state="reward_active",
        reward_active_until=datetime.utcnow() + timedelta(days=1),
    )
    section_reward = bot._build_streak_section("s13")
    assert "in pausa" in section_reward
    assert "🟩" * 14 in section_reward
