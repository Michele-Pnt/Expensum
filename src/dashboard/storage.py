"""Storage factory dei dati finanziari per utente: sceglie PostgreSQL o Notion.

Modulo leaf: legge lo store applicativo (utenti/config) via `current_app.config["STORE"]`,
mai import diretto di `app.py`/`factory.py`. Vedi CLAUDE.md — architettura storage
multi-backend: non introdurre qui concetti Notion-specifici (page_id/block_id) al
di fuori di `notion_client.py`.
"""
from __future__ import annotations

import json

from flask import current_app, jsonify

from src.notion_client import NotionFinanceClient
from src.storage.base import FinancialStorage
from src.storage.notion_storage import NotionStorage
from src.storage.postgres_storage import PostgresStorage


def _store():
    return current_app.config["STORE"]


def _build_financial_storage(user, pg_session=None) -> FinancialStorage:
    """Costruisce il FinancialStorage corretto in base al backend dell'utente."""
    if user.storage_backend == "postgres":
        return PostgresStorage(session=pg_session, user_id=user.chat_id)
    # Backend Notion
    store = _store()
    stored_schemas = store.get_database_schemas(user.chat_id)
    db_schemas = {}
    for db_key, data in stored_schemas.items():
        props = data.get("properties")
        mapped = data.get("mapped")
        db_schemas[db_key] = {
            "database_id": data.get("database_id"),
            "properties": json.loads(props) if isinstance(props, str) else (props or {}),
            "mapped": json.loads(mapped) if isinstance(mapped, str) else (mapped or {}),
        }
    notion_client = NotionFinanceClient(
        api_key=user.notion_access_token,
        expense_db_id=user.expense_db_id,
        income_db_id=user.income_db_id,
        categories_db_id=user.categories_db_id,
        monthly_balance_db_id=user.monthly_balance_db_id,
        accounts_db_id=user.accounts_db_id,
        subscriptions_db_id=user.subscriptions_db_id,
        pay_transfer_db_id=user.pay_transfer_db_id,
        db_schemas=db_schemas,
    )
    return NotionStorage(notion_client, store=store, user_id=user.chat_id)


class _QuickExpensesStorageError(Exception):
    """Errore interno durante il recupero dei suggerimenti rapidi chat."""


def _get_storage_for_chat(chat_id: str) -> FinancialStorage | None:
    """Restituisce il FinancialStorage dell'utente per le letture della chat."""
    from src.dashboard.auth import _get_user_by_chat_id

    user = _get_user_by_chat_id(chat_id)
    if user is None:
        return None
    if user.storage_backend == "postgres":
        return _build_financial_storage(user, pg_session=_store().Session())
    return _build_financial_storage(user)


def _pg_or_401(s, chat_id):
    """Restituisce (PostgresStorage, None) o (None, response 400) se backend != postgres."""
    from src.user_store import User
    from src.storage import rls
    # La RLS si applica al primo statement della transazione (listener after_begin):
    # va impostata PRIMA di qualunque query su questa sessione, altrimenti la query
    # su User qui sotto apre la transazione senza app.user_id e ogni successivo
    # INSERT/UPDATE sulle tabelle protette da RLS viene rifiutato dal database.
    rls.bind_user(s, chat_id)
    user = s.query(User).filter_by(chat_id=chat_id).first()
    if not user or user.storage_backend != "postgres":
        return None, (jsonify({"error": "Solo backend DB interno supportato"}), 400)
    return PostgresStorage(session=s, user_id=chat_id), None


def _get_user_plan_type(chat_id: str) -> str:
    """Ritorna 'free' o 'pro' per l'utente corrente."""
    try:
        plan = _store().get_user_plan(chat_id)
        return plan.get("plan_type", "free")
    except Exception:
        return "free"


def _pg_pro_or_error(s, chat_id):
    """Restituisce (PostgresStorage, None) o (None, response) per feature Pro-only.

    Usato dagli endpoint /api/savings-goals*: richiede sia backend PostgreSQL sia
    piano Pro. Stesso pattern di gating di /api/analytics/budget-status.
    """
    plan_type = _get_user_plan_type(chat_id)
    if plan_type != "pro":
        return None, (jsonify({"error": "Funzionalità riservata agli utenti Pro", "plan_type": plan_type}), 403)
    pg, err = _pg_or_401(s, chat_id)
    if err:
        body, _status = err
        return None, (body, 403)
    return pg, None
