"""Unit tests for the deterministic mortgage sustainability engine."""

from decimal import Decimal

import pytest

from src.mortgage_sustainability import (
    BudgetCategory,
    MortgageSustainabilityInput,
    evaluate_mortgage_sustainability,
)


pytestmark = pytest.mark.unit


def _input(**overrides) -> MortgageSustainabilityInput:
    payload = {
        "principal": Decimal("200000"),
        "tan_annual": Decimal("3"),
        "duration_months": 300,
        "monthly_fee": Decimal("3"),
        "upfront_fee": Decimal("1000"),
        "rate_type": "fisso",
        "monthly_income": Decimal("4000"),
        "essential_monthly_expenses": Decimal("1700"),
        "other_monthly_debt": Decimal("250"),
        "housing_monthly_costs": Decimal("250"),
        "monthly_savings_target": Decimal("500"),
        "available_liquidity": Decimal("40000"),
        "initial_costs": Decimal("15000"),
        "history_months": 6,
        "preserve_savings": True,
        "reducible_categories": (),
    }
    payload.update(overrides)
    return MortgageSustainabilityInput(**payload)


def test_returns_high_confidence_and_total_monthly_payment() -> None:
    result = evaluate_mortgage_sustainability(_input())

    assert result.confidence == "high"
    assert result.installment == Decimal("948.42")
    assert result.total_monthly_payment == Decimal("951.42")
    assert result.status == "sostenibile"


def test_marks_three_month_history_as_limited() -> None:
    result = evaluate_mortgage_sustainability(_input(history_months=3))

    assert result.confidence == "limited"
    assert result.status == "da_valutare"
    assert "6 mesi" in result.explanations[0]


def test_variable_rate_contains_three_explicit_stress_scenarios() -> None:
    result = evaluate_mortgage_sustainability(_input(rate_type="variabile"))

    assert [scenario.rate_increase for scenario in result.stress_scenarios] == [
        Decimal("1"), Decimal("2"), Decimal("3"),
    ]
    assert result.stress_scenarios[-1].installment > result.installment


def test_fixed_rate_includes_comparison_scenarios() -> None:
    """Un preventivo fisso resta confrontabile a tassi ipotetici più alti."""
    result = evaluate_mortgage_sustainability(_input(rate_type="fisso"))

    assert [scenario.rate_increase for scenario in result.stress_scenarios] == [
        Decimal("1"), Decimal("2"), Decimal("3"),
    ]
    assert result.stress_scenarios[-1].installment > result.installment


def test_manual_category_reductions_are_not_auto_distributed() -> None:
    categories = (
        BudgetCategory(id=1, name="Ristoranti", historical_monthly_spend=Decimal("300")),
        BudgetCategory(id=2, name="Shopping", historical_monthly_spend=Decimal("100")),
    )
    result = evaluate_mortgage_sustainability(
        _input(monthly_income=Decimal("3400"), reducible_categories=categories)
    )

    assert result.budget_reallocation.required_reduction == Decimal("0")
    assert len(result.budget_reallocation.items) == 2
    assert all(item.reduction == Decimal("0") for item in result.budget_reallocation.items)


def test_marks_risk_when_residual_savings_are_negative() -> None:
    categories = (
        BudgetCategory(id=1, name="Svago", historical_monthly_spend=Decimal("10")),
    )
    result = evaluate_mortgage_sustainability(
        _input(monthly_income=Decimal("2500"), reducible_categories=categories)
    )

    assert result.status == "a_rischio"
    assert result.budget_reallocation.uncovered_reduction == Decimal("0")


def test_manual_category_reduction_increases_residual_savings() -> None:
    category = BudgetCategory(id=1, name="Svago", historical_monthly_spend=Decimal("200"))
    baseline = evaluate_mortgage_sustainability(_input(reducible_categories=(category,)))
    reduced = evaluate_mortgage_sustainability(
        _input(reducible_categories=(category,), expense_reduction_target=Decimal("100"))
    )
    assert reduced.monthly_savings_after_mortgage == baseline.monthly_savings_after_mortgage + 100
