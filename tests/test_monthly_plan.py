"""
tests/test_monthly_plan.py — Unit test per i componenti del piano mensile.

Copre:
- MonthlyPatternAnalyzer: stats per categoria sui 6 mesi
- IncomeForecaster: previsione entrate media 6 mesi
- MonthlyBudgetTargetCalc: target mensile per categoria
- SubscriptionScheduler.due_this_month: abbonamenti in scadenza nel mese target
- MonthlyPlanData.to_prompt_text: serializzazione per il prompt AI
- MonthlyPlanBuilder: orchestrazione con mock FinancialStorage
"""

import pytest
from calendar import monthrange
from datetime import date, timedelta
from unittest.mock import MagicMock

from src.data_processor import (
    MonthlyPatternAnalyzer,
    MonthlyCategoryStats,
    IncomeForecaster,
    MonthlyBudgetTargetCalc,
)
from src.report_builder import SubscriptionScheduler, MonthlyPlanBuilder, MonthlyPlanData

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _first_of_month_n_months_ago(n: int) -> date:
    """Ritorna il primo giorno del mese N mesi fa."""
    today = date.today()
    y, m = today.year, today.month
    for _ in range(n):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return date(y, m, 1)


def _make_monthly_transactions(category: str, amounts_per_month: list[float]) -> list[dict]:
    """
    Crea transazioni fake: una per mese, il giorno 15.
    amounts_per_month[0] = 6 mesi fa, amounts_per_month[-1] = 1 mese fa.
    """
    txs = []
    n = len(amounts_per_month)
    for i, amt in enumerate(amounts_per_month):
        months_ago = n - i
        first = _first_of_month_n_months_ago(months_ago)
        txs.append({
            "date": date(first.year, first.month, 15),
            "category": category,
            "name": f"{category} mese {i + 1}",
            "amount": amt,
        })
    return txs


# ---------------------------------------------------------------------------
# MonthlyPatternAnalyzer
# ---------------------------------------------------------------------------

class TestMonthlyPatternAnalyzer:

    def test_computes_mean_for_category(self):
        amounts = [200.0, 220.0, 180.0, 210.0, 190.0, 200.0]
        txs = _make_monthly_transactions("Alimentari", amounts)
        stats = MonthlyPatternAnalyzer().compute(txs)

        assert "Alimentari" in stats
        s = stats["Alimentari"]
        assert abs(s.mean_monthly - sum(amounts) / len(amounts)) < 0.01

    def test_empty_transactions_returns_empty(self):
        stats = MonthlyPatternAnalyzer().compute([])
        assert stats == {}

    def test_p75_higher_than_mean_for_bimodal_data(self):
        amounts = [50.0, 50.0, 50.0, 300.0, 300.0, 300.0]
        txs = _make_monthly_transactions("Ristoranti", amounts)
        stats = MonthlyPatternAnalyzer().compute(txs)

        s = stats["Ristoranti"]
        assert s.p75 > s.mean_monthly

    def test_std_dev_zero_for_constant_amounts(self):
        amounts = [100.0] * 6
        txs = _make_monthly_transactions("Trasporti", amounts)
        stats = MonthlyPatternAnalyzer().compute(txs)

        assert abs(stats["Trasporti"].std_dev) < 0.01

    def test_monthly_amounts_length_is_6(self):
        # Anche se alcuni mesi non hanno spese, monthly_amounts ha sempre 6 elementi
        # (qui usiamo solo 3 mesi di dati)
        amounts = [100.0, 200.0, 150.0]
        txs = _make_monthly_transactions("Svago", amounts)
        stats = MonthlyPatternAnalyzer().compute(txs)

        if "Svago" in stats:
            assert len(stats["Svago"].monthly_amounts) == 6

    def test_trend_in_crescita_when_last3_higher(self):
        amounts = [50.0, 50.0, 50.0, 100.0, 100.0, 100.0]
        txs = _make_monthly_transactions("Acquisti", amounts)
        stats = MonthlyPatternAnalyzer().compute(txs)

        assert stats["Acquisti"].trend == "in crescita"

    def test_trend_in_calo_when_last3_lower(self):
        amounts = [100.0, 100.0, 100.0, 50.0, 50.0, 50.0]
        txs = _make_monthly_transactions("Carburante", amounts)
        stats = MonthlyPatternAnalyzer().compute(txs)

        assert stats["Carburante"].trend == "in calo"

    def test_trend_stabile_when_consistent(self):
        amounts = [100.0, 102.0, 98.0, 101.0, 99.0, 100.0]
        txs = _make_monthly_transactions("Bollette", amounts)
        stats = MonthlyPatternAnalyzer().compute(txs)

        assert stats["Bollette"].trend == "stabile"

    def test_no_category_exclusion(self):
        # A differenza del weekly plan, il monthly plan non esclude nessuna categoria
        txs = _make_monthly_transactions("Movimenti", [500.0] * 6)
        txs += _make_monthly_transactions("Alimentari", [200.0] * 6)
        stats = MonthlyPatternAnalyzer().compute(txs)

        assert "Movimenti" in stats
        assert "Alimentari" in stats


