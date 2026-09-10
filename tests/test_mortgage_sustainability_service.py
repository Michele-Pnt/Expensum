"""Tests for the storage-agnostic sustainability profile adapter."""

from datetime import date

import pytest

from src.mortgage_sustainability_service import (
    build_sustainability_input,
    build_sustainability_prefill,
)


pytestmark = pytest.mark.unit


class StorageStub:
    def fetch_all_transactions(self, start_date, end_date):
        return [
            {"date": date(2026, 4, 10), "amount": 100, "category": "Svago"},
            {"date": date(2026, 5, 10), "amount": 200, "category": "Svago"},
            {"date": date(2026, 6, 10), "amount": 300, "category": "Svago"},
        ]

    def fetch_income(self, start_date, end_date):
        return [
            {"date": date(2026, 4, 1), "amount": 2500, "income_type": "Stipendio"},
            {"date": date(2026, 5, 1), "amount": 2500, "income_type": "Stipendio"},
            {"date": date(2026, 6, 1), "amount": 2500, "income_type": "Stipendio"},
        ]

    def fetch_accounts(self):
        return [{"current_balance": 10000}]

    def get_categories(self):
        return [{"id": 7, "name": "Svago", "monthly_budget": None}]


class StringDateStorageStub(StorageStub):
    def fetch_all_transactions(self, start_date, end_date):
        return [
            {"date": "2026-04-10", "amount": 100, "category": "Svago"},
            {"date": "2026-05-10", "amount": 200, "category": "Svago"},
            {"date": "2026-06-10", "amount": 300, "category": "Svago"},
        ]

    def fetch_income(self, start_date, end_date):
        return [
            {"date": "2026-04-01", "amount": 2500, "income_type": "Stipendio"},
            {"date": "2026-05-01", "amount": 2500, "income_type": "Stipendio"},
            {"date": "2026-06-01", "amount": 2500, "income_type": "Stipendio"},
        ]


def test_builds_three_month_observed_profile_and_selected_category() -> None:
    result = build_sustainability_input(
        StorageStub(),
        {
            "principal": 100000,
            "tan_annual": 3,
            "duration_months": 240,
            "rate_type": "fisso",
            "selected_category_ids": [7],
            "essential_monthly_expenses": 1200,
            "monthly_savings_target": 300,
        },
        today=date(2026, 7, 1),
    )

    assert result.history_months == 3
    assert result.monthly_income == 2500
    assert result.available_liquidity == 10000
    assert result.reducible_categories[0].name == "Svago"
    assert result.reducible_categories[0].historical_monthly_spend == 200


def test_prefill_uses_observed_medians_and_net_savings_suggestion() -> None:
    result = build_sustainability_prefill(StorageStub(), {}, today=date(2026, 7, 1))

    assert result == {
        "monthly_income": 2500.0,
        "essential_monthly_expenses": 200.0,
        "monthly_savings_target": 2300.0,
        "history_months": 3,
        "source": "ultimi mesi chiusi",
        "active_goals": [],
        "goal_strategy": "maintain",
    }


def test_string_iso_dates_are_normalized_for_history_and_category_spend() -> None:
    result = build_sustainability_input(
        StringDateStorageStub(),
        {
            "principal": 100000,
            "tan_annual": 3,
            "duration_months": 240,
            "rate_type": "fisso",
            "selected_category_ids": [7],
        },
        today=date(2026, 7, 1),
    )

    assert result.history_months == 3
    assert result.monthly_income == 2500
    assert result.reducible_categories[0].historical_monthly_spend == 200


def test_prefill_values_are_overridden_by_user_payload() -> None:
    result = build_sustainability_prefill(
        StorageStub(),
        {
            "monthly_income": 3000,
            "essential_monthly_expenses": 1400,
            "monthly_savings_target": 500,
        },
        today=date(2026, 7, 1),
    )

    assert result["monthly_income"] == 3000.0
    assert result["essential_monthly_expenses"] == 1400.0
    assert result["monthly_savings_target"] == 500.0


def test_prefill_never_suggests_negative_savings() -> None:
    class DeficitStorage(StorageStub):
        def fetch_all_transactions(self, start_date, end_date):
            return [{"date": date(2026, 6, 10), "amount": 3000}]

        def fetch_income(self, start_date, end_date):
            return [{"date": date(2026, 6, 1), "amount": 2500, "income_type": "Stipendio"}]

    result = build_sustainability_prefill(DeficitStorage(), {}, today=date(2026, 7, 1))

    assert result["monthly_savings_target"] == 0.0


def test_prefill_excludes_non_salary_income() -> None:
    class MixedIncomeStorage(StorageStub):
        def fetch_income(self, start_date, end_date):
            return [
                {"date": date(2026, 4, 1), "amount": 2500, "income_type": "Stipendio"},
                {"date": date(2026, 4, 15), "amount": 500, "income_type": "Bonus"},
                {"date": date(2026, 5, 1), "amount": 2500, "income_type": "Stipendio"},
                {"date": date(2026, 6, 1), "amount": 2500, "income_type": "Stipendio"},
            ]

    result = build_sustainability_prefill(MixedIncomeStorage(), {}, today=date(2026, 7, 1))
    assert result["monthly_income"] == 2500.0
    assert result["monthly_savings_target"] == 2300.0
