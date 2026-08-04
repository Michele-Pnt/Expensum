"""
tests/test_gamification_cycles.py — Achievement ciclici e milestone cumulative.

I cicli sono l'asse che non si esaurisce: ogni mese si riguadagnano, per sempre.
Le famiglie a tier invece finiscono per costruzione, ed è il motivo per cui dopo
il primo anno la progressione si spegneva.

Le due proprietà da difendere:
1. un mese non può essere premiato due volte, nemmeno rieseguendo il job;
2. le milestone cumulative non regrediscono quando la serie consecutiva si rompe.
"""

import pytest
from datetime import date

from src.gamification import backfill, engine
from src.gamification import metrics as M
from src.gamification.registry import BY_CODE
from src.user_store import UserAchievement

pytestmark = pytest.mark.integration


class FakeStorage:
    def __init__(self, expenses=None):
        self._expenses = expenses or []

    def fetch_all_transactions(self, start, end):
        return [e for e in self._expenses if start <= e["date"] <= end]


def _month(year, month, n=10, sporche=0):
    out = [{"date": date(year, month, 1), "amount": 10.0, "category": "Spesa"} for _ in range(n)]
    out += [{"date": date(year, month, 2), "amount": 5.0, "category": "Altro"}
            for _ in range(sporche)]
    return out


@pytest.fixture
def store(mock_db_session):
    mock_db_session.add_user(chat_id="u1")
    return mock_db_session


class TestCycleAwarding:
    def test_a_clean_month_awards_two_cycles(self, store):
        storage = FakeStorage(_month(2026, 6))
        unlocks = backfill.evaluate_month(store, "u1", storage, 2026, 6)

        codes = {u.definition.code for u in unlocks}
        assert "cycle_active_month" in codes
        assert "cycle_clean_month" in codes

    def test_a_dirty_month_awards_only_the_active_cycle(self, store):
        storage = FakeStorage(_month(2026, 6, sporche=1))
        codes = {u.definition.code for u in backfill.evaluate_month(store, "u1", storage, 2026, 6)}

        assert "cycle_active_month" in codes
        assert "cycle_clean_month" not in codes

    def test_the_same_month_is_never_awarded_twice(self, store):
        storage = FakeStorage(_month(2026, 6))
        backfill.evaluate_month(store, "u1", storage, 2026, 6)
        secondo = backfill.evaluate_month(store, "u1", storage, 2026, 6)

        assert secondo == []
        with store.Session() as s:
            assert s.query(UserAchievement).filter_by(code="cycle_clean_month").count() == 1

    def test_different_months_are_separate_cycles(self, store):
        storage = FakeStorage(_month(2026, 5) + _month(2026, 6))
        backfill.evaluate_month(store, "u1", storage, 2026, 5)
        backfill.evaluate_month(store, "u1", storage, 2026, 6)

        with store.Session() as s:
            righe = s.query(UserAchievement).filter_by(code="cycle_clean_month").all()
        assert {r.dedup_key for r in righe} == {"2026-05", "2026-06"}

    def test_an_empty_month_awards_nothing(self, store):
        storage = FakeStorage(_month(2026, 6, n=2))
        assert backfill.evaluate_month(store, "u1", storage, 2026, 6) == []


class TestMilestones:
    def test_cumulative_milestone_unlocks_from_cycles(self, store):
        storage = FakeStorage(sum((_month(2026, m) for m in (4, 5, 6)), []))
        for m in (4, 5, 6):
            unlocks = backfill.evaluate_month(store, "u1", storage, 2026, m)

        codes = {u.definition.code for u in unlocks}
        assert "clean_months_3" in codes, "il terzo mese pulito sblocca la milestone"
        assert "active_months_3" in codes

    def test_totals_survive_a_broken_streak(self, store):
        """La differenza fra serie e totale: è ciò che rende le milestone raggiungibili."""
        storage = FakeStorage(_month(2026, 4) + _month(2026, 5, sporche=1) + _month(2026, 6))
        for m in (4, 5, 6):
            backfill.evaluate_month(store, "u1", storage, 2026, m)

        counters = engine.get_metrics(store, "u1")
        assert counters[M.CLEAN_MONTHS_TOTAL] == 2
        assert counters[M.CLEAN_MONTHS_STREAK] == 1
        assert counters[M.ACTIVE_MONTHS_TOTAL] == 3


class TestNeverEnding:
    def test_the_cycle_family_has_no_last_tier(self):
        """Regressione di design: i cicli non devono esaurirsi come i tier."""
        ciclici = [a for a in BY_CODE.values() if a.repeatable]
        assert {a.code for a in ciclici} >= {
            "cycle_active_month", "cycle_clean_month", "cycle_report_month",
        }
        assert all(a.metric is None for a in ciclici), "un ciclo non ha soglia da superare"

    def test_monthly_income_is_modest_but_perpetual(self):
        """Poco per volta, ma senza fine: è il motore di lungo periodo."""
        rendita = sum(BY_CODE[c].xp for c in
                      ("cycle_active_month", "cycle_clean_month", "cycle_report_month"))
        assert 40 <= rendita <= 100, "una rendita fuori scala svaluterebbe le milestone"
