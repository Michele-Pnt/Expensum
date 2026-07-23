"""tests/test_budget_alert.py — Alert budget categoria in tempo reale.

Copre:
  1. evaluate_budget_alert — logica pura delle soglie 80/100/120%
  2. check_expense_budget_alert — orchestrazione backend-agnostica via storage

Lo `storage` è un fake che implementa solo l'interfaccia usata (get_categories,
fetch_all_transactions): garantisce che l'alert funzioni identico per Notion e
Postgres, che espongono gli stessi metodi.
"""

from datetime import date

import pytest

from src.budget_alert import evaluate_budget_alert, check_expense_budget_alert

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 1. Logica pura — evaluate_budget_alert
# ---------------------------------------------------------------------------

class TestEvaluateBudgetAlert:
    def test_no_budget_returns_none(self):
        assert evaluate_budget_alert("Alimentari", 50.0, None) is None

    def test_zero_budget_returns_none(self):
        assert evaluate_budget_alert("Alimentari", 50.0, 0.0) is None

    def test_below_first_threshold_returns_none(self):
        # 79% < 80% → nessun alert
        assert evaluate_budget_alert("Alimentari", 79.0, 100.0) is None

    def test_warning_band_80(self):
        msg = evaluate_budget_alert("Alimentari", 85.0, 100.0)
        assert msg is not None
        assert "⚠️" in msg
        assert "85%" in msg
        assert "Alimentari" in msg
        assert "sforare" in msg

    def test_exceeded_band_100(self):
        msg = evaluate_budget_alert("Trasporti", 100.0, 100.0)
        assert msg is not None
        assert "🔴" in msg
        assert "100%" in msg
        assert "esaurito" in msg

    def test_over_band_120(self):
        msg = evaluate_budget_alert("Svago", 130.0, 100.0)
        assert msg is not None
        assert "🔴" in msg
        assert "130%" in msg
        assert "sforato" in msg

    def test_picks_highest_band(self):
        # 125% supera 80 e 100 e 120: deve prendere la frase della banda 120.
        msg = evaluate_budget_alert("Svago", 125.0, 100.0)
        assert "sforato" in msg
        assert "esaurito" not in msg

    def test_amounts_shown_rounded(self):
        msg = evaluate_budget_alert("Casa", 402.6, 500.0)
        # 402.6/500 = 80.5% → banda 80
        assert "€403/€500" in msg


# ---------------------------------------------------------------------------
# Fake storage — stessa interfaccia di Notion/PostgresStorage
# ---------------------------------------------------------------------------

class FakeStorage:
    """Implementa solo i metodi usati da check_expense_budget_alert."""

    def __init__(self, categories, transactions):
        self._categories = categories
        self._transactions = transactions

    def get_categories(self):
        return self._categories

    def fetch_all_transactions(self, start_date, end_date):
        return [
            t for t in self._transactions
            if start_date <= t["date"] <= end_date
        ]


# ---------------------------------------------------------------------------
# 2. Orchestrazione — check_expense_budget_alert
# ---------------------------------------------------------------------------

class TestCheckExpenseBudgetAlert:
    def test_none_category_returns_none(self):
        storage = FakeStorage([], [])
        assert check_expense_budget_alert(storage, None, date(2026, 7, 11)) is None

    def test_category_without_budget_returns_none(self):
        storage = FakeStorage(
            [{"name": "Alimentari", "monthly_budget": None}],
            [{"date": date(2026, 7, 5), "amount": 90.0, "category": "Alimentari"}],
        )
        assert check_expense_budget_alert(storage, "Alimentari", date(2026, 7, 11)) is None

    def test_alert_triggered_over_threshold(self):
        storage = FakeStorage(
            [{"name": "Alimentari", "monthly_budget": 100.0}],
            [
                {"date": date(2026, 7, 3), "amount": 50.0, "category": "Alimentari"},
                {"date": date(2026, 7, 8), "amount": 40.0, "category": "Alimentari"},
            ],
        )
        # 90/100 = 90% → banda 80
        msg = check_expense_budget_alert(storage, "Alimentari", date(2026, 7, 11))
        assert msg is not None
        assert "90%" in msg

    def test_sums_only_target_category(self):
        storage = FakeStorage(
            [
                {"name": "Alimentari", "monthly_budget": 100.0},
                {"name": "Trasporti", "monthly_budget": 100.0},
            ],
            [
                {"date": date(2026, 7, 3), "amount": 85.0, "category": "Alimentari"},
                {"date": date(2026, 7, 4), "amount": 200.0, "category": "Trasporti"},
            ],
        )
        msg = check_expense_budget_alert(storage, "Alimentari", date(2026, 7, 11))
        assert "85%" in msg  # non contaminata da Trasporti

    def test_ignores_other_months(self):
        storage = FakeStorage(
            [{"name": "Alimentari", "monthly_budget": 100.0}],
            [
                {"date": date(2026, 6, 20), "amount": 200.0, "category": "Alimentari"},
                {"date": date(2026, 7, 8), "amount": 30.0, "category": "Alimentari"},
            ],
        )
        # Solo la spesa di luglio conta: 30% < 80% → nessun alert
        assert check_expense_budget_alert(storage, "Alimentari", date(2026, 7, 11)) is None

    def test_absolute_amount_used(self):
        # Importi negativi (segno spesa) sommati in valore assoluto.
        storage = FakeStorage(
            [{"name": "Alimentari", "monthly_budget": 100.0}],
            [{"date": date(2026, 7, 8), "amount": -95.0, "category": "Alimentari"}],
        )
        msg = check_expense_budget_alert(storage, "Alimentari", date(2026, 7, 11))
        assert msg is not None
        assert "95%" in msg
