"""Alert budget per categoria in tempo reale sull'inserimento spesa.

Logica pura + orchestrazione backend-agnostica: legge budget e spese solo tramite
l'interfaccia `FinanceStorage` (get_categories / fetch_all_transactions), mai da
`notion_client` diretto. Funziona identico per Notion e Postgres.

Le soglie sono valutate a ogni spesa: se la spesa fa attraversare (o mantiene oltre)
una soglia, viene mostrato l'alert della banda più alta raggiunta.
"""

from __future__ import annotations

import calendar
import logging
from datetime import date
from typing import Optional

logger = logging.getLogger("financial_agent.budget_alert")

# Soglie in ordine crescente. Ogni banda: (frazione_budget, emoji, frase breve).
# La frase è volutamente semplice (2/3 parole), affiancata alla percentuale reale.
ALERT_BANDS: list[tuple[float, str, str]] = [
    (0.80, "⚠️", "sei al limite, occhio a sforare!"),
    (1.00, "🔴", "budget esaurito!"),
    (1.20, "🔴", "budget sforato!"),
]


def evaluate_budget_alert(
    category: str, spent: float, budget: Optional[float]
) -> Optional[str]:
    """Ritorna il messaggio di alert per la banda più alta superata, o `None`.

    Args:
        category: nome della categoria (mostrato all'utente).
        spent: totale speso nel mese per la categoria (valore assoluto).
        budget: budget mensile della categoria; `None`/0 → nessun alert.

    Returns:
        Stringa Markdown pronta da accodare al messaggio, o `None` se sotto soglia
        o senza budget impostato.
    """
    if not budget or budget <= 0:
        return None

    ratio = spent / budget
    triggered: Optional[tuple[float, str, str]] = None
    for band in ALERT_BANDS:
        if ratio >= band[0]:
            triggered = band  # tiene l'ultima (più alta) superata

    if triggered is None:
        return None

    _, emoji, phrase = triggered
    pct = round(ratio * 100)
    return (
        f"{emoji} Hai speso il {pct}% del budget di *{category}* "
        f"(€{spent:.0f}/€{budget:.0f}) — {phrase}"
    )


def _month_bounds(ref: date) -> tuple[date, date]:
    """Primo e ultimo giorno del mese di `ref`."""
    last_day = calendar.monthrange(ref.year, ref.month)[1]
    return ref.replace(day=1), ref.replace(day=last_day)


def check_expense_budget_alert(
    storage, category: Optional[str], ref: Optional[date] = None
) -> Optional[str]:
    """Calcola l'alert budget per una categoria dopo l'inserimento di una spesa.

    Backend-agnostico: il budget arriva da `storage.get_categories()`, lo speso
    mensile da `storage.fetch_all_transactions()`. La spesa appena salvata è già
    persistita, quindi è inclusa nel totale.

    Args:
        storage: implementazione `FinanceStorage` dell'utente corrente.
        category: categoria della spesa appena inserita.
        ref: data di riferimento (default: oggi). Il mese di `ref` definisce il
            periodo di budget considerato.

    Returns:
        Messaggio di alert Markdown, o `None` se nessuna soglia è superata,
        la categoria non ha budget, o i dati non sono disponibili.
    """
    if not category:
        return None
    ref = ref or date.today()

    # Budget della categoria (None se non impostato → nessun alert).
    budget: Optional[float] = None
    for cat in storage.get_categories():
        if cat.get("name") == category:
            raw = cat.get("monthly_budget")
            budget = float(raw) if raw is not None else None
            break
    if not budget or budget <= 0:
        return None

    # Speso month-to-date per la categoria nel mese di riferimento.
    start, end = _month_bounds(ref)
    txns = storage.fetch_all_transactions(start, end)
    spent = sum(
        abs(float(t.get("amount") or 0.0))
        for t in txns
        if t.get("category") == category
    )

    return evaluate_budget_alert(category, spent, budget)
