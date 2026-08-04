"""Piano di budget mensile per categoria, costruito a partire dal reddito.

Sostituisce il vecchio `get_budget_suggestions`, che proponeva come budget la media
delle spese degli ultimi tre mesi. Quel numero era una fotografia del passato
travestita da obiettivo: diceva "spendi 400€ al supermercato, quindi il tuo budget
è 400€", senza far risparmiare nulla e senza garantire che la somma dei budget
stesse dentro le entrate.

Qui si ragiona al contrario, dall'alto verso il basso:

    reddito − risparmio_target − spese_incomprimibili = quota_distribuibile

e la quota distribuibile viene ripartita fra le categorie variabili in proporzione
a quanto l'utente ci spende storicamente. Il risultato è un piano coerente: la somma
dei budget proposti non supera mai quello che l'utente guadagna, ed è agganciata al
suo obiettivo di risparmio reale quando ne ha uno.

Degradazioni esplicite, mai numeri inventati:
- meno di `MIN_MONTHS` mesi solari chiusi di storico → nessun piano;
- nessuna entrata tracciata → si ripiega sulla sola baseline storica robusta,
  dichiarando che è una fotografia e non un piano;
- quota distribuibile ≤ 0 → si restituisce l'avviso, non budget fittizi.

Logica pura e backend-agnostica: riceve un `FinancialStorage` e ne usa solo i
metodi di fetch, come `src/savings_goals_service.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from statistics import median

# Mesi solari chiusi da considerare per la baseline storica.
HISTORY_MONTHS = 6

# Sotto questa soglia di mesi chiusi non si propone nulla: con un solo mese di dati
# ogni media è rumore, ed era il difetto che faceva suggerire 1/3 della spesa reale.
MIN_MONTHS = 2

# Quota di reddito da risparmiare quando l'utente non ha un obiettivo attivo.
DEFAULT_SAVINGS_RATE = 0.20

# Soglia del filtro outlier: un mese si scarta se dista dalla mediana più di
# OUTLIER_MAD_FACTOR volte la deviazione assoluta mediana (MAD). Regge bene anche
# con pochi punti, al contrario della deviazione standard.
OUTLIER_MAD_FACTOR = 3.0

# Tipi di obiettivo da cui si può dedurre un target di risparmio mensile.
_SAVINGS_GOAL_TYPES = ("savings_rate", "net_savings")


@dataclass
class CategoryBudget:
    """Budget proposto per una categoria, con il dato storico che lo giustifica."""

    category_id: int | None
    name: str
    historical_median: float
    proposed_budget: float
    current_budget: float | None = None
    is_fixed: bool = False

    @property
    def delta(self) -> float:
        """Scostamento fra proposta e mediana storica (negativo = risparmio chiesto)."""
        return round(self.proposed_budget - self.historical_median, 2)


@dataclass
class BudgetPlan:
    """Piano completo, con tutti i numeri che servono a spiegarlo all'utente."""

    available: bool
    reason: str | None = None
    monthly_income: float = 0.0
    savings_target: float = 0.0
    fixed_costs: float = 0.0
    distributable: float = 0.0
    months_of_history: int = 0
    is_income_based: bool = True
    categories: list[CategoryBudget] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Forma serializzabile per l'API."""
        return {
            "available": self.available,
            "reason": self.reason,
            "monthly_income": self.monthly_income,
            "savings_target": self.savings_target,
            "fixed_costs": self.fixed_costs,
            "distributable": self.distributable,
            "months_of_history": self.months_of_history,
            "is_income_based": self.is_income_based,
            "categories": [
                {
                    "category_id": c.category_id,
                    "name": c.name,
                    "historical_median": c.historical_median,
                    "proposed_budget": c.proposed_budget,
                    "current_budget": c.current_budget,
                    "is_fixed": c.is_fixed,
                    "delta": c.delta,
                }
                for c in self.categories
            ],
        }


def _closed_months(today: date, count: int) -> list[tuple[int, int]]:
    """Gli ultimi `count` mesi solari **chiusi**, dal più vecchio al più recente.

    Il mese corrente è escluso di proposito: includerlo parzialmente distorceva la
    media a seconda del giorno in cui la si chiedeva.
    """
    year, month = today.year, today.month
    months = []
    for _ in range(count):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
        months.append((year, month))
    return list(reversed(months))


def _without_outliers(values: list[float]) -> list[float]:
    """Scarta i mesi anomali con il criterio MAD. Con meno di 3 punti non filtra."""
    if len(values) < 3:
        return values
    med = median(values)
    mad = median([abs(v - med) for v in values])
    if mad == 0:
        return values
    return [v for v in values if abs(v - med) <= OUTLIER_MAD_FACTOR * mad] or values


def _monthly_totals(records: list[dict], months: list[tuple[int, int]]) -> list[float]:
    """Totale per ciascun mese della finestra (0.0 nei mesi senza movimenti)."""
    buckets = {m: 0.0 for m in months}
    for rec in records:
        key = (rec["date"].year, rec["date"].month)
        if key in buckets:
            buckets[key] += rec["amount"]
    return [buckets[m] for m in months]


def _robust_monthly_value(values: list[float]) -> float:
    """Valore mensile rappresentativo: mediana dei mesi, outlier esclusi."""
    if not values:
        return 0.0
    return round(median(_without_outliers(values)), 2)


