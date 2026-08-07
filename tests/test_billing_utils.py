"""
tests/test_billing_utils.py — Test per src/billing_utils.py.

Funzioni pure, nessun DB: usate dalla vista calendario per proiettare le
occorrenze future di un abbonamento entro un intervallo di date.
"""

from datetime import date

import pytest

from src.billing_utils import get_occurrences_in_range

pytestmark = pytest.mark.unit


class TestGetOccurrencesInRange:
    def test_monthly_multiple_occurrences(self):
        occurrences = get_occurrences_in_range(
            date(2026, 1, 15), "monthly", date(2026, 1, 1), date(2026, 4, 30)
        )
        assert occurrences == [
            date(2026, 2, 15),
            date(2026, 3, 15),
            date(2026, 4, 15),
        ]

    def test_yearly_single_occurrence_in_range(self):
        occurrences = get_occurrences_in_range(
            date(2025, 8, 7), "yearly", date(2026, 1, 1), date(2026, 12, 31)
        )
        assert occurrences == [date(2026, 8, 7)]

    def test_weekly_within_short_range(self):
        occurrences = get_occurrences_in_range(
            date(2026, 8, 1), "weekly", date(2026, 8, 1), date(2026, 8, 15)
        )
        assert occurrences == [date(2026, 8, 8), date(2026, 8, 15)]

    def test_no_occurrences_when_range_before_next_billing(self):
        occurrences = get_occurrences_in_range(
            date(2026, 8, 1), "monthly", date(2026, 8, 1), date(2026, 8, 20)
        )
        assert occurrences == []

    def test_empty_when_no_last_billed(self):
        assert get_occurrences_in_range(None, "monthly", date(2026, 1, 1), date(2026, 1, 31)) == []

    def test_empty_when_start_after_end(self):
        occurrences = get_occurrences_in_range(
            date(2026, 1, 1), "monthly", date(2026, 5, 1), date(2026, 1, 1)
        )
        assert occurrences == []

    def test_accepts_string_last_billed(self):
        occurrences = get_occurrences_in_range(
            "2026-01-15", "monthly", date(2026, 2, 1), date(2026, 2, 28)
        )
        assert occurrences == [date(2026, 2, 15)]
