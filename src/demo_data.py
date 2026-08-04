"""
demo_data.py — Carica 30 giorni di spese fittizie per la modalità demo.

Le spese vengono prefissate con "[Demo] " per essere chiaramente identificabili
e vengono cancellate automaticamente al primo salvataggio reale dell'utente.
"""

import random
from datetime import date, timedelta

from src.storage.base import FinancialStorage

# Prefisso obbligatorio su tutte le spese demo
DEMO_PREFIX = "[Demo] "

# Categorie e template (nome spesa, range importo in €)
_EXPENSE_TEMPLATES: dict[str, list[tuple[str, tuple[float, float]]]] = {
    "Alimentari": [
        ("Supermercato Esselunga",  (28.0, 95.0)),
        ("Lidl",                    (15.0, 55.0)),
        ("Coop",                    (20.0, 70.0)),
        ("Fruttivendolo",           (5.0,  18.0)),
        ("Carrefour",               (20.0, 60.0)),
    ],
    "Ristoranti & Bar": [
        ("Caffè mattutino",         (1.5,  3.5)),
        ("Pranzo in pausa",         (8.0,  16.0)),
        ("Cena al ristorante",      (25.0, 75.0)),
        ("Pizza con amici",         (12.0, 22.0)),
        ("Aperitivo",               (6.0,  15.0)),
    ],
    "Trasporti": [
        ("Benzina",                 (40.0, 85.0)),
        ("Parcheggio",              (2.0,  14.0)),
        ("Uber/Taxi",               (8.0,  28.0)),
        ("Autostrada",              (5.0,  25.0)),
    ],
    "Svago & Intrattenimento": [
        ("Cinema UCI",              (10.0, 16.0)),
        ("Libri Amazon",            (8.0,  28.0)),
        ("Museo/Mostra",            (10.0, 20.0)),
    ],
    "Salute & Farmacia": [
        ("Farmacia",                (8.0,  38.0)),
        ("Parafarmacia",            (5.0,  22.0)),
    ],
    "Shopping": [
        ("Amazon acquisto",         (15.0, 80.0)),
        ("Zara",                    (25.0, 70.0)),
        ("H&M",                     (20.0, 55.0)),
    ],
    "Casa & Utilities": [
        ("Bolletta luce",           (55.0, 130.0)),
        ("Internet fibra",          (28.0, 35.0)),
        ("Articoli casa",           (10.0, 50.0)),
    ],
}

# Probabilità che in un dato giorno venga creata una spesa per categoria
_DAILY_PROB: dict[str, float] = {
    "Alimentari":               0.50,
    "Ristoranti & Bar":         0.65,
    "Trasporti":                0.40,
    "Svago & Intrattenimento":  0.18,
    "Salute & Farmacia":        0.07,
    "Shopping":                 0.15,
    "Casa & Utilities":         0.04,
}

_REQUIRED_CATEGORIES = list(_EXPENSE_TEMPLATES.keys())


def _ensure_categories(storage: FinancialStorage) -> None:
    """Crea le categorie necessarie se non esistono già."""
    existing = set(storage.get_category_names(include_archived=True))
    for cat in _REQUIRED_CATEGORIES:
        if cat not in existing:
            storage.create_category(cat)


def _ensure_account(storage: FinancialStorage) -> str | None:
    """Restituisce l'ID del primo conto disponibile; ne crea uno demo se assente."""
    accounts = storage.fetch_accounts()
    if accounts:
        return str(accounts[0]["id"])
    created = storage.create_account(DEMO_PREFIX + "Conto Corrente", initial_balance=0.0)
    return str(created["id"])


def load_demo_data(storage: FinancialStorage, seed: int | None = None) -> int:
    """Carica 30 giorni di spese fittizie nello storage dell'utente.

    Args:
        storage: istanza FinancialStorage già inizializzata per l'utente.
        seed: seed random opzionale (utile nei test per output deterministico).

    Returns:
        Numero di spese create.
    """
    rng = random.Random(seed)
    _ensure_categories(storage)
    account_id = _ensure_account(storage)

    today = date.today()
    created = 0

    for days_ago in range(29, -1, -1):  # dal più vecchio al più recente
        current_date = today - timedelta(days=days_ago)

        for category, prob in _DAILY_PROB.items():
            if rng.random() > prob:
                continue
            templates = _EXPENSE_TEMPLATES[category]
            name_raw, (min_amt, max_amt) = rng.choice(templates)
            amount = round(rng.uniform(min_amt, max_amt), 2)
            name = DEMO_PREFIX + name_raw

            storage.create_expense(
                expense_date=current_date,
                amount=amount,
                name=name,
                category_name=category,
                account_id=account_id,
            )
            created += 1

    return created


def delete_demo_data(storage: FinancialStorage) -> int:
    """Cancella tutte le spese demo (con prefisso DEMO_PREFIX) dallo storage.

    Funziona solo con backend che espongono delete_expenses_by_prefix().
    Per Notion, delega al metodo specifico se disponibile.

    Returns:
        Numero di spese cancellate (-1 se il backend non supporta la cancellazione).
    """
    if hasattr(storage, "delete_expenses_by_prefix"):
        return storage.delete_expenses_by_prefix(DEMO_PREFIX)
    return -1
