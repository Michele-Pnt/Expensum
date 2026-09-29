"""Contracts for the unified, source-level income forecast."""

from datetime import date

import pytest

from src.income_forecast import IncomeForecastEngine


pytestmark = pytest.mark.unit


def _income(
    income_date: date,
    amount: float,
    name: str,
    category: str,
) -> dict[str, object]:
    """Build an income record in the storage DTO shape."""
    return {
        "date": income_date,
        "amount": amount,
        "name": name,
        "income_category": {"name": category},
    }


def _monthly_history(
    name: str,
    category: str,
    amount: float,
    day: int = 27,
) -> list[dict[str, object]]:
    """Return six complete months of equal source income before September 2026."""
    return [
        _income(date(2026, month, day), amount, name, category)
        for month in range(3, 9)
    ]


def test_monthly_salary_blends_history_with_the_27th_occurrence() -> None:
    """A regular salary has a scheduled September payment and high confidence."""
    result = IncomeForecastEngine().forecast(
        _monthly_history("Stipendio", "Lavoro", 2_000.0),
        month_start=date(2026, 9, 1),
        month_end=date(2026, 9, 30),
        as_of=date(2026, 9, 10),
    )

    salary = result.by_source("stipendio|lavoro")
    assert salary.scheduled_dates == (date(2026, 9, 27),)
    assert salary.periodicity_confidence == pytest.approx(0.9)
    assert salary.full_month_amount == pytest.approx(2_000.0)
    assert salary.remaining_amount == pytest.approx(2_000.0)


def test_weekly_source_exposes_two_future_occurrences() -> None:
    """Only scheduled dates after today are pending for a weekly source."""
    records = [
        _income(date(2026, 7, 23), 100.0, "Lezioni", "Consulenze"),
        _income(date(2026, 7, 30), 100.0, "Lezioni", "Consulenze"),
        _income(date(2026, 8, 6), 100.0, "Lezioni", "Consulenze"),
        _income(date(2026, 8, 13), 100.0, "Lezioni", "Consulenze"),
        _income(date(2026, 8, 20), 100.0, "Lezioni", "Consulenze"),
        _income(date(2026, 8, 27), 100.0, "Lezioni", "Consulenze"),
        _income(date(2026, 9, 3), 100.0, "Lezioni", "Consulenze"),
        _income(date(2026, 9, 10), 100.0, "Lezioni", "Consulenze"),
    ]
    result = IncomeForecastEngine().forecast(
        records,
        month_start=date(2026, 9, 1),
        month_end=date(2026, 9, 30),
        as_of=date(2026, 9, 13),
    )

    lessons = result.by_source("lezioni|consulenze")
    assert lessons.scheduled_dates == (date(2026, 9, 17), date(2026, 9, 24))
    assert lessons.remaining_amount == pytest.approx(200.0)
    assert result.recurring_remaining_total == pytest.approx(200.0)
    assert result.irregular_adjustment == 0.0


def test_irregular_source_uses_only_its_six_month_historical_mean() -> None:
    """Non-periodic income retains the old six-complete-month behaviour."""
    records = [
        _income(date(2026, 3, 4), 60.0, "Rimborsi", "Altro"),
        _income(date(2026, 5, 8), 120.0, "Rimborsi", "Altro"),
        _income(date(2026, 8, 21), 60.0, "Rimborsi", "Altro"),
    ]
    result = IncomeForecastEngine().forecast(
        records,
        month_start=date(2026, 9, 1),
        month_end=date(2026, 9, 30),
        as_of=date(2026, 9, 10),
    )

    refunds = result.by_source("rimborsi|altro")
    assert refunds.periodicity_confidence == 0.0
    assert refunds.scheduled_dates == ()
    assert refunds.full_month_amount == pytest.approx(40.0)
    assert refunds.remaining_amount == 0.0


def test_late_payment_is_not_asserted_as_a_future_income() -> None:
    """An unrecorded date before today loses its periodic contribution."""
    result = IncomeForecastEngine().forecast(
        _monthly_history("Stipendio", "Lavoro", 2_000.0),
        month_start=date(2026, 9, 1),
        month_end=date(2026, 9, 30),
        as_of=date(2026, 9, 28),
    )

    salary = result.by_source("stipendio|lavoro")
    assert salary.scheduled_dates == ()
    assert salary.full_month_amount == pytest.approx(200.0)


