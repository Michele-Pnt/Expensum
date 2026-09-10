"""
tests/test_loan_calculator.py — motore di ammortamento puro (src/loan_calculator.py).

Caso di riferimento verificato manualmente in fase di design: 200.000€, TAN 3%,
25 anni (300 mesi) -> rata ~948,42€, interessi totali ~84.526€.
"""
from datetime import date
from decimal import Decimal

import pytest

from src.loan_calculator import (
    calculate_installment,
    build_amortization_schedule,
    split_current_payment,
    calculate_taeg,
    summarize_remaining_loan,
)

pytestmark = pytest.mark.unit


class TestCalculateInstallment:
    def test_known_case_200k_3pct_25y(self):
        installment = calculate_installment(Decimal("200000"), Decimal("3"), 300)
        assert installment == pytest.approx(Decimal("948.42"), abs=Decimal("0.5"))

    def test_zero_rate_is_simple_division(self):
        installment = calculate_installment(Decimal("12000"), Decimal("0"), 12)
        assert installment == Decimal("1000.00")

    def test_rejects_non_positive_duration(self):
        with pytest.raises(ValueError):
            calculate_installment(Decimal("1000"), Decimal("3"), 0)


class TestAmortizationSchedule:
    def test_schedule_length_matches_duration(self):
        schedule = build_amortization_schedule(Decimal("200000"), Decimal("3"), 300)
        assert len(schedule) == 300

    def test_last_period_residual_is_zero(self):
        schedule = build_amortization_schedule(Decimal("200000"), Decimal("3"), 300)
        assert schedule[-1]["residual_balance"] == Decimal("0.00")

    def test_residual_balance_decreases_monotonically(self):
        schedule = build_amortization_schedule(Decimal("50000"), Decimal("4.5"), 60)
        residuals = [item["residual_balance"] for item in schedule]
        assert all(residuals[i] >= residuals[i + 1] for i in range(len(residuals) - 1))

    def test_total_interest_matches_known_case(self):
        schedule = build_amortization_schedule(Decimal("200000"), Decimal("3"), 300)
        total_interest = sum(item["interest"] for item in schedule)
        assert total_interest == pytest.approx(Decimal("84526"), abs=Decimal("50"))

    def test_principal_plus_interest_equals_installment(self):
        schedule = build_amortization_schedule(Decimal("50000"), Decimal("4.5"), 60)
        for item in schedule[:-1]:
            assert item["principal"] + item["interest"] == pytest.approx(
                item["installment"], abs=Decimal("0.01")
            )


class TestSplitCurrentPayment:
    def test_split_matches_schedule_first_period(self):
        schedule = build_amortization_schedule(Decimal("100000"), Decimal("3.5"), 120)
        installment = schedule[0]["installment"]
        principal, interest = split_current_payment(Decimal("100000"), Decimal("3.5"), installment)
        assert principal == schedule[0]["principal"]
        assert interest == schedule[0]["interest"]


class TestCalculateTaeg:
    def test_taeg_slightly_above_tan_without_accessory_costs(self):
        # Senza costi accessori il TAEG coincide con l'equivalente annuo effettivo
        # del TAN nominale mensile composto (sempre leggermente superiore al TAN
        # nominale per via della capitalizzazione, non è un errore di calcolo).
        taeg = calculate_taeg(Decimal("100000"), Decimal("3"), 120)
        assert taeg == pytest.approx(Decimal("3.0417"), abs=Decimal("0.001"))

    def test_taeg_exceeds_tan_with_accessory_costs(self):
        taeg = calculate_taeg(
            Decimal("100000"), Decimal("3"), 120,
            upfront_fee=Decimal("1500"), monthly_fee=Decimal("3"),
        )
        assert taeg > Decimal("3")


class TestRemainingLoanSummary:
    def test_summary_exposes_time_interest_and_next_payment_split(self):
        summary = summarize_remaining_loan(
            residual_balance=Decimal("100000"),
            tan_annual=Decimal("3"),
            remaining_months=239,
            reference_date=date(2026, 1, 1),
        )

        assert summary["remaining_months"] == 239
        assert summary["estimated_end_date"] == date(2045, 12, 1)
        assert summary["remaining_interest"] > Decimal("0")
        assert summary["next_interest"] > Decimal("0")
        assert summary["next_principal"] > Decimal("0")
