"""Adattatore tra FinancialStorage e il motore puro di sostenibilità mutuo."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from statistics import median

from src.mortgage_sustainability import BudgetCategory, MortgageSustainabilityInput
from src.savings_goals_service import compute_goal_progress


def _normalize_date(value: object) -> date | None:
    """Normalizza date e stringhe ISO provenienti dai backend di storage."""
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _closed_months(today: date, count: int = 6) -> list[tuple[int, int]]:
    """Restituisce gli ultimi mesi solari chiusi, dal più vecchio."""
    year, month = today.year, today.month
    result = []
    for _ in range(count):
        month -= 1
        if month == 0:
            year, month = year - 1, 12
        result.append((year, month))
    return list(reversed(result))


def _month_values(records: list[dict], months: list[tuple[int, int]]) -> list[Decimal]:
    """Aggrega record per mese, lasciando zero nei mesi senza dati."""
    buckets = {item: Decimal("0") for item in months}
    for record in records:
        record_date = _normalize_date(record.get("date"))
        if record_date and (record_date.year, record_date.month) in buckets:
            buckets[(record_date.year, record_date.month)] += Decimal(str(record.get("amount") or 0))
    return list(buckets.values())


def _decimal(payload: dict, key: str, default: Decimal = Decimal("0")) -> Decimal:
    """Converte un campo JSON opzionale in Decimal."""
    raw = payload.get(key)
    return Decimal(str(raw)) if raw not in (None, "") else default


def _observed_profile(
    storage, today: date
) -> tuple[
    list[tuple[int, int]],
    list[dict],
    list[dict],
    list[tuple[int, int]],
    list[Decimal],
    list[Decimal],
]:
    """Legge e aggrega il profilo osservato degli ultimi sei mesi chiusi."""
    months = _closed_months(today)
    start_date = date(months[0][0], months[0][1], 1)
    end_date = date(today.year, today.month, 1)
    expenses = storage.fetch_all_transactions(start_date, end_date)
    incomes = storage.fetch_income(start_date, end_date)
    salary_incomes = [
        record for record in incomes
        if str(record.get("income_category") or record.get("income_type") or "").strip().lower()
        == "stipendio"
    ]
    observed_months = {
        (normalized_date.year, normalized_date.month)
        for record in [*expenses, *salary_incomes]
        if (normalized_date := _normalize_date(record.get("date")))
    }
    covered_months = [month for month in months if month in observed_months]
    baseline_months = covered_months or months
    return (
        months,
        expenses,
        incomes,
        covered_months,
        _month_values(
            salary_incomes,
            baseline_months,
        ),
        _month_values(expenses, baseline_months),
    )


def _active_goal_commitments(
    storage, today: date, strategy: str | dict, monthly_income: Decimal | None = None,
    extensions: dict | None = None,
) -> tuple[Decimal, list[dict]]:
    """Stima l'impegno mensile degli obiettivi attivi, secondo la scelta utente."""
    if strategy == "abandon":
        return Decimal("0"), []
    try:
        goals = storage.fetch_savings_goals(status="active")
    except (AttributeError, RuntimeError):
        return Decimal("0"), []
    commitments: list[dict] = []
    total = Decimal("0")
    for goal in goals:
        try:
            goal_strategy = strategy.get(str(goal.get("id")), strategy.get(goal.get("id"), "maintain")) if isinstance(strategy, dict) else strategy
            if goal_strategy == "abandon":
                continue
            if goal.get("goal_type") == "category_spending_reduction":
                continue
            progress = compute_goal_progress(storage, goal, today)
            if goal.get("goal_type") == "savings_rate":
                monthly = ((monthly_income or Decimal("0")) * Decimal(str(goal.get("target_amount") or 0)) / Decimal("100")).quantize(Decimal("0.01"))
                if goal_strategy == "extend":
                    monthly = (monthly / 2).quantize(Decimal("0.01"))
                remaining = monthly
            else:
                remaining = max(Decimal(str(goal.get("target_amount") or 0)) - Decimal(str(progress.get("current") or 0)), Decimal("0"))
                target_date = _normalize_date(goal.get("target_date"))
                months = max(1, ((target_date.year - today.year) * 12 + target_date.month - today.month + 1)) if target_date else 12
                if goal_strategy == "extend":
                    extension = int((extensions or {}).get(str(goal.get("id")), 12) or 12)
                    months += max(1, extension)
                monthly = (remaining / months).quantize(Decimal("0.01"))
            if monthly > 0:
                total += monthly
                commitments.append({"id": goal.get("id"), "name": goal.get("name") or "Obiettivo", "monthly_commitment": float(monthly), "strategy": goal_strategy, "extension_months": 12 if goal_strategy == "extend" else 0})
        except (KeyError, TypeError, ValueError, ArithmeticError):
            continue
    return total, commitments