def test_monthly_day_31_is_clamped_to_the_target_month_end() -> None:
    """A 31st-of-month recurrence is safely forecast for a 30-day month."""
    records = [
        _income(date(2026, month, 31), 500.0, "Affitto", "Locazioni")
        for month in (3, 5, 7)
    ]
    result = IncomeForecastEngine().forecast(
        records,
        month_start=date(2026, 9, 1),
        month_end=date(2026, 9, 30),
        as_of=date(2026, 9, 10),
    )

    rent = result.by_source("affitto|locazioni")
    assert rent.scheduled_dates == (date(2026, 9, 30),)


def test_received_income_reduces_only_its_own_remaining_source() -> None:
    """A salary bonus cannot consume an unrelated rental income forecast."""
    records = [
        *_monthly_history("Stipendio", "Lavoro", 2_000.0),
        _income(date(2026, 9, 27), 2_000.0, "Stipendio", "Lavoro"),
        *_monthly_history("Affitto", "Locazioni", 800.0, day=30),
    ]
    result = IncomeForecastEngine().forecast(
        records,
        month_start=date(2026, 9, 1),
        month_end=date(2026, 9, 30),
        as_of=date(2026, 9, 28),
    )

    assert result.by_source("stipendio|lavoro").remaining_amount == 0
    assert result.by_source("affitto|locazioni").remaining_amount > 0


def test_next_month_history_excludes_the_current_incomplete_month() -> None:
    """A next-month forecast must not learn from income recorded during this month."""
    records = [
        _income(date(2026, 3, 4), 60.0, "Rimborsi", "Altro"),
        _income(date(2026, 5, 8), 120.0, "Rimborsi", "Altro"),
        _income(date(2026, 8, 21), 60.0, "Rimborsi", "Altro"),
        _income(date(2026, 9, 2), 600.0, "Rimborsi", "Altro"),
    ]
    result = IncomeForecastEngine().forecast(
        records,
        month_start=date(2026, 10, 1),
        month_end=date(2026, 10, 31),
        as_of=date(2026, 9, 15),
    )

    assert result.by_source("rimborsi|altro").full_month_amount == pytest.approx(40.0)


def test_occurrence_due_on_as_of_is_retained_for_the_forecast() -> None:
    """The forecast must not discard an income occurrence scheduled for today."""
    result = IncomeForecastEngine().forecast(
        _monthly_history("Stipendio", "Lavoro", 2_000.0),
        month_start=date(2026, 9, 1),
        month_end=date(2026, 9, 30),
        as_of=date(2026, 9, 27),
    )

    salary = result.by_source("stipendio|lavoro")
    assert salary.scheduled_dates == (date(2026, 9, 27),)
    assert salary.full_month_amount == pytest.approx(2_000.0)


def test_occurrence_recorded_on_as_of_is_not_still_expected() -> None:
    """A received recurring payment consumes the matching scheduled occurrence."""
    records = [
        *_monthly_history("Stipendio", "Lavoro", 2_000.0),
        _income(date(2026, 9, 27), 2_000.0, "Stipendio", "Lavoro"),
    ]

    result = IncomeForecastEngine().forecast(
        records,
        month_start=date(2026, 9, 1),
        month_end=date(2026, 9, 30),
        as_of=date(2026, 9, 27),
    )

    salary = result.by_source("stipendio|lavoro")
    assert salary.scheduled_dates == ()
    assert salary.remaining_amount == 0.0
    assert result.recurring_remaining_total == 0.0


def test_occurrence_with_incompatible_amount_is_still_expected() -> None:
    """A same-source receipt only consumes a recurrence when its amount is compatible."""
    records = [
        *_monthly_history("Stipendio", "Lavoro", 2_000.0),
        _income(date(2026, 9, 27), 300.0, "Stipendio settembre", "Lavoro"),
    ]

    result = IncomeForecastEngine().forecast(
        records,
        month_start=date(2026, 9, 1),
        month_end=date(2026, 9, 30),
        as_of=date(2026, 9, 27),
    )

    salary = result.by_source("stipendio|lavoro")
    assert salary.scheduled_dates == (date(2026, 9, 27),)
    assert salary.remaining_amount == pytest.approx(2_000.0)


def test_calendar_tokens_do_not_split_one_monthly_income_source() -> None:
    """Month and year suffixes in a description cannot hide a stable recurrence."""
    records = [
        _income(date(2026, 6, 27), 2_000.0, "Stipendio giugno 2026", "Lavoro"),
        _income(date(2026, 7, 27), 2_000.0, "Stipendio luglio 2026", "Lavoro"),
        _income(date(2026, 8, 27), 2_000.0, "Stipendio agosto 2026", "Lavoro"),
    ]

    result = IncomeForecastEngine().forecast(
        records,
        month_start=date(2026, 9, 1),
        month_end=date(2026, 9, 30),
        as_of=date(2026, 9, 10),
    )

    assert result.by_source("stipendio|lavoro").scheduled_dates == (date(2026, 9, 27),)
    assert result.recurring_remaining_total == pytest.approx(2_000.0)