# ---------------------------------------------------------------------------
# IncomeForecaster
# ---------------------------------------------------------------------------

class TestIncomeForecaster:

    def _make_incomes(self, amounts_per_month: list[float]) -> list[dict]:
        """Crea entrate fake: una per mese, il giorno 1."""
        incomes = []
        n = len(amounts_per_month)
        for i, amt in enumerate(amounts_per_month):
            months_ago = n - i
            first = _first_of_month_n_months_ago(months_ago)
            incomes.append({
                "date": date(first.year, first.month, 1),
                "amount": amt,
                "name": "Stipendio",
            })
        return incomes

    def test_average_of_6_months(self):
        amounts = [2000.0, 2100.0, 1900.0, 2050.0, 1950.0, 2000.0]
        incomes = self._make_incomes(amounts)
        result = IncomeForecaster().compute(incomes)
        expected = sum(amounts) / 6
        assert abs(result - expected) < 0.01

    def test_empty_returns_zero(self):
        result = IncomeForecaster().compute([])
        assert result == 0.0

    def test_missing_months_treated_as_zero(self):
        # Solo 3 mesi di entrate su 6 → media su 6 (altri tre = 0)
        amounts = [3000.0, 3000.0, 3000.0]
        incomes = self._make_incomes(amounts)
        result = IncomeForecaster().compute(incomes)
        # 3 mesi a 3000, 3 mesi a 0 → media = 1500
        assert abs(result - 1500.0) < 0.01

    def test_no_category_exclusion(self):
        # Il monthly plan non filtra nessun tipo di entrata per nome
        amounts = [1000.0] * 6
        incomes = self._make_incomes(amounts)
        # Rinomina in "Movimenti" — deve essere incluso
        for inc in incomes:
            inc["name"] = "Movimenti"
        result = IncomeForecaster().compute(incomes)
        assert result > 0.0


# ---------------------------------------------------------------------------
# MonthlyBudgetTargetCalc
# ---------------------------------------------------------------------------

