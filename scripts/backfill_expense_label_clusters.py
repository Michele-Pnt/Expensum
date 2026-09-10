"""Backfill idempotente dei cluster delle voci di spesa per utenti PostgreSQL."""

from __future__ import annotations

from src.expense_label_normalizer import assign_label_cluster
from src.storage.models import Expense
from src.user_store import UserStore


def backfill_user(
    store: UserStore,
    chat_id: str,
    *,
    dry_run: bool = False,
) -> dict[str, int | str | bool]:
    """Assegna cluster alle sole spese storiche ancora prive di etichetta.

    Il job non modifica le descrizioni, non attraversa tenant e può essere rieseguito:
    dopo un run completato la query delle spese pendenti è vuota. Il chiamante deve
    selezionare esplicitamente l'utente; non esiste un'iterazione implicita su tutti
    gli utenti in un processo applicativo ordinario.
    """
    user = store.get_user(chat_id)
    if user is None:
        return {"skipped": "utente non trovato o inattivo", "expenses_scanned": 0, "clusters_created": 0}
    if user.storage_backend != "postgres":
        return {
            "skipped": "backend non-Postgres, feature non applicabile",
            "expenses_scanned": 0,
            "clusters_created": 0,
        }

    with store.Session() as session:
        expenses = (
            session.query(Expense)
            .filter(Expense.user_id == str(chat_id), Expense.label_cluster_id.is_(None))
            .order_by(Expense.id)
            .all()
        )
        scanned = len(expenses)
        if dry_run:
            return {"expenses_scanned": scanned, "clusters_created": 0, "dry_run": True}

        created = 0
        for expense in expenses:
            result = assign_label_cluster(session, str(chat_id), expense.name, expense.category_id)
            expense.label_cluster_id = result.cluster_id
            created += int(result.created)
        session.commit()

    return {"expenses_scanned": scanned, "clusters_created": created, "dry_run": False}
