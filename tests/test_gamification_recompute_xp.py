"""
tests/test_gamification_recompute_xp.py — Ricalcolo dell'XP dopo una ricalibrazione.

Copre il motivo per cui questo script esiste: `xp_awarded` e `total_xp` sono
istantanee del valore del registry al momento dello sblocco, quindi cambiare il
registry non è retroattivo finché qualcuno non riallinea esplicitamente i dati.
"""

import pytest

from src.gamification import backfill, engine
from src.gamification import metrics as M
from src.gamification.registry import BY_CODE
from src.user_store import UserAchievement, UserGamificationProfile

pytestmark = pytest.mark.integration


@pytest.fixture
def store(mock_db_session):
    mock_db_session.add_user(chat_id="u1")
    return mock_db_session


def _unlock_at(store, chat_id, code, xp, dedup_key=""):
    """Simula uno sblocco avvenuto quando il registry valeva `xp` per quel codice.

    Aggiorna anche `level`, come fa il codice reale (`engine._insert_unlock`): senza,
    il livello "storico" resterebbe sempre 1 e i test sul livello che scende
    testerebbero un profilo mai esistito in produzione.
    """
    from src.gamification.xp import level_for_xp

    with store.Session() as s:
        s.add(UserAchievement(chat_id=chat_id, code=code, dedup_key=dedup_key,
                              xp_awarded=xp, source="live"))
        profile = s.query(UserGamificationProfile).filter_by(chat_id=chat_id).first()
        if profile is None:
            profile = UserGamificationProfile(chat_id=chat_id, total_xp=0, level=1)
            s.add(profile)
        profile.total_xp = (profile.total_xp or 0) + xp
        profile.level = level_for_xp(profile.total_xp)
        s.commit()


class TestRecomputeXp:
    def test_updates_frozen_xp_to_the_current_registry_value(self, store):
        """Il caso centrale: un valore vecchio viene riallineato a quello attuale."""
        current = BY_CODE["volume_expenses_25"].xp
        _unlock_at(store, "u1", "volume_expenses_25", xp=current + 500)

        result = backfill.recompute_xp(store, "u1")

        assert result["updated"] == 1
        with store.Session() as s:
            row = s.query(UserAchievement).one()
            assert row.xp_awarded == current
            assert s.query(UserGamificationProfile).one().total_xp == current

    def test_is_idempotent(self, store):
        _unlock_at(store, "u1", "volume_expenses_25", xp=9999)
        backfill.recompute_xp(store, "u1")
        second = backfill.recompute_xp(store, "u1")

        assert second["updated"] == 0, "il secondo giro non trova più nulla da correggere"

    def test_recomputes_level_from_new_total(self, store):
        for code in ("volume_expenses_25", "volume_expenses_50", "onboarding_feedback_sent"):
            _unlock_at(store, "u1", code, xp=1)  # valori palesemente vecchi/sbagliati

        result = backfill.recompute_xp(store, "u1")

        expected = sum(BY_CODE[c].xp for c in
                       ("volume_expenses_25", "volume_expenses_50", "onboarding_feedback_sent"))
        assert result["new_xp"] == expected
        with store.Session() as s:
            assert s.query(UserGamificationProfile).one().total_xp == expected

    def test_level_can_go_down_and_the_script_must_report_it(self, store):
        """Se una ricalibrazione abbassa gli XP, il livello può scendere: va segnalato,
        non nascosto."""
        _unlock_at(store, "u1", "streak_cycle_1", xp=500)  # vecchio valore, alto

        result = backfill.recompute_xp(store, "u1")

        assert result["new_xp"] < result["old_xp"]
        assert result["new_level"] <= result["old_level"]

    def test_unknown_codes_keep_their_old_value(self, store):
        """Un achievement deprecato non deve perdere XP per una decisione successiva."""
        _unlock_at(store, "u1", "achievement_ormai_rimosso", xp=42)

        result = backfill.recompute_xp(store, "u1")

        assert result["unknown_codes"] == ["achievement_ormai_rimosso"]
        assert result["new_xp"] == 42
        with store.Session() as s:
            row = s.query(UserAchievement).one()
            assert row.xp_awarded == 42, "invariato, non azzerato"

    def test_untouched_fields_survive(self, store):
        """Il ricalcolo tocca solo XP e livello: storia e stato restano intatti."""
        from datetime import datetime

        with store.Session() as s:
            s.add(UserAchievement(
                chat_id="u1", code="volume_expenses_25", xp_awarded=1,
                source="backfill", notified_telegram=True,
                unlocked_at=datetime(2026, 1, 1), seen_at=datetime(2026, 1, 2),
            ))
            s.commit()

        backfill.recompute_xp(store, "u1")

        with store.Session() as s:
            row = s.query(UserAchievement).one()
            assert row.source == "backfill"
            assert row.notified_telegram is True
            assert row.unlocked_at == datetime(2026, 1, 1)
            assert row.seen_at == datetime(2026, 1, 2)

    def test_user_with_no_unlocks_is_a_no_op(self, store):
        result = backfill.recompute_xp(store, "u1")
        assert result == {
            "chat_id": "u1", "updated": 0, "unknown_codes": [],
            "old_xp": 0, "new_xp": 0, "old_level": 1, "new_level": 1,
        }

    def test_never_raises_on_a_broken_store(self):
        class Broken:
            def Session(self):
                raise RuntimeError("db irraggiungibile")
        result = backfill.recompute_xp(Broken(), "u1")
        assert result["chat_id"] == "u1"
        assert result["updated"] == 0


class TestRecomputeXpAll:
    def test_covers_every_active_user(self, mock_db_session):
        store = mock_db_session
        for cid in ("a", "b"):
            store.add_user(chat_id=cid)
            _unlock_at(store, cid, "volume_expenses_25", xp=1)

        summary = backfill.recompute_xp_all(store)

        assert summary["users"] == 2
        assert summary["rows_updated"] == 2

    def test_level_down_users_are_surfaced_separately(self, mock_db_session):
        store = mock_db_session
        store.add_user(chat_id="drops")
        _unlock_at(store, "drops", "streak_cycle_1", xp=9999)

        summary = backfill.recompute_xp_all(store)

        assert len(summary["level_down"]) == 1
        assert summary["level_down"][0]["chat_id"] == "drops"
