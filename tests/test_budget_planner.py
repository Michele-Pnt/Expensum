"""
tests/test_budget_planner.py — Test puri per src/budget_planner.py.

Il piano è top-down: parte dal reddito, sottrae risparmio target e costi fissi, e
distribuisce quel che resta. L'invariante centrale è che la somma dei budget
proposti non superi mai quello che l'utente guadagna — cosa che il vecchio
suggerimento (media delle spese passate) non garantiva affatto.

Nessun DB: storage finto, come in tests/test_savings_goals_service.py.
"""

import pytest
from datetime import date

from src.budget_planner import (
    DEFAULT_SAVINGS_RATE,
    build_budget_plan,
    _closed_months,
    _without_outliers,
)

pytestmark = pytest.mark.unit

TODAY = date(2026, 7, 15)


class FakeStorage:
    def __init__(self, expenses=None, incomes=None, categories=None,
                 subscriptions=None, goals=None):
        self._expenses = expenses or []
        self._incomes = incomes or []
        self._categories = categories or []
        self._subscriptions = subscriptions or []
        self._goals = goals or []

    def fetch_all_transactions(self, start_date, end_date):
        return [e for e in self._expenses if start_date <= e["date"] <= end_date]

    def fetch_income(self, start_date, end_date):
        return [i for i in self._incomes if start_date <= i["date"] <= end_date]

    def get_categories(self, include_archived=False):
        return self._categories

    def fetch_subscriptions(self):
        return self._subscriptions

    def fetch_savings_goals(self, status=None):
        return self._goals


def _expenses(category, amounts_by_month):
    """amounts_by_month: {(anno, mese): importo_totale_del_mese}."""
    return [
        {"date": date(y, m, 10), "amount": amount, "category": category}
        for (y, m), amount in amounts_by_month.items()
    ]


def _incomes(amounts_by_month):
    return [
        {"date": date(y, m, 1), "amount": amount}
        for (y, m), amount in amounts_by_month.items()
    ]


SIX_MONTHS = [(2026, 1), (2026, 2), (2026, 3), (2026, 4), (2026, 5), (2026, 6)]


def _plan_with(income=2000.0, spesa=600.0, svago=400.0, subscriptions=None, goals=None):
    storage = FakeStorage(
        expenses=(
            _expenses("Spesa", {m: spesa for m in SIX_MONTHS})
            + _expenses("Svago", {m: svago for m in SIX_MONTHS})
        ),
        incomes=_incomes({m: income for m in SIX_MONTHS}),
        categories=[
            {"id": 1, "name": "Spesa", "monthly_budget": None},
            {"id": 2, "name": "Svago", "monthly_budget": None},
        ],
        subscriptions=subscriptions or [],
        goals=goals or [],
    )
    return build_budget_plan(storage, TODAY)


class TestHelpers:
    def test_closed_months_excludes_current_month(self):
        months = _closed_months(TODAY, 6)
        assert (2026, 7) not in months, "il mese in corso è parziale, va escluso"
        assert months == SIX_MONTHS

    def test_outlier_filter_drops_anomalous_month(self):
        assert 5000.0 not in _without_outliers([100.0, 110.0, 105.0, 95.0, 5000.0])

    def test_outlier_filter_keeps_everything_with_few_points(self):
        assert _without_outliers([100.0, 5000.0]) == [100.0, 5000.0]


class TestSustainability:
    def test_proposed_budgets_never_exceed_distributable(self):
        """L'invariante centrale del piano."""
        plan = _plan_with()

        total = sum(c.proposed_budget for c in plan.categories)
        assert total <= plan.distributable + 0.01

    def test_distributable_is_income_minus_savings_and_fixed(self):
        plan = _plan_with(income=2000.0, subscriptions=[{"amount": 100.0}])

        assert plan.monthly_income == 2000.0
        assert plan.savings_target == 400.0  # 20% di default
        assert plan.fixed_costs == 100.0
        assert plan.distributable == 1500.0

    def test_overspending_user_gets_reduced_budgets(self):
        """Chi spende più di quanto guadagna riceve proposte più basse dello storico."""
        plan = _plan_with(income=1000.0, spesa=600.0, svago=400.0)

        assert plan.available is True
        for cat in plan.categories:
            assert cat.proposed_budget < cat.historical_median
            assert cat.delta < 0

    def test_proportions_between_categories_are_preserved(self):
        plan = _plan_with(spesa=600.0, svago=300.0)

        by_name = {c.name: c for c in plan.categories}
        ratio = by_name["Spesa"].proposed_budget / by_name["Svago"].proposed_budget
        assert ratio == pytest.approx(2.0, abs=0.01)