def _savings_target_from_goals(storage, monthly_income: float) -> float:
    """Risparmio mensile richiesto dall'obiettivo attivo dell'utente.

    `savings_rate` esprime una percentuale di reddito, `net_savings` un importo
    totale da spalmare sui mesi che mancano alla scadenza. Se non c'è un obiettivo
    utilizzabile si ricade su `DEFAULT_SAVINGS_RATE`.
    """
    try:
        goals = storage.fetch_savings_goals(status="active")
    except Exception:  # noqa: BLE001 — backend senza obiettivi: si usa il default
        goals = []

    targets = []
    for goal in goals:
        if goal.get("goal_type") not in _SAVINGS_GOAL_TYPES:
            continue
        amount = float(goal.get("target_amount") or 0)
        if amount <= 0:
            continue
        if goal["goal_type"] == "savings_rate":
            targets.append(monthly_income * amount / 100.0)
        else:
            months_left = _months_until(goal.get("target_date"))
            targets.append(amount / months_left if months_left else amount / 12.0)

    if not targets:
        return round(monthly_income * DEFAULT_SAVINGS_RATE, 2)
    # Più obiettivi attivi: vince il più impegnativo, così il piano li soddisfa tutti.
    return round(max(targets), 2)


def _months_until(target_date) -> int:
    """Mesi interi che mancano alla data (0 se assente o già passata)."""
    if not target_date:
        return 0
    if isinstance(target_date, str):
        try:
            target_date = date.fromisoformat(target_date)
        except ValueError:
            return 0
    today = date.today()
    if target_date <= today:
        return 0
    return max(1, (target_date.year - today.year) * 12 + target_date.month - today.month)


def build_budget_plan(storage, today: date | None = None) -> BudgetPlan:
    """Costruisce il piano di budget mensile per l'utente dello storage.

    Args:
        storage: un `FinancialStorage`.
        today: data di riferimento (per i test); default `date.today()`.

    Returns:
        Un `BudgetPlan`. Quando `available` è False, `reason` spiega perché e
        `categories` è vuoto: nessun numero viene inventato per riempire il vuoto.
    """
    today = today or date.today()
    months = _closed_months(today, HISTORY_MONTHS)
    window_start = date(months[0][0], months[0][1], 1)
    window_end = _last_day_of_month(*months[-1])

    expenses = storage.fetch_all_transactions(window_start, window_end)
    incomes = storage.fetch_income(window_start, window_end)

    months_with_data = {(e["date"].year, e["date"].month) for e in expenses}
    covered = [m for m in months if m in months_with_data]
    if len(covered) < MIN_MONTHS:
        return BudgetPlan(
            available=False,
            reason="not_enough_history",
            months_of_history=len(covered),
        )

    # La finestra si restringe ai mesi effettivamente coperti: un utente iscritto da
    # tre mesi non deve vedersi diviso per sei.
    months = covered
    monthly_income = _robust_monthly_value(_monthly_totals(incomes, months))

    per_category = _spending_by_category(storage, expenses, months)
    fixed_costs = _fixed_costs(storage)

    if monthly_income <= 0:
        # Senza entrate tracciate non esiste un tetto: si può solo fotografare
        # la spesa storica, dichiarandolo.
        return BudgetPlan(
            available=True,
            reason="no_income_baseline_only",
            months_of_history=len(months),
            is_income_based=False,
            fixed_costs=fixed_costs,
            categories=[
                CategoryBudget(
                    category_id=cat["id"], name=cat["name"],
                    historical_median=cat["median"], proposed_budget=cat["median"],
                    current_budget=cat["current_budget"],
                )
                for cat in per_category
            ],
        )

    savings_target = _savings_target_from_goals(storage, monthly_income)
    distributable = round(monthly_income - savings_target - fixed_costs, 2)

    if distributable <= 0:
        return BudgetPlan(
            available=False,
            reason="not_sustainable",
            monthly_income=monthly_income,
            savings_target=savings_target,
            fixed_costs=fixed_costs,
            distributable=distributable,
            months_of_history=len(months),
        )

    variable_total = sum(c["median"] for c in per_category)
    scale = distributable / variable_total if variable_total > 0 else 0.0

    categories = [
        CategoryBudget(
            category_id=cat["id"],
            name=cat["name"],
            historical_median=cat["median"],
            # La proporzione preserva le priorità dell'utente; la scala fa quadrare
            # il totale con quello che può davvero permettersi.
            proposed_budget=round(cat["median"] * scale, 2),
            current_budget=cat["current_budget"],
        )
        for cat in per_category
    ]

    return BudgetPlan(
        available=True,
        monthly_income=monthly_income,
        savings_target=savings_target,
        fixed_costs=fixed_costs,
        distributable=distributable,
        months_of_history=len(months),
        categories=categories,
    )


def _last_day_of_month(year: int, month: int) -> date:
    from calendar import monthrange
    return date(year, month, monthrange(year, month)[1])


def _spending_by_category(storage, expenses: list[dict], months: list[tuple[int, int]]) -> list[dict]:
    """Mediana mensile di spesa per categoria, ordinata dalla più costosa.

    Le categorie archiviate sono escluse: `get_categories()` le filtra per default.
    """
    known = {c["name"]: c for c in storage.get_categories()}

    by_category: dict[str, list[dict]] = {}
    for exp in expenses:
        name = exp.get("category")
        if not name or name not in known:
            continue
        by_category.setdefault(name, []).append(exp)

    result = []
    for name, records in by_category.items():
        value = _robust_monthly_value(_monthly_totals(records, months))
        if value <= 0:
            continue
        cat = known[name]
        result.append({
            "id": cat.get("id"),
            "name": name,
            "median": value,
            "current_budget": cat.get("monthly_budget"),
        })
    return sorted(result, key=lambda c: c["median"], reverse=True)


def _fixed_costs(storage) -> float:
    """Costo mensile degli abbonamenti attivi: spesa non comprimibile."""
    try:
        subscriptions = storage.fetch_subscriptions()
    except Exception:  # noqa: BLE001 — backend senza abbonamenti
        return 0.0
    return round(sum(float(s.get("amount") or 0) for s in subscriptions), 2)
