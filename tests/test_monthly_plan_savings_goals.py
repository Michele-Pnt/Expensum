"""
tests/test_monthly_plan_savings_goals.py — Integrazione obiettivi di risparmio
nel piano mensile (MonthlyPlanBuilder / MonthlyPlanData).
"""
import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock

from src.report_builder import MonthlyPlanBuilder

pytestmark = pytest.mark.unit


def _first_of_month_n_months_ago(n: int) -> date:
    today = date.today()
    y, m = today.year, today.month
    for _ in range(n):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return date(y, m, 1)


def _base_storage() -> MagicMock:
    storage = MagicMock()
    history_txs = [
        {"date": date(_first_of_month_n_months_ago(i).year, _first_of_month_n_months_ago(i).month, 15),
         "category": "Alimentari", "amount": 200.0, "name": "Spesa"}
        for i in range(1, 7)
    ]
    storage.fetch_all_transactions.return_value = history_txs
    storage.fetch_income.return_value = [
        {"date": _first_of_month_n_months_ago(i), "amount": 2000.0, "name": "Stipendio", "account_id": 1}
        for i in range(1, 7)
    ]
    storage.fetch_accounts.return_value = [{"id": 1, "name": "Conto", "current_balance": 5000.0, "opening_balance": 0.0}]
    storage.fetch_subscriptions.return_value = []
    storage.get_categories.return_value = [{"name": "Alimentari", "monthly_budget": 300.0, "average": 220.0}]
    return storage


class TestSavingsGoalsSectionOmitted:
    def test_no_section_when_no_active_goals(self):
        storage = _base_storage()
        storage.fetch_savings_goals.return_value = []
        data = MonthlyPlanBuilder().build(storage)
        assert data.savings_goals_summary == []
        assert "OBIETTIVI DI RISPARMIO" not in data.to_prompt_text()

    def test_no_crash_when_fetch_savings_goals_not_supported(self):
        """Storage che non implementa fetch_savings_goals (es. mock non configurato
        esplicitamente) non deve mai far fallire la generazione del piano mensile."""
        storage = _base_storage()
        storage.fetch_savings_goals.side_effect = NotImplementedError()
        data = MonthlyPlanBuilder().build(storage)
        assert data.savings_goals_summary == []


class TestSavingsGoalsSectionIncluded:
    def test_active_goal_appears_in_summary_and_prompt_text(self):
        storage = _base_storage()
        storage.fetch_savings_goals.return_value = [{
            "id": 1, "goal_type": "net_worth", "name": "Fondo emergenza",
            "target_amount": 10000.0, "account_id": None, "category_id": None,
            "start_date": _first_of_month_n_months_ago(6).isoformat(),
            "target_date": None, "status": "active",
        }]
        data = MonthlyPlanBuilder().build(storage)

        assert len(data.savings_goals_summary) == 1
        summary = data.savings_goals_summary[0]
        assert summary["name"] == "Fondo emergenza"
        assert summary["progress_pct"] == pytest.approx(50.0)  # 5000/10000*100

        text = data.to_prompt_text()
        assert "OBIETTIVI DI RISPARMIO" in text
        assert "Fondo emergenza" in text
