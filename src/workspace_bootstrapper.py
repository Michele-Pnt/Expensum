"""
src/workspace_bootstrapper.py — Inizializzazione automatica del workspace utente.

Viene chiamato una sola volta al termine dell'OAuth, dopo che i 7 database
Notion sono stati scoperti e salvati. Crea dati di default (categorie, conti,
abbonamenti) se il workspace è ancora vuoto.

Idempotente: se il workspace è già popolato non crea duplicati.
"""

import logging
from typing import NamedTuple

from src.storage.base import FinancialStorage

logger = logging.getLogger("financial_agent.bootstrapper")

# ---------------------------------------------------------------------------
# Dati di default
# ---------------------------------------------------------------------------

DEFAULT_CATEGORIES: list[str] = [
    "Alimentari",
    "Ristoranti",
    "Trasporti",
    "Salute",
    "Casa",
    "Bollette",
    "Intrattenimento",
    "Sport",
    "Abbigliamento",
    "Tecnologia",
    "Viaggi",
    "Regali",
    "Altro",
]

DEFAULT_ACCOUNTS: list[tuple[str, float]] = [
    ("Conto Corrente", 0.0),
    ("Contanti", 0.0),
]

# Abbonamenti di default vuoti — l'utente li aggiunge nel setup
DEFAULT_SUBSCRIPTIONS: list[str] = []


# ---------------------------------------------------------------------------
# Risultato del bootstrap
# ---------------------------------------------------------------------------

class BootstrapResult(NamedTuple):
    categories_created: list[str]
    accounts_created: list[str]
    subscriptions_created: list[str]
    skipped_categories: bool
    skipped_accounts: bool

    def is_empty(self) -> bool:
        """True se non è stato creato nulla (workspace già popolato)."""
        return (
            not self.categories_created
            and not self.accounts_created
            and not self.subscriptions_created
        )

    def to_telegram_message(self) -> str:
        """Genera il riepilogo da inviare all'utente via Telegram."""
        if self.is_empty():
            return ""

        lines = ["🚀 <b>Workspace inizializzato!</b>\n"]

        if self.categories_created:
            lines.append(f"📂 <b>Categorie create ({len(self.categories_created)}):</b>")
            lines.append(", ".join(self.categories_created))
        elif self.skipped_categories:
            lines.append("📂 Categorie: già presenti, nessuna modifica.")

        if self.accounts_created:
            lines.append(f"\n🏦 <b>Conti creati ({len(self.accounts_created)}):</b>")
            lines.append(", ".join(self.accounts_created))
        elif self.skipped_accounts:
            lines.append("\n🏦 Conti: già presenti, nessuna modifica.")

        lines.append(
            "\n\n💡 Usa <b>/setup</b> per personalizzare categorie, conti e abbonamenti."
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def bootstrap_workspace(storage: FinancialStorage) -> BootstrapResult:
    """Inizializza il workspace con dati di default.

    Controlla prima se il workspace è già popolato per garantire idempotenza:
    - Se esistono categorie → non ne crea di nuove
    - Se esistono conti → non ne crea di nuovi

    Args:
        storage: implementazione di FinancialStorage dell'utente

    Returns:
        BootstrapResult con il dettaglio di ciò che è stato creato
    """
    categories_created: list[str] = []
    accounts_created: list[str] = []
    subscriptions_created: list[str] = []
    skipped_categories = False
    skipped_accounts = False

    # --- Categorie ---
    try:
        existing_categories = storage.get_category_names()
        if existing_categories:
            logger.info(
                "[Bootstrap] Categorie già presenti (%d), skip.", len(existing_categories)
            )
            skipped_categories = True
        else:
            for name in DEFAULT_CATEGORIES:
                storage.create_category(name)
                categories_created.append(name)
                logger.info("[Bootstrap] Categoria creata: %s", name)
    except Exception as e:
        logger.error("[Bootstrap] Errore creazione categorie: %s", e)

    # --- Conti ---
    try:
        existing_accounts = storage.fetch_accounts()
        if existing_accounts:
            logger.info(
                "[Bootstrap] Conti già presenti (%d), skip.", len(existing_accounts)
            )
            skipped_accounts = True
        else:
            for name, balance in DEFAULT_ACCOUNTS:
                storage.create_account(name, initial_balance=balance)
                accounts_created.append(name)
                logger.info("[Bootstrap] Conto creato: %s", name)
    except Exception as e:
        logger.error("[Bootstrap] Errore creazione conti: %s", e)

    # --- Abbonamenti ---
    # Default vuoti: vengono creati solo se DEFAULT_SUBSCRIPTIONS è popolato
    try:
        for name in DEFAULT_SUBSCRIPTIONS:
            storage.create_subscription(name)
            subscriptions_created.append(name)
            logger.info("[Bootstrap] Abbonamento creato: %s", name)
    except Exception as e:
        logger.error("[Bootstrap] Errore creazione abbonamenti: %s", e)

    result = BootstrapResult(
        categories_created=categories_created,
        accounts_created=accounts_created,
        subscriptions_created=subscriptions_created,
        skipped_categories=skipped_categories,
        skipped_accounts=skipped_accounts,
    )
    logger.info(
        "[Bootstrap] Completato — categorie: %d, conti: %d, abbonamenti: %d",
        len(categories_created),
        len(accounts_created),
        len(subscriptions_created),
    )
    return result
