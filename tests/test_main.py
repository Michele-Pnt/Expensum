"""
tests/test_main.py — Test unitari per helper del monthly report in main.py.
"""

from datetime import date

import pytest

from main import _build_monthly_report_payload, _resolve_default_target_month
from src.data_processor import TrendReport, MonthlySummary

pytestmark = pytest.mark.unit


def _summary(year: int, month: int, total: float, by_category: dict[str, float] | None = None) -> MonthlySummary:
    summary = MonthlySummary(year, month)
    summary.total = total
    summary.by_category = by_category or {}
    return summary


class TestResolveDefaultTargetMonth:
    def test_uses_previous_month_for_regular_dates(self):
        assert _resolve_default_target_month(date(2026, 5, 10)) == (2026, 4)

    def test_rolls_back_to_previous_year_in_january(self):
        assert _resolve_default_target_month(date(2026, 1, 10)) == (2025, 12)


class TestBuildMonthlyReportPayload:
    def test_includes_monthly_history_with_expected_shape(self):
        report = TrendReport()
        report.history = [
            _summary(2026, 2, 900.0),
            _summary(2026, 3, 1100.0),
        ]
        report.current_month = _summary(2026, 4, 1250.0, {"Casa": 800.0, "Cibo": 450.0})
        report.total_income = 2100.0
        report.incomes = [
            {"date": date(2026, 2, 15), "amount": 1800.0},
            {"date": date(2026, 3, 15), "amount": 2000.0},
            {"date": date(2026, 4, 15), "amount": 2100.0},
        ]

        payload = _build_monthly_report_payload(
            report=report,
            target_year=2026,
            target_month=4,
            total_accounts_balance=3200.0,
            budget_by_cat={"Casa": 900.0, "Cibo": 500.0},
        )

        assert payload["type"] == "monthly_full"
        assert payload["target_year"] == 2026
        assert payload["target_month"] == 4
        assert payload["by_category"] == {"Casa": 800.0, "Cibo": 450.0}
        assert payload["spent_by_cat"] == {"Casa": 800.0, "Cibo": 450.0}
        assert payload["budget_by_cat"] == {"Casa": 900.0, "Cibo": 500.0}

        history = payload["monthly_history"]
        assert len(history) == 3
        assert history[0] == {
            "month": "February 2026",
            "income": 1800.0,
            "expenses": 900.0,
            "net": 900.0,
        }
        assert history[-1] == {
            "month": "April 2026",
            "income": 2100.0,
            "expenses": 1250.0,
            "net": 850.0,
        }

    def test_accepts_iso_string_income_dates(self):
        report = TrendReport()
        report.history = []
        report.current_month = _summary(2026, 4, 500.0, {"Varie": 500.0})
        report.total_income = 750.0
        report.incomes = [{"date": "2026-04-03", "amount": 750.0}]

        payload = _build_monthly_report_payload(
            report=report,
            target_year=2026,
            target_month=4,
            total_accounts_balance=1000.0,
            budget_by_cat={},
        )

        assert payload["monthly_history"] == [
            {
                "month": "April 2026",
                "income": 750.0,
                "expenses": 500.0,
                "net": 250.0,
            }
        ]