def build_sustainability_prefill(storage, payload: dict, today: date | None = None) -> dict:
    """Restituisce suggerimenti precompilabili derivati dal profilo finanziario osservato."""
    today = today or date.today()
    _, _, _, covered_months, income_values, expense_values = _observed_profile(storage, today)
    observed_income = Decimal(str(median(income_values)))
    observed_expenses = Decimal(str(median(expense_values)))
    goal_strategy = payload.get("goal_strategies") or str(payload.get("goal_strategy") or "maintain")
    _, active_goals = _active_goal_commitments(storage, today, goal_strategy, observed_income, payload.get("goal_extensions"))
    values = {
        "monthly_income": _decimal(payload, "monthly_income", observed_income),
        "essential_monthly_expenses": _decimal(
            payload, "essential_monthly_expenses", observed_expenses
        ),
        "monthly_savings_target": _decimal(
            payload,
            "monthly_savings_target",
            max(observed_income - observed_expenses, Decimal("0")),
        ),
    }
    return {
        **{key: float(value) for key, value in values.items()},
        "history_months": len(covered_months),
        "source": "ultimi mesi chiusi",
        "active_goals": active_goals,
        "goal_strategy": goal_strategy,
    }


def build_sustainability_input(storage, payload: dict, today: date | None = None) -> MortgageSustainabilityInput:
    """Costruisce l'input del motore usando sei mesi di dati finanziari disponibili.

    I valori dichiarati dall'utente prevalgono sui valori osservati, in modo che
    reddito o costi futuri possano essere corretti prima della simulazione.
    """
    today = today or date.today()
    months, expenses, incomes, covered_months, income_values, expense_values = _observed_profile(
        storage, today
    )
    history_months = len(covered_months)
    baseline_months = covered_months or months
    monthly_income = _decimal(
        payload, "monthly_income", Decimal(str(median(income_values)))
    )
    observed_expenses = Decimal(str(median(expense_values)))
    essential = _decimal(payload, "essential_monthly_expenses", observed_expenses)
    goal_strategy = payload.get("goal_strategies") or str(payload.get("goal_strategy") or "maintain")
    goal_commitment, _ = _active_goal_commitments(storage, today, goal_strategy, monthly_income, payload.get("goal_extensions"))

    selected_ids = {int(item) for item in payload.get("selected_category_ids", [])}
    categories = {item["name"]: item for item in storage.get_categories()}
    reducible: list[BudgetCategory] = []
    for category in categories.values():
        if category.get("id") not in selected_ids:
            continue
        category_records = [record for record in expenses if record.get("category") == category["name"]]
        spend = Decimal(str(median(_month_values(category_records, baseline_months))))
        reducible.append(BudgetCategory(
            id=int(category["id"]),
            name=category["name"],
            historical_monthly_spend=spend,
            current_budget=(Decimal(str(category["monthly_budget"])) if category.get("monthly_budget") is not None else None),
        ))

    accounts = storage.fetch_accounts()
    observed_liquidity = sum((Decimal(str(item.get("current_balance") or 0)) for item in accounts), Decimal("0"))
    return MortgageSustainabilityInput(
        principal=_decimal(payload, "principal"),
        tan_annual=_decimal(payload, "tan_annual"),
        duration_months=int(payload.get("duration_months") or 0),
        monthly_fee=_decimal(payload, "monthly_fee"),
        upfront_fee=_decimal(payload, "upfront_fee"),
        rate_type=payload.get("rate_type") or "fisso",
        monthly_income=monthly_income,
        essential_monthly_expenses=essential,
        other_monthly_debt=_decimal(payload, "other_monthly_debt"),
        housing_monthly_costs=Decimal("0"),
        monthly_savings_target=(
            max(monthly_income - observed_expenses, Decimal("0"))
            if bool(payload.get("preserve_savings")) else Decimal("0")
        ),
        available_liquidity=_decimal(payload, "available_liquidity", observed_liquidity),
        initial_costs=_decimal(payload, "initial_costs"),
        history_months=history_months,
        preserve_savings=bool(payload.get("preserve_savings")),
        reducible_categories=tuple(reducible),
        goal_commitment=goal_commitment,
        goal_strategy=goal_strategy,
        expense_reduction_target=_decimal(payload, "expense_reduction_target"),
        payment_cadence=payload.get("payment_cadence") or "monthly",
    )