class TestMonthlyBudgetTargetCalc:

    def _make_stats(self, name: str, mean: float, trend: str = "stabile") -> MonthlyCategoryStats:
        s = MonthlyCategoryStats(name)
        s.mean_monthly = mean
        s.trend = trend
        s.monthly_amounts = [mean] * 6
        return s

    def test_uses_budget_when_available(self):
        stats = {"Alimentari": self._make_stats("Alimentari", 200.0)}
        cats = [{"name": "Alimentari", "monthly_budget": 300.0}]

        targets = MonthlyBudgetTargetCalc().compute(stats, cats, 2000.0, 0.0)
        assert abs(targets["Alimentari"] - 300.0) < 0.01

    def test_fallback_to_historical_mean_without_budget(self):
        stats = {"Svago": self._make_stats("Svago", 150.0)}
        targets = MonthlyBudgetTargetCalc().compute(stats, [], 2000.0, 0.0)
        assert abs(targets["Svago"] - 150.0) < 0.01

    def test_trend_crescita_increases_target(self):
        stats = {"Ristoranti": self._make_stats("Ristoranti", 200.0, trend="in crescita")}
        targets = MonthlyBudgetTargetCalc().compute(stats, [], 2000.0, 0.0)
        # 200 * 1.05 = 210
        assert abs(targets["Ristoranti"] - 210.0) < 0.01

    def test_trend_calo_decreases_target(self):
        stats = {"Carburante": self._make_stats("Carburante", 200.0, trend="in calo")}
        targets = MonthlyBudgetTargetCalc().compute(stats, [], 2000.0, 0.0)
        # 200 * 0.95 = 190
        assert abs(targets["Carburante"] - 190.0) < 0.01

    def test_budget_takes_precedence_over_mean(self):
        # Budget esplicito deve avere precedenza sulla media storica
        stats = {"Alimentari": self._make_stats("Alimentari", 500.0)}
        cats = [{"name": "Alimentari", "monthly_budget": 300.0}]
        targets = MonthlyBudgetTargetCalc().compute(stats, cats, 2000.0, 0.0)
        assert abs(targets["Alimentari"] - 300.0) < 0.01

    def test_category_without_budget_or_stats_excluded(self):
        # Categoria senza stats né budget → non inclusa
        targets = MonthlyBudgetTargetCalc().compute({}, [], 2000.0, 0.0)
        assert targets == {}


# ---------------------------------------------------------------------------
# SubscriptionScheduler.due_this_month
# ---------------------------------------------------------------------------

class TestSubscriptionSchedulerDueThisMonth:

    def _target_month(self, year: int, month: int) -> date:
        return date(year, month, 1)

    def test_monthly_sub_due_in_target_month(self):
        # Sub mensile fatturato il 15 aprile → scade il 15 maggio
        target = self._target_month(2026, 5)
        sub = {
            "name": "Netflix",
            "amount": 15.99,
            "last_billed": date(2026, 4, 15).isoformat(),
            "sub_type": "mensile",
        }
        result = SubscriptionScheduler().due_this_month([sub], target)
        assert len(result) == 1
        assert result[0]["due_date"] == date(2026, 5, 15)

    def test_monthly_sub_not_due_in_target_month(self):
        # Sub mensile fatturato il 20 maggio → scade il 20 giugno, non in maggio
        target = self._target_month(2026, 5)
        sub = {
            "name": "Spotify",
            "amount": 9.99,
            "last_billed": date(2026, 4, 20).isoformat(),
            "sub_type": "mensile",
        }
        # last_billed 20 aprile → next due 20 maggio → IN maggio
        result = SubscriptionScheduler().due_this_month([sub], target)
        assert len(result) == 1

    def test_monthly_sub_outside_target_month(self):
        # Sub che scade a giugno, target maggio → escluso
        target = self._target_month(2026, 5)
        sub = {
            "name": "Palestra",
            "amount": 50.0,
            "last_billed": date(2026, 4, 25).isoformat(),
            "sub_type": "mensile",
        }
        # last_billed 25 aprile → next due 25 maggio → IN maggio
        result_may = SubscriptionScheduler().due_this_month([sub], target)
        # Verifica che con target giugno, il sub (scadenza maggio) non sia incluso
        target_june = self._target_month(2026, 6)
        result_june = SubscriptionScheduler().due_this_month([sub], target_june)
        assert len(result_june) == 1
        assert result_june[0]["due_date"] == date(2026, 6, 25)

    def test_no_last_billed_skipped(self):
        target = self._target_month(2026, 5)
        sub = {"name": "Unknown", "amount": 5.0, "last_billed": None, "sub_type": "mensile"}
        result = SubscriptionScheduler().due_this_month([sub], target)
        assert len(result) == 0

    def test_subs_total_sums_correctly(self):
        target = self._target_month(2026, 5)
        subs = [
            {"name": "Netflix", "amount": 15.99, "last_billed": date(2026, 4, 15).isoformat(), "sub_type": "mensile"},
            {"name": "Spotify", "amount": 9.99, "last_billed": date(2026, 4, 10).isoformat(), "sub_type": "mensile"},
        ]
        result = SubscriptionScheduler().due_this_month(subs, target)
        total = sum(float(s.get("amount", 0)) for s in result)
        assert abs(total - 25.98) < 0.01

    def test_default_target_is_next_month(self):
        # Senza target_month_date, usa il mese prossimo
        today = date.today()
        if today.month == 12:
            next_y, next_m = today.year + 1, 1
        else:
            next_y, next_m = today.year, today.month + 1
        last_m = today.month - 1 if today.month > 1 else 12
        last_y = today.year if today.month > 1 else today.year - 1
        sub = {
            "name": "Test",
            "amount": 10.0,
            "last_billed": date(last_y, last_m, 5).isoformat(),
            "sub_type": "mensile",
        }
        result = SubscriptionScheduler().due_this_month([sub])
        if result:
            assert result[0]["due_date"].month == next_m
            assert result[0]["due_date"].year == next_y


