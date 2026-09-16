"""Source-level income forecasting shared by monthly views."""

from __future__ import annotations

import re
import unicodedata
from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import median
from typing import Mapping, Sequence


@dataclass(frozen=True)
class IncomeSourceForecast:
    """Forecast details for one normalized income source."""

    source_key: str
    full_month_amount: float
    recorded_month_amount: float
    remaining_amount: float
    scheduled_dates: tuple[date, ...]
    periodicity_confidence: float


@dataclass(frozen=True)
class IncomeForecastResult:
    """Source forecasts and their aggregate amounts for one calendar month."""

    sources: tuple[IncomeSourceForecast, ...]

    @property
    def full_month_total(self) -> float:
        """Return the sum of full-month forecasts across sources."""
        return sum(source.full_month_amount for source in self.sources)

    @property
    def remaining_total(self) -> float:
        """Return the sum of source-level residual income forecasts."""
        return sum(source.remaining_amount for source in self.sources)

    def by_source(self, source_key: str) -> IncomeSourceForecast:
        """Return one source forecast, raising ``KeyError`` when it is absent."""
        for source in self.sources:
            if source.source_key == source_key:
                return source
        raise KeyError(source_key)


@dataclass(frozen=True)
class _IncomeRecord:
    """Validated data required by the pure forecast engine."""

    income_date: date
    amount: float


class IncomeForecastEngine:
    """Combine periodic income evidence with each source's six-month history."""

    MONTHS_LOOKBACK = 6
    _CALENDAR_PERIODS = {
        "monthly": 1,
        "bimonthly": 2,
        "quarterly": 3,
        "semiannual": 6,
    }

    def forecast(
        self,
        incomes: Sequence[Mapping[str, object]],
        *,
        month_start: date,
        month_end: date,
        as_of: date,
    ) -> IncomeForecastResult:
        """Forecast a calendar month while retaining residuals per income source.

        ``month_start`` and ``month_end`` must delimit one calendar month. Historical
        averages use the six months completed before the month containing ``as_of``;
        periodic amounts are inferred from the source's last three observations.
        """
        if month_start > month_end:
            raise ValueError("month_start must not be after month_end")

        records_by_source: dict[str, list[_IncomeRecord]] = defaultdict(list)
        for income in incomes:
            record = self._parse_record(income)
            if record is not None and record.income_date <= as_of:
                records_by_source[self._source_key(income)].append(record)

        forecasts = [
            self._forecast_source(
                source_key,
                sorted(records, key=lambda item: item.income_date),
                month_start=month_start,
                month_end=month_end,
                as_of=as_of,
            )
            for source_key, records in records_by_source.items()
        ]
        return IncomeForecastResult(tuple(sorted(forecasts, key=lambda item: item.source_key)))

    @staticmethod
    def _parse_record(income: Mapping[str, object]) -> _IncomeRecord | None:
        raw_date = income.get("date")
        if isinstance(raw_date, datetime):
            income_date = raw_date.date()
        elif isinstance(raw_date, date):
            income_date = raw_date
        elif isinstance(raw_date, str):
            try:
                income_date = date.fromisoformat(raw_date)
            except ValueError:
                return None
        else:
            return None

        try:
            amount = abs(float(income.get("amount", 0.0)))
        except (TypeError, ValueError):
            return None
        return _IncomeRecord(income_date=income_date, amount=amount)

    @staticmethod
    def _source_key(income: Mapping[str, object]) -> str:
        name = _normalized_text(income.get("name"), fallback="entrata")
        category_value = income.get("income_category")
        if isinstance(category_value, Mapping):
            category_value = category_value.get("name")
        if not category_value:
            category_value = income.get("income_type")
        category = _normalized_text(category_value, fallback="altre entrate")
        return f"{name}|{category}"

    def _forecast_source(
        self,
        source_key: str,
        records: Sequence[_IncomeRecord],
        *,
        month_start: date,
        month_end: date,
        as_of: date,
    ) -> IncomeSourceForecast:
        historical_mean = self._historical_mean(records, as_of)
        cadence = self._infer_cadence(records)
        recorded_amount = sum(
            record.amount
            for record in records
            if month_start <= record.income_date <= month_end and record.income_date <= as_of
        )

        if cadence is None:
            return IncomeSourceForecast(
                source_key=source_key,
                full_month_amount=historical_mean,
                recorded_month_amount=recorded_amount,
                remaining_amount=max(0.0, historical_mean - recorded_amount),
                scheduled_dates=(),
                periodicity_confidence=0.0,
            )

        recent_records = records[-3:]
        scheduled_amount = float(median(record.amount for record in recent_records))
        confidence = self._confidence(records, recent_records)
        occurrences = self._occurrences_in_month(
            anchor=records[-1].income_date,
            cadence=cadence,
            month_start=month_start,
            month_end=month_end,
        )
        effective_scheduled_amount = 0.0
        pending_dates: list[date] = []
        for occurrence in occurrences:
            if occurrence >= as_of:
                effective_scheduled_amount += scheduled_amount
                pending_dates.append(occurrence)
            elif self._has_matching_record(records, occurrence, cadence):
                effective_scheduled_amount += scheduled_amount

        full_month_amount = (
            confidence * effective_scheduled_amount
            + (1.0 - confidence) * historical_mean
        )
        return IncomeSourceForecast(
            source_key=source_key,
            full_month_amount=full_month_amount,
            recorded_month_amount=recorded_amount,
            remaining_amount=max(0.0, full_month_amount - recorded_amount),
            scheduled_dates=tuple(pending_dates),
            periodicity_confidence=confidence,
        )

    def _historical_mean(self, records: Sequence[_IncomeRecord], month_start: date) -> float:
        months = _previous_months(month_start, self.MONTHS_LOOKBACK)
        monthly_totals = {month: 0.0 for month in months}
        for record in records:
            month_key = (record.income_date.year, record.income_date.month)
            if month_key in monthly_totals:
                monthly_totals[month_key] += record.amount
        return sum(monthly_totals.values()) / self.MONTHS_LOOKBACK

    def _infer_cadence(self, records: Sequence[_IncomeRecord]) -> str | None:
        if len(records) < 3:
            return None
        recent = records[-3:]
        amounts = [record.amount for record in recent]
        amount_median = float(median(amounts))
        if amount_median == 0 or any(
            abs(amount - amount_median) / amount_median > 0.10 for amount in amounts
        ):
            return None

        first_gap = recent[1].income_date - recent[0].income_date
        second_gap = recent[2].income_date - recent[1].income_date
        if _matches_day_gaps(first_gap.days, second_gap.days, expected_days=7):
            return "weekly"
        if _matches_day_gaps(first_gap.days, second_gap.days, expected_days=14):
            return "biweekly"

        for cadence, months in self._CALENDAR_PERIODS.items():
            if (
                _month_delta(recent[0].income_date, recent[1].income_date) == months
                and _month_delta(recent[1].income_date, recent[2].income_date) == months
                and _same_calendar_day(recent[0].income_date, recent[1].income_date)
                and _same_calendar_day(recent[1].income_date, recent[2].income_date)
            ):
                return cadence
        return None

    @staticmethod
    def _confidence(
        records: Sequence[_IncomeRecord], recent_records: Sequence[_IncomeRecord]
    ) -> float:
        amount_median = float(median(record.amount for record in recent_records))
        maximum_deviation = max(
            abs(record.amount - amount_median) / amount_median for record in recent_records
        )
        confidence = 0.5 + min(max(len(records) - 3, 0), 3) * 0.1
        confidence += 0.2 if maximum_deviation <= 0.05 else 0.1
        return min(confidence, 0.9)

    def _occurrences_in_month(
        self,
        *,
        anchor: date,
        cadence: str,
        month_start: date,
        month_end: date,
    ) -> tuple[date, ...]:
        occurrences: set[date] = set()
        for offset in range(-72, 73):
            occurrence = _advance(anchor, cadence, offset)
            if month_start <= occurrence <= month_end:
                occurrences.add(occurrence)
        return tuple(sorted(occurrences))

    @staticmethod
    def _has_matching_record(
        records: Sequence[_IncomeRecord], occurrence: date, cadence: str
    ) -> bool:
        tolerance_days = 1 if cadence in {"weekly", "biweekly"} else 3
        return any(
            abs((record.income_date - occurrence).days) <= tolerance_days
            for record in records
        )


