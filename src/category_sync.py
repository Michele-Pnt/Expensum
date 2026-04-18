"""
src/category_sync.py — Sincronizzazione categorie verso user_categories.

Tre trigger:
  A. Post-setup (OAuth o Postgres) — prima popolazione
  B. Pre-report — dati freschi prima di costruire il report
  D. Job notturno APScheduler — aggiornamento bulk alle 03:00

Per utenti Notion: fetch da Notion API → upsert su user_categories.
Per utenti Postgres: calcolo da tabella expenses → update average su user_categories.
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.user_store import UserStore

logger = logging.getLogger("financial_agent.category_sync")


def sync_categories_to_local(
    client,  # NotionFinanceClient
    user_id: str,
    store: UserStore,
) -> int:
    """Scarica le categorie dal DB Notion dell'utente e le salva in user_categories.

    Ritorna il numero di categorie sincronizzate.
    Il campo average viene letto dalla formula Notion (media mensile storica).
    """
    db_id = client.categories_db_id
    if not db_id:
        logger.warning("[CategorySync] Notion categories_db_id non configurato per %s.", user_id)
        return 0

    try:
        ds_id = client._get_data_source_id(db_id)
    except Exception as e:
        logger.error("[CategorySync] Impossibile ottenere data_source_id per %s: %s", user_id, e)
        return 0

    categories = []
    has_more = True
    cursor = None

    try:
        while has_more:
            resp = client._query_with_retry(ds_id, {}, cursor)
            for page in resp.get("results", []):
                page_id = page["id"]
                props = page.get("properties", {})
                name = "Sconosciuta"
                average_val = 0.0

                for prop_name, prop in props.items():
                    if prop.get("type") == "title":
                        rt = prop.get("title", [])
                        if rt:
                            name = rt[0].get("plain_text", "Sconosciuta")
                    elif prop_name.lower() == "average":
                        ptype = prop.get("type", "")
                        if ptype == "formula":
                            f_val = prop.get("formula", {})
                            if f_val.get("type") == "number":
                                average_val = float(f_val.get("number") or 0.0)
                        elif ptype == "number":
                            average_val = float(prop.get("number") or 0.0)

                if name != "Sconosciuta":
                    categories.append({
                        "name": name,
                        "average": average_val,
                        "notion_page_id": page_id,
                        "synced_at": datetime.utcnow(),
                    })

            has_more = resp.get("has_more", False)
            cursor = resp.get("next_cursor")

    except Exception as e:
        logger.error("[CategorySync] Errore fetch categorie Notion per %s: %s", user_id, e)
        return 0

    if categories:
        store.upsert_user_categories(user_id, categories)
        logger.info("[CategorySync] Notion: sincronizzate %d categorie per %s.", len(categories), user_id)

    return len(categories)


def compute_category_averages(
    user_id: str,
    session: Session,
    store: UserStore,
    category_filter: Optional[str] = None,
) -> None:
    """Calcola la media mensile storica per le categorie Postgres e aggiorna user_categories.

    La formula replica quella Notion: totale_spese / numero_mesi_unici_con_spese.
    Se category_filter è specificato, aggiorna solo quella categoria.
    """
    try:
        if category_filter:
            rows = session.execute(
                text(
                    "SELECT category_name, "
                    "SUM(amount) as total, "
                    "COUNT(DISTINCT strftime('%Y-%m', expense_date)) as months "
                    "FROM expenses "
                    "WHERE user_id = :uid AND category_name = :cat "
                    "GROUP BY category_name"
                ),
                {"uid": user_id, "cat": category_filter},
            ).fetchall()
        else:
            rows = session.execute(
                text(
                    "SELECT category_name, "
                    "SUM(amount) as total, "
                    "COUNT(DISTINCT strftime('%Y-%m', expense_date)) as months "
                    "FROM expenses "
                    "WHERE user_id = :uid "
                    "GROUP BY category_name"
                ),
                {"uid": user_id},
            ).fetchall()

        for row in rows:
            cat_name, total, months = row
            avg = round(total / months, 2) if months > 0 else 0.0
            store.update_category_average(user_id, cat_name, avg)

        logger.info(
            "[CategorySync] Postgres: aggiornate %d medie per %s.", len(rows), user_id
        )
    except Exception as e:
        logger.error("[CategorySync] Errore calcolo medie Postgres per %s: %s", user_id, e)


def refresh_category_averages(
    user_id: str,
    store: UserStore,
    session: Optional[Session] = None,
    notion_client=None,
) -> None:
    """Entry point unificata per aggiornare le medie categorie.

    Instrada automaticamente in base a storage_backend dell'utente.
    Almeno uno tra session (Postgres) e notion_client (Notion) deve essere fornito.
    """
    user = store.get_user(user_id)
    if not user:
        logger.warning("[CategorySync] Utente %s non trovato.", user_id)
        return

    if user.storage_backend == "notion":
        if notion_client is None:
            logger.warning("[CategorySync] notion_client mancante per utente Notion %s.", user_id)
            return
        sync_categories_to_local(notion_client, user_id, store)
    else:
        if session is None:
            logger.warning("[CategorySync] session mancante per utente Postgres %s.", user_id)
            return
        compute_category_averages(user_id, session, store)
