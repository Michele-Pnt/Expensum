"""Ricostruzione della serie storica del capitale (saldi conti mese per mese).

Sorgente unica di verità per "quanto capitale aveva l'utente al mese X". Esiste
per evitare che i vari consumatori (endpoint analytics, obiettivi di risparmio,
report) reimplementino ciascuno la propria formula e divergano: è esattamente ciò
che era successo con `/api/analytics/capital-trend`, che mostrava un capitale
negativo mentre la pagina "Il mio spazio" mostrava conti tutti positivi.

Definizione di capitale adottata, allineata a `PostgresStorage._compute_balance`
(la formula che alimenta "Il mio spazio"):

    saldo_conto = opening_balance + entrate - uscite + trasferimenti_in - trasferimenti_out

dove entrate e uscite sono **solo quelle attribuite a quel conto**. Le transazioni
senza conto (`account_id = NULL`) e quelle che puntano a un conto ormai cancellato
non appartengono ad alcun saldo e vengono quindi escluse dal capitale: erano la
causa del bug: venivano accumulate in un bucket che partiva da zero e conteneva
solo uscite, quindi trascinava il totale sotto zero mese dopo mese.

Il modulo è logica pura e backend-agnostica: riceve un `FinancialStorage` e usa
solo i suoi metodi di fetch, senza conoscere Notion o Postgres.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# Data di partenza per la ricostruzione: il saldo è cumulativo, quindi va sempre
# ricostruito dall'inizio della storia dell'utente, non dalla finestra visualizzata.
EPOCH = date(2000, 1, 1)


@dataclass
class MonthPoint:
    """Capitale a fine di un dato mese solare."""

    year: int
    month: int
    total: float
    by_account: dict[int, float] = field(default_factory=dict)


@dataclass
class WealthSeries:
    """Serie mensile del capitale più i metadati che servono a spiegarla.

    `unassigned_expenses` e `unassigned_incomes` sono i totali esclusi dal calcolo
    perché non attribuibili ad alcun conto esistente. Non sono un errore: sono un
    dato che la UI può usare per invitare l'utente ad assegnare un conto alle
    proprie spese, invece di lasciare inspiegata la differenza rispetto alla somma
    dei saldi.
    """

    points: list[MonthPoint] = field(default_factory=list)
    account_names: dict[int, str] = field(default_factory=dict)
    unassigned_expenses: float = 0.0
    unassigned_incomes: float = 0.0

    @property
    def totals(self) -> list[float]:
        """Solo i totali, per i consumatori che non usano il dettaglio per conto."""
        return [p.total for p in self.points]


def _month_key(value: date) -> tuple[int, int]:
    return (value.year, value.month)


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def build_wealth_series(
    storage,
    today: date,
    *,
    account_id: int | None = None,
    since: date | None = None,
) -> WealthSeries:
    """Ricostruisce il capitale mese per mese fino a `today`.

    Args:
        storage: un `FinancialStorage` (Postgres o Notion).
        today: ultima data da considerare.
        account_id: se valorizzato, restringe la serie a quel singolo conto.
        since: primo mese da restituire. I mesi precedenti vengono comunque
            calcolati (il saldo è cumulativo) ma non compaiono nel risultato.

    Returns:
        Una `WealthSeries` con un punto per ogni mese, dal primo mese con
        attività (o da `since`) fino al mese di `today`.
    """
    accounts = storage.fetch_accounts()
    targets = [a for a in accounts if account_id is None or a["id"] == account_id]
    if not targets:
        return WealthSeries()

    balances: dict[int, float] = {a["id"]: float(a.get("opening_balance") or 0.0) for a in targets}
    target_ids = set(balances)
    # `name` è opzionale: i consumatori che usano solo i totali (obiettivi di
    # risparmio) non lo forniscono necessariamente.
    account_names = {a["id"]: a.get("name") or f"Conto {a['id']}" for a in targets}

    incomes = storage.fetch_income(EPOCH, today)
    expenses = storage.fetch_all_transactions(EPOCH, today)
    transfers = storage.fetch_transfers(EPOCH, today)

    # Delta mensile per conto. Entrate e uscite non attribuibili a un conto target
    # vengono contabilizzate a parte, mai nel capitale.
    deltas: dict[tuple[int, int], dict[int, float]] = {}
    unassigned_expenses = 0.0
    unassigned_incomes = 0.0

    def _apply(when: date, acc_id: int, amount: float) -> None:
        deltas.setdefault(_month_key(when), {})
        deltas[_month_key(when)][acc_id] = deltas[_month_key(when)].get(acc_id, 0.0) + amount

    for inc in incomes:
        acc_id = inc.get("account_id")
        if acc_id not in target_ids:
            unassigned_incomes += inc["amount"]
            continue
        _apply(inc["date"], acc_id, inc["amount"])

    for exp in expenses:
        acc_id = exp.get("account_id")
        if acc_id not in target_ids:
            unassigned_expenses += exp["amount"]
            continue
        _apply(exp["date"], acc_id, -exp["amount"])

    # Un trasferimento tra due conti entrambi target si somma e si sottrae nello
    # stesso mese: si annulla da solo sul totale, ma sposta correttamente il saldo
    # fra le due linee per-conto.
    for tr in transfers:
        if tr.get("to_account_id") in target_ids:
            _apply(tr["date"], tr["to_account_id"], tr["amount"])
        if tr.get("from_account_id") in target_ids:
            _apply(tr["date"], tr["from_account_id"], -tr["amount"])

    first_activity = min(deltas) if deltas else None
    if first_activity is None:
        start = _month_key(since or today)
    elif since is not None and _month_key(since) < first_activity:
        start = _month_key(since)
    else:
        start = first_activity

    series = WealthSeries(
        account_names=account_names,
        unassigned_expenses=round(unassigned_expenses, 2),
        unassigned_incomes=round(unassigned_incomes, 2),
    )
    cutoff = _month_key(since) if since else None

    year, month = start
    while (year, month) <= _month_key(today):
        for acc_id, delta in deltas.get((year, month), {}).items():
            balances[acc_id] += delta
        if cutoff is None or (year, month) >= cutoff:
            series.points.append(MonthPoint(
                year=year,
                month=month,
                total=round(sum(balances.values()), 2),
                by_account={aid: round(bal, 2) for aid, bal in balances.items()},
            ))
        year, month = _next_month(year, month)

    return series
