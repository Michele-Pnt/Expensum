"""
tests/test_savings_goals_service.py — Test puri per src/savings_goals_service.py.

Nessun DB: la storage e' un doppio scritto a mano che risponde con dati fissi,
cosi' i test isolano solo la logica di calcolo (progresso, ETA, voto).
"""
import pytest
from datetime import date

from src.savings_goals_service import (
    compute_goal_progress,
    compute_monthly_score,
    explain_score,
    _weighted_monthly_delta,
)

pytestmark = pytest.mark.unit


class FakeStorage:
    """Doppio minimale di FinancialStorage: risponde solo a cio' che serve al test."""

    def __init__(self, accounts=None, incomes=None, expenses=None, categories=None,
                 monthly_balances=None, transfers=None):
        self._accounts = accounts or []
        self._incomes = incomes or []
        self._expenses = expenses or []
        self._categories = categories or []
        self._monthly_balances = monthly_balances or []
        self._transfers = transfers or []

    def fetch_accounts(self):
        return self._accounts

    def fetch_income(self, start_date, end_date):
        return [i for i in self._incomes if start_date <= i["date"] <= end_date]

    def fetch_all_transactions(self, start_date, end_date):
        return [e for e in self._expenses if start_date <= e["date"] <= end_date]

    def get_categories(self):
        return self._categories

    def fetch_monthly_balances(self, start_date, end_date):
        return [b for b in self._monthly_balances if start_date <= date(b["year"], b["month"], 1) <= end_date]

    def fetch_transfers(self, start_date, end_date):
        return [t for t in self._transfers if start_date <= t["date"] <= end_date]


# ---------------------------------------------------------------------------
# _weighted_monthly_delta
# ---------------------------------------------------------------------------

class TestWeightedMonthlyDelta:
    def test_none_with_fewer_than_two_points(self):
        assert _weighted_monthly_delta([100.0]) is None
        assert _weighted_monthly_delta([]) is None

    def test_positive_trend(self):
        # delta costanti di 10 -> media pesata deve restare 10
        assert _weighted_monthly_delta([100.0, 110.0, 120.0, 130.0]) == pytest.approx(10.0)

    def test_recent_months_weigh_more(self):
        # Un salto grande solo nell'ultimo mese pesa di piu' di uno vecchio uguale
        values_recent_jump = [100.0, 100.0, 100.0, 200.0]
        values_old_jump = [100.0, 200.0, 200.0, 200.0]
        assert _weighted_monthly_delta(values_recent_jump) > _weighted_monthly_delta(values_old_jump)


# ---------------------------------------------------------------------------
# compute_goal_progress — net_savings
# ---------------------------------------------------------------------------

class TestNetSavingsProgress:
    def test_progress_and_eta_with_positive_trend(self):
        today = date(2026, 7, 15)
        goal = {
            "goal_type": "net_savings", "target_amount": 1000.0,
            "start_date": "2026-01-01", "target_date": None,
        }
        storage = FakeStorage(
            incomes=[{"date": date(2026, m, 1), "amount": 500.0} for m in range(1, 8)],
            expenses=[{"date": date(2026, m, 1), "amount": 400.0} for m in range(1, 8)],
            monthly_balances=[{"year": 2026, "month": m, "net_savings": 100.0} for m in range(1, 8)],
        )
        progress = compute_goal_progress(storage, goal, today=today)
        assert progress["evaluable"] is True
        assert progress["current"] == pytest.approx(700.0)
        assert progress["progress_pct"] == pytest.approx(70.0)
        assert progress["eta_date"] is not None
        assert progress["eta_date"] > today

    def test_not_reachable_when_trend_is_negative(self):
        today = date(2026, 7, 15)
        goal = {
            "goal_type": "net_savings", "target_amount": 1000.0,
            "start_date": "2026-01-01", "target_date": None,
        }
        storage = FakeStorage(
            incomes=[{"date": date(2026, m, 1), "amount": 100.0} for m in range(1, 8)],
            expenses=[{"date": date(2026, m, 1), "amount": 100.0} for m in range(1, 8)],
            monthly_balances=[{"year": 2026, "month": m, "net_savings": -50.0} for m in range(1, 8)],
        )
        progress = compute_goal_progress(storage, goal, today=today)
        assert progress["eta_date"] is None


# ---------------------------------------------------------------------------
# compute_goal_progress — account_balance / net_worth
# ---------------------------------------------------------------------------