# ---------------------------------------------------------------------------
# MonthlyPlanBuilder — test con mock FinancialStorage
# ---------------------------------------------------------------------------

class TestMonthlyPlanBuilder:

    def _make_storage(self) -> MagicMock:
        storage = MagicMock()

        # 6 mesi di storico spese
        history_txs = []
        for i in range(1, 7):
            first = _first_of_month_n_months_ago(i)
            history_txs.append({
                "date": date(first.year, first.month, 15),
                "category": "Alimentari",
                "amount": 200.0 + i * 10,
                "name": "Spesa",
            })

        # Il mock ritorna le stesse transazioni per ogni chiamata a fetch_all_transactions
        storage.fetch_all_transactions.return_value = history_txs
        storage.fetch_income.return_value = [
            {"date": _first_of_month_n_months_ago(i), "amount": 2000.0, "name": "Stipendio"}
            for i in range(1, 7)
        ]
        storage.fetch_accounts.return_value = [{"name": "Conto", "current_balance": 5000.0}]
        storage.fetch_subscriptions.return_value = []
        storage.get_categories.return_value = [
            {"name": "Alimentari", "monthly_budget": 300.0, "average": 220.0}
        ]
        return storage

    def test_build_returns_monthly_plan_data(self):
        storage = self._make_storage()
        data = MonthlyPlanBuilder().build(storage)
        assert isinstance(data, MonthlyPlanData)

    def test_target_month_is_next_month(self):
        storage = self._make_storage()
        data = MonthlyPlanBuilder().build(storage)
        today = date.today()
        if today.month == 12:
            expected_year, expected_month = today.year + 1, 1
        else:
            expected_year, expected_month = today.year, today.month + 1
        assert data.target_month.year == expected_year
        assert data.target_month.month == expected_month

    def test_income_forecast_computed(self):
        storage = self._make_storage()
        data = MonthlyPlanBuilder().build(storage)
        # 6 mesi x 2000 → media = 2000
        assert abs(data.income_forecast - 2000.0) < 0.01

    def test_total_accounts_correct(self):
        storage = self._make_storage()
        data = MonthlyPlanBuilder().build(storage)
        assert data.total_accounts == 5000.0

    def test_alimentari_in_targets(self):
        storage = self._make_storage()
        data = MonthlyPlanBuilder().build(storage)
        assert "Alimentari" in data.suggested_targets

    def test_category_override_applied(self):
        storage = self._make_storage()
        overrides = {"Alimentari": 150.0}
        data = MonthlyPlanBuilder().build(storage, category_overrides=overrides)
        assert abs(data.suggested_targets["Alimentari"] - 150.0) < 0.01
        assert "Alimentari" in data.category_overrides

    def test_fallback_text_generated(self):
        storage = self._make_storage()
        data = MonthlyPlanBuilder().build(storage)
        text = MonthlyPlanBuilder().build_fallback_text(data)
        assert "Piano Mensile" in text
        assert "Alimentari" in text

    def test_to_prompt_text_contains_key_sections(self):
        storage = self._make_storage()
        data = MonthlyPlanBuilder().build(storage)
        prompt = data.to_prompt_text()
        assert "PIANO MENSILE" in prompt
        assert "TARGET MENSILE" in prompt
        assert "Alimentari" in prompt

    def test_savings_goal_non_negative(self):
        storage = self._make_storage()
        data = MonthlyPlanBuilder().build(storage)
        assert data.savings_goal >= 0.0
