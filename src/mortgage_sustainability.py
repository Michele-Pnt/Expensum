"""Motore puro e deterministico per valutare la sostenibilità di un mutuo.

Il modulo non conosce database, HTTP o componenti React. Gli adattatori costruiscono
``MortgageSustainabilityInput`` con dati osservati/dichiarati e usano il risultato
serializzabile per preview, bozze e conferme di budget.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP

from src.loan_calculator import calculate_installment, calculate_taeg, cadence_months


MONEY_QUANTUM = Decimal("0.01")
STRESS_RATE_INCREASES = (Decimal("1"), Decimal("2"), Decimal("3"))


def _money(value: Decimal) -> Decimal:
    """Arrotonda un importo monetario a due decimali."""
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class BudgetCategory:
    """Categoria scelta dall'utente per un'eventuale riduzione del budget."""

    id: int
    name: str
    historical_monthly_spend: Decimal
    current_budget: Decimal | None = None


@dataclass(frozen=True)
class MortgageSustainabilityInput:
    """Dati normalizzati necessari al calcolo della sostenibilità."""

    principal: Decimal
    tan_annual: Decimal
    duration_months: int
    monthly_fee: Decimal
    upfront_fee: Decimal
    rate_type: str
    monthly_income: Decimal
    essential_monthly_expenses: Decimal
    other_monthly_debt: Decimal
    housing_monthly_costs: Decimal
    monthly_savings_target: Decimal
    available_liquidity: Decimal
    initial_costs: Decimal
    history_months: int
    preserve_savings: bool
    reducible_categories: tuple[BudgetCategory, ...]
    goal_commitment: Decimal = Decimal("0")
    goal_strategy: str | dict = "maintain"
    expense_reduction_target: Decimal = Decimal("0")
    payment_cadence: str = "monthly"


@dataclass(frozen=True)
class StressScenario:
    """Effetto di un aumento di tasso su rata e margine mensile."""

    rate_increase: Decimal
    installment: Decimal
    total_monthly_payment: Decimal
    monthly_margin_after_savings: Decimal


@dataclass(frozen=True)
class BudgetReallocationItem:
    """Riduzione suggerita per una categoria esplicitamente selezionata."""

    category_id: int
    name: str
    historical_monthly_spend: Decimal
    reduction: Decimal
    proposed_budget: Decimal


@dataclass(frozen=True)
class BudgetReallocation:
    """Piano di redistribuzione, sempre da confermare dall'utente."""

    required_reduction: Decimal
    uncovered_reduction: Decimal
    items: tuple[BudgetReallocationItem, ...]


@dataclass(frozen=True)
class MortgageSustainabilityResult:
    """Esito completo e spiegabile della valutazione."""

    installment: Decimal
    taeg: Decimal
    total_monthly_payment: Decimal
    monthly_margin_before_savings: Decimal
    monthly_savings_after_mortgage: Decimal
    confidence: str
    status: str
    explanations: tuple[str, ...]
    stress_scenarios: tuple[StressScenario, ...]
    budget_reallocation: BudgetReallocation

    def to_dict(self) -> dict:
        """Restituisce un payload JSON-safe per API e persistenza delle bozze."""
        return _decimal_to_json(asdict(self))


def _decimal_to_json(value):
    """Converte ricorsivamente Decimal in float senza dipendere da Flask."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _decimal_to_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_decimal_to_json(item) for item in value]
    return value


def _confidence(history_months: int) -> tuple[str, str | None]:
    """Classifica l'affidabilità dello storico finanziario disponibile."""
    if history_months >= 6:
        return "high", None
    if history_months >= 3:
        return "limited", "Analisi basata su meno di 6 mesi: con 6 mesi è più affidabile."
    return "low", "Storico inferiore a 3 mesi: usa stime prudenti o dati manuali verificati."


def _budget_reallocation(
    required_reduction: Decimal, categories: tuple[BudgetCategory, ...], reductions: dict | None = None
) -> BudgetReallocation:
    """Distribuisce un taglio sulle sole categorie selezionate dall'utente."""
    required_reduction = _money(max(required_reduction, Decimal("0")))
    capacity = sum((max(category.historical_monthly_spend, Decimal("0")) for category in categories), Decimal("0"))
    covered = min(required_reduction, capacity)
    items: list[BudgetReallocationItem] = []
    distributed = Decimal("0")

    for index, category in enumerate(categories):
        spend = max(category.historical_monthly_spend, Decimal("0"))
        if reductions and str(category.id) in reductions:
            reduction = min(max(Decimal(str(reductions[str(category.id)] or 0)), Decimal("0")), spend)
        elif not capacity or not covered:
            reduction = Decimal("0")
        elif index == len(categories) - 1:
            reduction = _money(covered - distributed)
        else:
            reduction = _money(covered * spend / capacity)
            distributed += reduction
        reduction = min(reduction, spend)
        items.append(BudgetReallocationItem(
            category_id=category.id,
            name=category.name,
            historical_monthly_spend=_money(spend),
            reduction=_money(reduction),
            proposed_budget=_money(spend - reduction),
        ))

    actual_covered = sum((item.reduction for item in items), Decimal("0"))
    return BudgetReallocation(
        required_reduction=required_reduction,
        uncovered_reduction=_money(max(required_reduction - actual_covered, Decimal("0"))),
        items=tuple(items),
    )