class TestAccountBalanceAndNetWorth:
    def test_account_balance_not_evaluable_if_account_missing(self):
        goal = {"goal_type": "account_balance", "target_amount": 500.0, "account_id": 99,
                "start_date": "2026-01-01", "target_date": None}
        storage = FakeStorage(accounts=[{"id": 1, "current_balance": 100.0, "opening_balance": 0.0}])
        progress = compute_goal_progress(storage, goal, today=date(2026, 7, 1))
        assert progress["evaluable"] is False

    def test_net_worth_sums_all_accounts(self):
        goal = {"goal_type": "net_worth", "target_amount": 1000.0,
                "start_date": "2026-01-01", "target_date": None}
        storage = FakeStorage(accounts=[
            {"id": 1, "current_balance": 300.0, "opening_balance": 0.0},
            {"id": 2, "current_balance": 400.0, "opening_balance": 0.0},
        ])
        progress = compute_goal_progress(storage, goal, today=date(2026, 7, 1))
        assert progress["current"] == pytest.approx(700.0)
        assert progress["progress_pct"] == pytest.approx(70.0)


# ---------------------------------------------------------------------------
# compute_goal_progress — savings_rate
# ---------------------------------------------------------------------------

class TestSavingsRate:
    def test_not_evaluable_with_zero_income(self):
        goal = {"goal_type": "savings_rate", "target_amount": 20.0,
                "start_date": "2026-07-01", "target_date": None}
        storage = FakeStorage(incomes=[], expenses=[])
        progress = compute_goal_progress(storage, goal, today=date(2026, 7, 15))
        assert progress["evaluable"] is False

    def test_computes_saved_percentage_of_income(self):
        goal = {"goal_type": "savings_rate", "target_amount": 20.0,
                "start_date": "2026-07-01", "target_date": None}
        storage = FakeStorage(
            incomes=[{"date": date(2026, 7, 1), "amount": 1000.0}],
            expenses=[{"date": date(2026, 7, 10), "amount": 750.0}],
        )
        progress = compute_goal_progress(storage, goal, today=date(2026, 7, 15))
        assert progress["current"] == pytest.approx(25.0)  # (1000-750)/1000*100


# ---------------------------------------------------------------------------
# compute_goal_progress — category_spending_reduction
# ---------------------------------------------------------------------------

class TestCategorySpendingReduction:
    def test_below_target_gives_progress_over_100(self):
        goal = {"goal_type": "category_spending_reduction", "target_amount": 200.0,
                "category_id": 5, "start_date": "2026-07-01", "target_date": None}
        storage = FakeStorage(
            categories=[{"id": 5, "name": "Ristoranti"}],
            expenses=[{"date": date(2026, 7, 10), "amount": 100.0, "category": "Ristoranti"}],
        )
        progress = compute_goal_progress(storage, goal, today=date(2026, 7, 15))
        assert progress["current"] == pytest.approx(100.0)
        assert progress["progress_pct"] == pytest.approx(50.0)  # (1 - 100/200)*100


# ---------------------------------------------------------------------------
# compute_monthly_score
# ---------------------------------------------------------------------------

class TestMonthlyScore:
    def test_savings_rate_labels(self):
        goal = {"goal_type": "savings_rate", "target_amount": 20.0}
        progress = {"evaluable": True, "current": 26.0, "progress_pct": 130.0}
        score = compute_monthly_score(None, goal, progress, today=date(2026, 7, 15))
        assert score["score_label"] == "Ottimo mese"

    def test_insufficient_data_label(self):
        goal = {"goal_type": "net_savings", "target_amount": 1000.0}
        progress = {"evaluable": False}
        score = compute_monthly_score(None, goal, progress)
        assert score["score_label"] == "Dati insufficienti"


# ---------------------------------------------------------------------------
# explain_score
# ---------------------------------------------------------------------------

class TestExplainScore:
    def test_savings_rate_explanation_contains_both_numbers(self):
        goal = {"goal_type": "savings_rate", "target_amount": 20.0}
        score = {"score_label": "Obiettivo centrato", "pace_effettivo": 22.0, "pace_richiesto": 20.0}
        text = explain_score(goal, score, markdown=False)
        assert "22%" in text
        assert "20%" in text

    def test_negative_pace_uses_losing_wording(self):
        goal = {
            "goal_type": "net_worth", "target_amount": 5000.0,
            "target_date": "2026-12-31",
        }
        score = {
            "score_label": "Fuori rotta", "pace_effettivo": -123.0, "pace_richiesto": 828.0,
        }
        text = explain_score(goal, score, markdown=False)
        assert "perdendo" in text
        assert "123" in text
        assert "-123" not in text
        assert "circa 828" in text
        assert "~" not in text

    def test_positive_pace_uses_circa_not_tilde(self):
        goal = {
            "goal_type": "net_worth", "target_amount": 5000.0,
            "target_date": "2026-12-31",
        }
        score = {
            "score_label": "In linea", "pace_effettivo": 200.0, "pace_richiesto": 250.0,
        }
        text = explain_score(goal, score, markdown=False)
        assert "circa" in text
        assert "~" not in text

    def test_insufficient_data_explanation(self):
        goal = {"goal_type": "net_savings", "target_amount": 1000.0}
        score = {"score_label": "Dati insufficienti", "pace_effettivo": None, "pace_richiesto": None}
        text = explain_score(goal, score)
        assert "Dati insufficienti" in text