class TestSavingsGoalIntegration:
    def test_savings_rate_goal_drives_the_target(self):
        plan = _plan_with(income=2000.0, goals=[
            {"goal_type": "savings_rate", "target_amount": 30, "target_date": None},
        ])

        assert plan.savings_target == 600.0  # 30% di 2000
        assert plan.distributable == 1400.0

    def test_net_savings_goal_is_spread_over_remaining_months(self):
        plan = _plan_with(income=2000.0, goals=[
            {"goal_type": "net_savings", "target_amount": 1200,
             "target_date": date(2026, 1, 15)},  # già passata → spalmata su 12 mesi
        ])

        assert plan.savings_target == 100.0

    def test_default_rate_without_goals(self):
        plan = _plan_with(income=2000.0)
        assert plan.savings_target == pytest.approx(2000.0 * DEFAULT_SAVINGS_RATE)

    def test_most_demanding_goal_wins(self):
        plan = _plan_with(income=2000.0, goals=[
            {"goal_type": "savings_rate", "target_amount": 10, "target_date": None},
            {"goal_type": "savings_rate", "target_amount": 35, "target_date": None},
        ])
        assert plan.savings_target == 700.0


class TestHonestDegradation:
    def test_not_enough_history_returns_no_plan(self):
        storage = FakeStorage(
            expenses=_expenses("Spesa", {(2026, 6): 500.0}),
            incomes=_incomes({(2026, 6): 2000.0}),
            categories=[{"id": 1, "name": "Spesa", "monthly_budget": None}],
        )
        plan = build_budget_plan(storage, TODAY)

        assert plan.available is False
        assert plan.reason == "not_enough_history"
        assert plan.categories == []

    def test_no_income_falls_back_to_baseline(self):
        storage = FakeStorage(
            expenses=_expenses("Spesa", {m: 500.0 for m in SIX_MONTHS}),
            incomes=[],
            categories=[{"id": 1, "name": "Spesa", "monthly_budget": None}],
        )
        plan = build_budget_plan(storage, TODAY)

        assert plan.available is True
        assert plan.is_income_based is False
        assert plan.reason == "no_income_baseline_only"
        # Fotografia dello storico, dichiarata come tale.
        assert plan.categories[0].proposed_budget == plan.categories[0].historical_median

    def test_unsustainable_plan_is_reported_not_faked(self):
        """Costi fissi che divorano il reddito: nessun budget inventato."""
        plan = _plan_with(income=1000.0, subscriptions=[{"amount": 900.0}])

        assert plan.available is False
        assert plan.reason == "not_sustainable"
        assert plan.distributable < 0
        assert plan.categories == []

    def test_current_month_is_never_counted(self):
        """Il mese in corso è parziale: includerlo distorceva la media."""
        storage = FakeStorage(
            expenses=(
                _expenses("Spesa", {m: 300.0 for m in SIX_MONTHS})
                # Luglio (mese di TODAY) con un importo assurdo: va ignorato.
                + _expenses("Spesa", {(2026, 7): 9999.0})
            ),
            incomes=_incomes({m: 2000.0 for m in SIX_MONTHS}),
            categories=[{"id": 1, "name": "Spesa", "monthly_budget": None}],
        )
        plan = build_budget_plan(storage, TODAY)

        assert plan.categories[0].historical_median == 300.0

    def test_unknown_category_is_ignored(self):
        """Spese su categorie archiviate/sconosciute non generano budget."""
        storage = FakeStorage(
            expenses=(
                _expenses("Spesa", {m: 300.0 for m in SIX_MONTHS})
                + _expenses("Archiviata", {m: 200.0 for m in SIX_MONTHS})
            ),
            incomes=_incomes({m: 2000.0 for m in SIX_MONTHS}),
            categories=[{"id": 1, "name": "Spesa", "monthly_budget": None}],
        )
        plan = build_budget_plan(storage, TODAY)

        assert [c.name for c in plan.categories] == ["Spesa"]


class TestSerialization:
    def test_to_dict_exposes_everything_the_ui_needs(self):
        payload = _plan_with().to_dict()

        assert set(payload) >= {
            "available", "monthly_income", "savings_target", "fixed_costs",
            "distributable", "months_of_history", "is_income_based", "categories",
        }
        assert set(payload["categories"][0]) >= {
            "category_id", "name", "historical_median", "proposed_budget", "delta",
        }