def evaluate_mortgage_sustainability(
    value: MortgageSustainabilityInput,
) -> MortgageSustainabilityResult:
    """Valuta la sostenibilità di un mutuo senza effettuare scritture.

    Calcola sempre tre scenari di confronto (+1/+2/+3 punti). Per il tasso
    variabile rappresentano possibili revisioni; per il fisso confrontano
    preventivi ipotetici, senza prevedere variazioni del contratto.
    """
    if value.rate_type not in {"fisso", "variabile"}:
        raise ValueError("rate_type deve essere 'fisso' o 'variabile'")

    cadence = cadence_months(value.payment_cadence)
    installment = calculate_installment(
        value.principal, value.tan_annual, value.duration_months, value.payment_cadence
    )
    taeg = calculate_taeg(
        value.principal, value.tan_annual, value.duration_months,
        upfront_fee=value.upfront_fee, monthly_fee=value.monthly_fee,
        payment_cadence=value.payment_cadence,
    )
    # La rata è pagata ogni N mesi, quindi la sostenibilità confronta il suo
    # equivalente mensile. Le spese ricorrenti restano invece mensili.
    total_payment = _money(installment / cadence + value.monthly_fee)
    cash_margin = _money(
        value.monthly_income
        - value.essential_monthly_expenses
        - value.other_monthly_debt
        - total_payment
    )
    margin_before_savings = _money(cash_margin - value.monthly_savings_target)
    required_reduction = -margin_before_savings if value.preserve_savings else Decimal("0")
    requested_reduction = max(value.expense_reduction_target, Decimal("0"))
    budget_reallocation = _budget_reallocation(requested_reduction, value.reducible_categories)
    applied_reduction = sum((item.reduction for item in budget_reallocation.items), Decimal("0"))
    savings_after_mortgage = _money(margin_before_savings + applied_reduction)
    confidence, confidence_explanation = _confidence(value.history_months)

    scenarios: list[StressScenario] = []
    for increase in STRESS_RATE_INCREASES:
        stressed_installment = calculate_installment(
            value.principal, value.tan_annual + increase, value.duration_months,
            value.payment_cadence,
        )
        stressed_total = _money(stressed_installment / cadence + value.monthly_fee)
        scenarios.append(StressScenario(
            rate_increase=increase,
            installment=stressed_installment,
            total_monthly_payment=stressed_total,
            monthly_margin_after_savings=_money(
                value.monthly_income
                - value.essential_monthly_expenses
                - value.other_monthly_debt
                - stressed_total
                - value.monthly_savings_target
                + applied_reduction
            ),
        ))

    explanations: list[str] = []
    if confidence_explanation:
        explanations.append(confidence_explanation)
    if value.rate_type == "variabile":
        explanations.append("Gli scenari +1, +2 e +3 punti sono stress test, non previsioni del tasso.")
    else:
        explanations.append(
            "Gli scenari +1, +2 e +3 punti confrontano preventivi ipotetici: "
            "il tasso fisso del contratto non cambia."
        )
    if value.preserve_savings and budget_reallocation.required_reduction:
        explanations.append("La riduzione proposta riguarda solo le categorie selezionate e richiede conferma.")
    if value.available_liquidity < value.initial_costs:
        explanations.append("La liquidità dichiarata non copre i costi iniziali dichiarati.")

    stress_fails = any(scenario.monthly_margin_after_savings < 0 for scenario in scenarios)
    risk = (
        (savings_after_mortgage < 0 if value.preserve_savings else margin_before_savings < 0)
        or value.available_liquidity < value.initial_costs
        or (value.preserve_savings and budget_reallocation.uncovered_reduction > 0)
    )
    if risk:
        status = "a_rischio"
    elif confidence != "high" or stress_fails:
        status = "da_valutare"
    else:
        status = "sostenibile"

    if risk:
        explanations.append("A rischio: la rata supera il risparmio mensile disponibile oppure gli scenari non sono coperti.")
    elif confidence != "high" or stress_fails:
        explanations.append("Da valutare: lo storico è ancora limitato oppure uno stress test riduce troppo il margine.")
    else:
        explanations.append("Sostenibile: rata e costi del mutuo sono coperti dal reddito disponibile negli scenari considerati.")

    return MortgageSustainabilityResult(
        installment=installment,
        taeg=taeg,
        total_monthly_payment=total_payment,
        monthly_margin_before_savings=margin_before_savings,
        monthly_savings_after_mortgage=savings_after_mortgage,
        confidence=confidence,
        status=status,
        explanations=tuple(explanations),
        stress_scenarios=tuple(scenarios),
        budget_reallocation=budget_reallocation,
    )