def test_irregular_adjustment_uses_six_month_median_and_remaining_days() -> None:
    """Frequent irregular income contributes its robust daily share to the widget."""
    monthly_amounts = [900.0, 1_200.0, 0.0, 1_500.0, 800.0, 1_100.0]
    records = [
        _income(date(2026, month, 5), amount, "Collaborazioni", "Consulenze")
        for month, amount in zip(range(3, 9), monthly_amounts)
        if amount > 0
    ]

    result = IncomeForecastEngine().forecast(
        records,
        month_start=date(2026, 9, 1),
        month_end=date(2026, 9, 30),
        as_of=date(2026, 9, 10),
    )

    assert result.recurring_remaining_total == 0.0
    assert result.irregular_adjustment == pytest.approx(1_000.0 / 30 * 20)
    assert result.remaining_total == pytest.approx(666.666, rel=1e-3)


def test_isolated_irregular_peak_does_not_inflate_remaining_income() -> None:
    """One exceptional receipt is suppressed by zero months in the median."""
    result = IncomeForecastEngine().forecast(
        [_income(date(2026, 8, 5), 6_000.0, "Vendita occasionale", "Altro")],
        month_start=date(2026, 9, 1),
        month_end=date(2026, 9, 30),
        as_of=date(2026, 9, 10),
    )

    assert result.irregular_adjustment == 0.0
    assert result.remaining_total == 0.0
    # The next-month planning signal stays backward compatible.
    assert result.full_month_total == pytest.approx(1_000.0)


def test_future_dated_records_do_not_influence_the_forecast() -> None:
    """Imported future records cannot change the evidence available on ``as_of``."""
    baseline = _monthly_history("Stipendio", "Lavoro", 2_000.0)
    with_future_record = [
        *baseline,
        _income(date(2026, 9, 27), 20_000.0, "Stipendio", "Lavoro"),
    ]
    engine = IncomeForecastEngine()
    baseline_result = engine.forecast(
        baseline,
        month_start=date(2026, 9, 1),
        month_end=date(2026, 9, 30),
        as_of=date(2026, 9, 10),
    )
    future_record_result = engine.forecast(
        with_future_record,
        month_start=date(2026, 9, 1),
        month_end=date(2026, 9, 30),
        as_of=date(2026, 9, 10),
    )

    assert future_record_result == baseline_result


@pytest.mark.parametrize(
    ("records", "month_start", "month_end", "as_of", "expected_dates"),
    [
        (
            [
                _income(date(2026, 7, 31), 100.0, "Lezioni", "Consulenze"),
                _income(date(2026, 8, 14), 100.0, "Lezioni", "Consulenze"),
                _income(date(2026, 8, 28), 100.0, "Lezioni", "Consulenze"),
            ],
            date(2026, 9, 1),
            date(2026, 9, 30),
            date(2026, 9, 1),
            (date(2026, 9, 11), date(2026, 9, 25)),
        ),
        (
            [
                _income(date(2026, 3, 15), 600.0, "Dividendo", "Investimenti"),
                _income(date(2026, 6, 15), 600.0, "Dividendo", "Investimenti"),
                _income(date(2026, 9, 15), 600.0, "Dividendo", "Investimenti"),
            ],
            date(2026, 12, 1),
            date(2026, 12, 31),
            date(2026, 9, 16),
            (date(2026, 12, 15),),
        ),
        (
            [
                _income(date(2025, 3, 15), 900.0, "Premio", "Lavoro"),
                _income(date(2025, 9, 15), 900.0, "Premio", "Lavoro"),
                _income(date(2026, 3, 15), 900.0, "Premio", "Lavoro"),
            ],
            date(2026, 9, 1),
            date(2026, 9, 30),
            date(2026, 4, 1),
            (date(2026, 9, 15),),
        ),
    ],
)
def test_supported_periodicities_schedule_their_next_occurrence(
    records: list[dict[str, object]],
    month_start: date,
    month_end: date,
    as_of: date,
    expected_dates: tuple[date, ...],
) -> None:
    """Biweekly, quarterly, and semiannual evidence is accepted after three records."""
    result = IncomeForecastEngine().forecast(
        records,
        month_start=month_start,
        month_end=month_end,
        as_of=as_of,
    )

    assert result.sources[0].scheduled_dates == expected_dates