def _normalized_text(value: object, *, fallback: str) -> str:
    """Create a stable key component without relying on storage-specific identifiers."""
    if not isinstance(value, str) or not value.strip():
        return fallback
    normalized = unicodedata.normalize("NFKD", value)
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_marks.strip().casefold())


def _previous_months(month_start: date, count: int) -> tuple[tuple[int, int], ...]:
    """Return the ``count`` calendar months immediately before ``month_start``."""
    months: list[tuple[int, int]] = []
    year, month = month_start.year, month_start.month
    for _ in range(count):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
        months.append((year, month))
    return tuple(months)


def _month_delta(first: date, second: date) -> int:
    """Return the signed number of calendar months between two dates."""
    return (second.year - first.year) * 12 + second.month - first.month


def _same_calendar_day(first: date, second: date) -> bool:
    """Accept same-day and end-of-month-clamped calendar recurrences."""
    if abs(first.day - second.day) <= 3:
        return True
    return first.day == monthrange(first.year, first.month)[1] and second.day == monthrange(
        second.year, second.month
    )[1]


def _matches_day_gaps(first: int, second: int, *, expected_days: int) -> bool:
    """Match a fixed-day cadence while tolerating one day of input variance."""
    return abs(first - expected_days) <= 1 and abs(second - expected_days) <= 1


def _advance(anchor: date, cadence: str, offset: int) -> date:
    """Advance or rewind a cadence while preserving a calendar anchor day."""
    if cadence == "weekly":
        return anchor + timedelta(days=7 * offset)
    if cadence == "biweekly":
        return anchor + timedelta(days=14 * offset)
    months = IncomeForecastEngine._CALENDAR_PERIODS[cadence] * offset
    raw_month = anchor.month + months
    year = anchor.year + (raw_month - 1) // 12
    month = (raw_month - 1) % 12 + 1
    return date(year, month, min(anchor.day, monthrange(year, month)[1]))
