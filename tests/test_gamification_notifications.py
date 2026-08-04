"""
tests/test_gamification_notifications.py — Testi delle notifiche di sblocco.

Logica pura: nessun DB, nessun invio. Il comportamento che conta è la soglia oltre
la quale si passa a un messaggio unico — ricevere quindici notifiche di fila è un
fastidio, non un premio, ed è lo scenario tipico del primo accesso di un utente con
mesi di storico alle spalle.
"""

import pytest

from src.gamification import notifications as N

pytestmark = pytest.mark.unit


def _unlock(code="volume_expenses_25", title="Si comincia", xp=25, new_level=None):
    return {
        "code": code,
        "title": title,
        "description": "Hai registrato 25 spese.",
        "xp": xp,
        "new_level": new_level,
    }


class TestSingleMessage:
    def test_contains_title_description_and_xp(self):
        text = N.achievement_message(_unlock())

        assert "Si comincia" in text
        assert "Hai registrato 25 spese." in text
        assert "+25 XP" in text

    def test_level_up_is_appended_only_when_present(self):
        assert "livello" not in N.achievement_message(_unlock())
        assert "livello 4" in N.achievement_message(_unlock(new_level=4))

    def test_english_locale(self):
        text = N.achievement_message(_unlock(new_level=3), locale="en")
        assert "level 3" in text

    def test_unknown_locale_falls_back_to_italian(self):
        assert "XP" in N.achievement_message(_unlock(), locale="xx")


class TestAggregateMessage:
    def test_lists_every_title_and_sums_xp(self):
        unlocks = [_unlock(f"c{i}", f"Titolo {i}", xp=10) for i in range(5)]
        text = N.aggregate_message(unlocks)

        assert "5" in text
        for i in range(5):
            assert f"Titolo {i}" in text
        assert "+50 XP" in text

    def test_reports_the_highest_level_reached(self):
        unlocks = [_unlock("a", "A", new_level=2), _unlock("b", "B", new_level=5)]
        assert "livello 5" in N.aggregate_message(unlocks)


class TestBuildMessages:
    def test_empty_input_produces_nothing(self):
        assert N.build_messages([]) == []

    def test_few_unlocks_are_celebrated_one_by_one(self):
        unlocks = [_unlock(f"c{i}", f"Titolo {i}") for i in range(N.MAX_INDIVIDUAL_MESSAGES)]
        messages = N.build_messages(unlocks)

        assert len(messages) == N.MAX_INDIVIDUAL_MESSAGES

    def test_many_unlocks_collapse_into_one_message(self):
        """Lo scenario del primo accesso dopo il backfill."""
        unlocks = [_unlock(f"c{i}", f"Titolo {i}") for i in range(N.MAX_INDIVIDUAL_MESSAGES + 1)]
        messages = N.build_messages(unlocks)

        assert len(messages) == 1
        assert f"Titolo {N.MAX_INDIVIDUAL_MESSAGES}" in messages[0]
