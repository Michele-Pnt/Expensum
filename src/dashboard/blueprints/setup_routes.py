"""Setup Mini App (form dinamico Notion/Postgres), onboarding wizard, e CRUD
generico "gestione" (`/api/manage/*`) usato dal setup legacy.

Blueprint leaf: legge lo store condiviso via `current_app.config["STORE"]`, mai
import diretto di `app.py`/`factory.py` (nessun ciclo).
"""
from __future__ import annotations

import json
import logging
import re

import requests
from flask import Blueprint, current_app, jsonify, render_template, request
from notion_client import Client as NotionClient

from config import Config
from src import analytics
from src.dashboard.auth import _get_user_by_chat_id, _resolve_request_chat_id
from src.dashboard.blueprints.space_routes import _is_fallback_category
from src.dashboard.budget_validation import _parse_money, _validate_category_budgets_with_general_budget
from src.notion_client import NotionFinanceClient
from src.recurring_income_service import RecurringIncomeService
from src.storage.notion_storage import NotionStorage
from src.storage.postgres_storage import PostgresStorage
from src.workspace_bootstrapper import bootstrap_lifestyle_categories

logger = logging.getLogger(__name__)

setup_bp = Blueprint("setup", __name__)

# Mirror del valore in app.py (usato anche da login/register/telegram-login,
# non ancora estratti): consolidabile in un'unica costante condivisa quando
# anche auth_routes.py verrà estratto.
TELEGRAM_REQUEST_TIMEOUT = 10

ONBOARDING_GOALS = frozenset({
    "cashflow_control", "budget", "emergency_fund", "savings_goal",
    "increase_savings",
})
PROFILE_FIELDS = frozenset({
    "household_type", "has_job", "financial_experience",
    "report_detail_preference", "acquisition_source",
})


def _store():
    return current_app.config["STORE"]


def _forbidden_setup_response():
    return "<h1>Accesso negato</h1><p>Link non valido o sessione non autorizzata.</p>", 403


def _resync_category_cache_from_notion(user) -> None:
    """Riallinea la cache `user_categories` a Notion dopo una mutazione categoria.

    Per gli utenti Notion, create/rename/delete di categorie dalla web app scrivono
    solo su Notion: senza questo re-sync la cache (che alimenta il parser del bot)
    resterebbe disallineata fino al job notturno. Best-effort: la scrittura su Notion
    è già avvenuta, quindi eventuali errori qui vengono solo loggati.
    """
    if user.storage_backend != "notion" or not user.categories_db_id:
        return
    try:
        from src.category_sync import sync_categories_to_local

        notion_client = NotionFinanceClient(
            api_key=user.notion_access_token,
            categories_db_id=user.categories_db_id,
        )
        sync_categories_to_local(notion_client, user.chat_id, _store())
    except Exception as e:
        logger.warning(
            "[Manage] Re-sync cache categorie fallito per %s: %s", user.chat_id, e
        )


@setup_bp.route("/setup")
def setup_form():
    """Mostra il form dinamico per il setup iniziale."""
    store = _store()
    reg_token = request.args.get("reg_token")
    if not reg_token:
        return _forbidden_setup_response()

    with store.Session() as s:
        from src.user_store import OAuthSession, User
        sess = s.query(OAuthSession).filter_by(state=reg_token).first()
        if not sess:
             return _forbidden_setup_response()

        # Lega la RLS prima di qualsiasi altra query protetta (vedi rls.rebind_user).
        from src.storage import rls
        rls.rebind_user(s, sess.chat_id)

        user = s.query(User).filter_by(chat_id=sess.chat_id).first()
        if not user:
            return _forbidden_setup_response()

        # --- Branch PostgreSQL: niente schemi Notion, form semplificato ---
        if user.storage_backend == "postgres":
            pg_storage = PostgresStorage(session=s, user_id=user.chat_id)
            existing_accounts = pg_storage.fetch_accounts()
            existing_categories = pg_storage.get_categories()
            existing_subscriptions = pg_storage.fetch_subscriptions()
            is_first_setup = user.setup_completed_at is None
            return render_template(
                "setup_miniapp.html",
                backend="postgres",
                schemas={},
                reg_token=reg_token,
                user_name=user.username or "Utente",
                available_accounts=existing_accounts,
                available_categories=existing_categories,
                available_subscriptions=existing_subscriptions,
                is_first_setup=is_first_setup,
                # I col_* servono solo al ramo Notion: passiamo stringhe vuote come placeholder
                col_accounts_initial_amount="",
                col_accounts_type="",
                col_sub_type="",
                col_sub_amount="",
                col_sub_category="",
                col_sub_account="",
                col_sub_last_billed="",
            )

        # --- Branch Notion (flusso legacy invariato) ---
        if not user.notion_access_token:
            return _forbidden_setup_response()

        # I 3 DB che ci servono per il setup
        setup_db_keys = ["accounts_db_id", "categories_db_id", "subscriptions_db_id"]

        # Fetchiamo SEMPRE gli schemi live da Notion al momento del setup:
        # evita problemi di cache con properties vuote o stantie.
        setup_bindings = {k: getattr(user, k, None) for k in setup_db_keys if getattr(user, k, None)}
        live_schemas_raw = {}
        if setup_bindings:
            try:
                live_schemas_raw = NotionFinanceClient.discover_db_schemas(
                    user.notion_access_token, setup_bindings
                )
                for db_key, schema_data in live_schemas_raw.items():
                    store.save_database_schema(
                        chat_id=user.chat_id,
                        db_key=db_key,
                        notion_db_id=schema_data.get("database_id"),
                        properties_json=json.dumps(schema_data.get("properties", {})),
                        mapped_properties_json=json.dumps(schema_data.get("mapped", {}))
                    )
            except Exception as e:
                logger.exception("[Setup] Errore recupero schemi live da Notion: %s", e)

        # Se il fetch live è fallito, proviamo con la cache
        if not live_schemas_raw:
            stored_schemas = store.get_database_schemas(user.chat_id)
        else:
            stored_schemas = {
                db_key: {
                    "database_id": sd.get("database_id"),
                    "properties": json.dumps(sd.get("properties", {})),
                    "mapped": json.dumps(sd.get("mapped", {}))
                }
                for db_key, sd in live_schemas_raw.items()
            }

        # Prepariamo il dizionario finale con le properties parsate
        schemas = {}
        for db_key in setup_db_keys:
            data = stored_schemas.get(db_key)
            if not data:
                continue
            try:
                props = data["properties"]
                mapped = data.get("mapped")
                schemas[db_key] = {
                    "database_id": data["database_id"],
                    "properties": json.loads(props) if isinstance(props, str) else props,
                    "mapped": json.loads(mapped) if mapped and isinstance(mapped, str) else {}
                }
            except Exception as e:
                logger.exception("[Setup] Errore parsing schema %s: %s", db_key, e)

        # Recupera accounts e categories esistenti su Notion per i dropdown relation
        available_accounts = []
        available_categories = []
        try:
            nc = NotionFinanceClient(
                api_key=user.notion_access_token,
                accounts_db_id=user.accounts_db_id,
                categories_db_id=user.categories_db_id,
                db_schemas=schemas,
            )
            available_accounts = nc.fetch_accounts()
        except Exception as e:
            logger.exception("[Setup] fetch_accounts fallito: %s", e)
        try:
            nc_cat = NotionFinanceClient(
                api_key=user.notion_access_token,
                categories_db_id=user.categories_db_id,
                db_schemas=schemas,
            )
            available_categories = nc_cat.fetch_categories()
        except Exception as e:
            logger.exception("[Setup] fetch_categories da Notion fallito: %s", e)
            try:
                from src.storage.models import UserCategory
                # Sessione bindata al tenant per la RLS (user_categories è protetta).
                with store._user_session(user.chat_id) as _cs:
                    cat_rows = _cs.query(UserCategory).filter_by(user_id=user.chat_id).all()
                    available_categories = [
                        {"id": r.notion_page_id or str(r.id), "name": r.name, "monthly_budget": r.monthly_budget}
                        for r in cat_rows
                    ]
            except Exception as e2:
                logger.exception("[Setup] fetch_categories da DB fallito: %s", e2)

        available_subscriptions = []
        try:
            nc_sub = NotionFinanceClient(
                api_key=user.notion_access_token,
                subscriptions_db_id=user.subscriptions_db_id,
                categories_db_id=user.categories_db_id,
                db_schemas=schemas,
            )
            available_subscriptions = nc_sub.fetch_subscriptions()
        except Exception as e:
            logger.exception("[Setup] fetch_subscriptions da Notion fallito: %s", e)

        return render_template("setup_miniapp.html",
                               backend="notion",
                               schemas=schemas,
                               reg_token=reg_token,
                               user_name=user.username or "Utente",
                               available_accounts=available_accounts,
                               available_categories=available_categories,
                               available_subscriptions=available_subscriptions,
                               is_first_setup=user.setup_completed_at is None,
                               col_accounts_initial_amount=Config.NOTION_ACCOUNTS_COL_INITIAL_AMOUNT,
                               col_accounts_type=Config.NOTION_ACCOUNTS_COL_TYPE,
                               col_sub_type=Config.NOTION_SUB_COL_TYPE,
                               col_sub_amount=Config.NOTION_SUB_COL_AMOUNT,
                               col_sub_category=Config.NOTION_SUB_COL_CATEGORY,
                               col_sub_account=Config.NOTION_SUB_COL_ACCOUNT,
                               col_sub_last_billed=Config.NOTION_SUB_COL_LAST_BILLED)

@setup_bp.route("/api/setup-complete", methods=["POST"])
def api_setup_complete():
    """Riceve i dati dal form Mini App e popola Notion."""
    store = _store()
    payload = request.json
    reg_token = payload.get("reg_token")
    items_data = payload.get("items", {}) # { "accounts_db_id": [...], ... }

    if not reg_token:
        return jsonify({"error": "Missing token"}), 400

    with store.Session() as s:
        from src.user_store import OAuthSession, User
        sess = s.query(OAuthSession).filter_by(state=reg_token).first()
        if not sess:
            return jsonify({"error": "Access denied"}), 403

        # Lega la RLS prima di qualsiasi altra query protetta (vedi rls.rebind_user).
        from src.storage import rls
        rls.rebind_user(s, sess.chat_id)

        user = s.query(User).filter_by(chat_id=sess.chat_id).first()
        if not user:
            return jsonify({"error": "Access denied"}), 403

        # --- Branch PostgreSQL: payload piatto, creazione diretta via PostgresStorage ---
        if user.storage_backend == "postgres":
            pg_storage = PostgresStorage(session=s, user_id=user.chat_id)
            errors: list[str] = []
            fatal_errors: list[str] = []
            created_count = 0

            # 1. Categorie — deduplicazione contro esistenti e contro il payload stesso
            existing_cat_names = {n.lower() for n in pg_storage.get_category_names(include_archived=True)}
            seen_cats: set[str] = set()
            for item in items_data.get("categories", []):
                name = (item.get("name") or "").strip()
                if not name:
                    errors.append("Nome vuoto in categories, elemento saltato")
                    continue
                key = name.lower()
                if key in existing_cat_names:
                    errors.append(f"Categoria '{name}' già esistente, saltata")
                    continue
                if key in seen_cats:
                    errors.append(f"Categoria '{name}' duplicata nel payload, saltata")
                    continue
                seen_cats.add(key)
                try:
                    pg_storage.create_category(name)
                    created_count += 1
                except Exception as e:
                    msg = f"Errore categoria '{name}': {e}"
                    errors.append(msg)
                    fatal_errors.append(msg)

            # 2. Conti
            for item in items_data.get("accounts", []):
                name = (item.get("name") or "").strip()
                if not name:
                    errors.append("Nome vuoto in accounts, elemento saltato")
                    continue
                try:
                    initial_balance = float(item.get("initial_balance") or 0.0)
                    pg_storage.create_account(name, initial_balance=initial_balance)
                    created_count += 1
                except Exception as e:
                    msg = f"Errore account '{name}': {e}"
                    errors.append(msg)
                    fatal_errors.append(msg)

            # 3. Abbonamenti
            for item in items_data.get("subscriptions", []):
                name = (item.get("name") or "").strip()
                if not name:
                    errors.append("Nome vuoto in subscriptions, elemento saltato")
                    continue
                try:
                    pg_storage.create_subscription(
                        name,
                        last_billed=item.get("last_billed") or None,
                    )
                    created_count += 1
                except Exception as e:
                    msg = f"Errore abbonamento '{name}': {e}"
                    errors.append(msg)
                    fatal_errors.append(msg)

            if not fatal_errors:
                if user.setup_completed_at is None:
                    store.mark_setup_completed(user.chat_id)
                    telegram_url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"
                    try:
                        requests.post(telegram_url, json={
                            "chat_id": user.chat_id,
                            "text": (
                                f"✅ <b>Setup completato!</b>\n"
                                f"Ho creato {created_count} elementi nel database interno.\n\n"
                                f"Ora puoi iniziare a scrivermi le tue spese!"
                            ),
                            "parse_mode": "HTML"
                        }, timeout=TELEGRAM_REQUEST_TIMEOUT)
                    except Exception:
                        pass

                return jsonify({"status": "ok", "created": created_count, "details": errors})

            return jsonify({"error": "Setup failed", "details": errors}), 500

        # --- Branch Notion (flusso legacy invariato) ---
        # Carichiamo gli schemi dal DB così _get_property_name può risolvere
        # i nomi reali delle colonne Notion (es. "Type" invece di "Account type")
        stored_schemas = store.get_database_schemas(user.chat_id)
        db_schemas = {}
        for db_key, data in stored_schemas.items():
            props = data.get("properties")
            mapped = data.get("mapped")
            db_schemas[db_key] = {
                "database_id": data.get("database_id"),
                "properties": json.loads(props) if isinstance(props, str) else (props or {}),
                "mapped": json.loads(mapped) if isinstance(mapped, str) else (mapped or {})
            }

        # DEBUG TEMPORANEO
        for k, v in db_schemas.items():
            logger.debug(
                "[DEBUG] schema %s -> properties keys: %s, mapped: %s",
                k, list(v.get('properties', {}).keys()), v.get('mapped'),
            )

        notion = NotionFinanceClient(
            api_key=user.notion_access_token,
            accounts_db_id=user.accounts_db_id,
            categories_db_id=user.categories_db_id,
            subscriptions_db_id=user.subscriptions_db_id,
            db_schemas=db_schemas,
        )

        errors = []
        created_count = 0

        # --- Helper: estrazione valori dal payload Notion ---

        def _extract_name(prop_data: dict) -> str:
            """Estrae il testo dal primo campo title o rich_text trovato."""
            for _, value in prop_data.items():
                if isinstance(value, dict):
                    for notion_type in ('title', 'rich_text'):
                        if notion_type in value:
                            items_list = value[notion_type]
                            if items_list:
                                return items_list[0].get('text', {}).get('content', '')
            return ''

        def _extract_number(prop_data: dict, prop_name: str):
            val = prop_data.get(prop_name, {})
            if isinstance(val, dict) and 'number' in val:
                return val['number']
            return None

        def _extract_select(prop_data: dict, prop_name: str):
            val = prop_data.get(prop_name, {})
            if isinstance(val, dict) and 'select' in val:
                return val['select'].get('name')
            return None

        def _extract_relation_ref(prop_data: dict, prop_name: str):
            """Estrae un riferimento relation: può essere un UUID o '__name__:Nome'."""
            val = prop_data.get(prop_name, {})
            if isinstance(val, dict) and '__relation_ref' in val:
                return val['__relation_ref']
            return None

        def _extract_date(prop_data: dict, prop_name: str) -> str | None:
            """Estrae la data ISO (YYYY-MM-DD) da un campo date Notion."""
            val = prop_data.get(prop_name, {})
            if isinstance(val, dict) and 'date' in val:
                date_obj = val['date']
                if isinstance(date_obj, dict):
                    return date_obj.get('start')
            return None

        def _resolve_ref(ref: str, name_to_id: dict):
            """Risolve un riferimento: se inizia con '__name__:' cerca nella mappa, altrimenti è già un UUID."""
            if not ref:
                return None
            if ref.startswith('__name__:'):
                return name_to_id.get(ref[len('__name__:'):])
            return ref  # già un page_id UUID Notion

        # --- Fase 1: Categorie (devono esistere prima delle subscriptions) ---
        cat_map = {}  # nome → page_id
        seen_cat_names: set[str] = set()
        for prop_data in items_data.get("categories_db_id", []):
            name = ''
            try:
                name = _extract_name(prop_data)
                if not name:
                    errors.append("Nome vuoto in categories_db_id, elemento saltato")
                    continue
                if name.lower() in seen_cat_names:
                    errors.append(f"Categoria '{name}' duplicata nel payload, saltata")
                    continue
                seen_cat_names.add(name.lower())
                result = notion.create_category(name)
                cat_map[name] = result["id"]
                created_count += 1
            except Exception as e:
                errors.append(f"Errore categoria '{name}': {e}")

        # --- Fase 2: Accounts (devono esistere prima delle subscriptions) ---
        acc_map = {}  # nome → page_id
        for prop_data in items_data.get("accounts_db_id", []):
            name = ''
            try:
                logger.debug("[DEBUG] account prop_data keys: %s", list(prop_data.keys()))
                logger.debug("[DEBUG] account prop_data: %s", prop_data)
                name = _extract_name(prop_data)
                acc_type = _extract_select(prop_data, Config.NOTION_ACCOUNTS_COL_TYPE)
                logger.debug(
                    "[DEBUG] account name='%s', type='%s' (cercato con chiave '%s')",
                    name, acc_type, Config.NOTION_ACCOUNTS_COL_TYPE,
                )
                if not name:
                    errors.append("Nome vuoto in accounts_db_id, elemento saltato")
                    continue
                result = notion.create_account(
                    name,
                    initial_amount=_extract_number(prop_data, Config.NOTION_ACCOUNTS_COL_INITIAL_AMOUNT),
                    account_type=_extract_select(prop_data, Config.NOTION_ACCOUNTS_COL_TYPE),
                )
                acc_map[name] = result["id"]
                created_count += 1
            except Exception as e:
                errors.append(f"Errore account '{name}': {e}")

        # --- Fase 3: Subscriptions (risolve relation usando le mappe sopra) ---
        for prop_data in items_data.get("subscriptions_db_id", []):
            name = ''
            try:
                name = _extract_name(prop_data)
                if not name:
                    errors.append("Nome vuoto in subscriptions_db_id, elemento saltato")
                    continue
                notion.create_subscription(
                    name,
                    sub_type=_extract_select(prop_data, Config.NOTION_SUB_COL_TYPE),
                    amount=_extract_number(prop_data, Config.NOTION_SUB_COL_AMOUNT),
                    category_id=_resolve_ref(
                        _extract_relation_ref(prop_data, Config.NOTION_SUB_COL_CATEGORY), cat_map
                    ),
                    account_id=_resolve_ref(
                        _extract_relation_ref(prop_data, Config.NOTION_SUB_COL_ACCOUNT), acc_map
                    ),
                    last_billed=_extract_date(prop_data, Config.NOTION_SUB_COL_LAST_BILLED),
                )
                created_count += 1
            except Exception as e:
                errors.append(f"Errore abbonamento '{name}': {e}")

        if created_count > 0 or not errors:
            if user.setup_completed_at is None:
                store.mark_setup_completed(user.chat_id)
                telegram_url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"
                try:
                    requests.post(telegram_url, json={
                        "chat_id": user.chat_id,
                        "text": (
                            f"✅ <b>Setup completato!</b>\n"
                            f"Ho creato {created_count} elementi nel tuo Notion.\n\n"
                            f"Ora puoi iniziare a scrivermi le tue spese!"
                        ),
                        "parse_mode": "HTML"
                    }, timeout=TELEGRAM_REQUEST_TIMEOUT)
                except Exception:
                    pass

            return jsonify({"status": "ok", "created": created_count, "details": errors})

        return jsonify({"error": "Setup failed", "details": errors}), 500


@setup_bp.route("/api/delete-notion-item", methods=["DELETE"])
def api_delete_notion_item():
    """Legacy: archivia un elemento Notion. Mantenuto per backward compat."""
    store = _store()
    payload = request.json or {}
    reg_token = payload.get("reg_token")
    page_id = payload.get("page_id")

    if not reg_token or not page_id:
        return jsonify({"error": "Missing reg_token or page_id"}), 400

    with store.Session() as s:
        from src.user_store import OAuthSession, User
        sess = s.query(OAuthSession).filter_by(state=reg_token).first()
        if not sess:
            return jsonify({"error": "Access denied"}), 403

        user = s.query(User).filter_by(chat_id=sess.chat_id).first()
        if not user:
            return jsonify({"error": "Access denied"}), 403

        try:
            notion_raw = NotionClient(auth=user.notion_access_token)
            notion_raw.pages.update(page_id=page_id, archived=True)
            return jsonify({"status": "ok"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# CRUD endpoints per la mini app di gestione
# ---------------------------------------------------------------------------

def _resolve_manage_session(reg_token: str):
    """Risolve reg_token → (user, session_db) oppure None."""
    from src.user_store import OAuthSession, User
    with _store().Session() as s:
        sess = s.query(OAuthSession).filter_by(state=reg_token).first()
        if not sess:
            return None, None, None
        user = s.query(User).filter_by(chat_id=sess.chat_id).first()
        return user, sess, s


@setup_bp.route("/api/manage/add", methods=["POST"])
def api_manage_add():
    """Aggiunge una singola entità (account / category / subscription).

    Body JSON:
        {
          "reg_token": "...",
          "entity_type": "account" | "category" | "subscription",
          "data": { "name": "...", "initial_balance": 0.0, "last_billed": "YYYY-MM-DD" }
        }
    """
    store = _store()
    payload = request.json or {}
    reg_token = payload.get("reg_token")
    entity_type = payload.get("entity_type")
    data = payload.get("data") or {}

    if not reg_token or not entity_type:
        return jsonify({"error": "Missing reg_token or entity_type"}), 400

    from src.user_store import OAuthSession, User
    with store.Session() as s:
        sess = s.query(OAuthSession).filter_by(state=reg_token).first()
        if not sess:
            return jsonify({"error": "Access denied"}), 403

        # Lega la RLS prima di qualsiasi altra query protetta (vedi rls.rebind_user).
        from src.storage import rls
        rls.rebind_user(s, sess.chat_id)

        user = s.query(User).filter_by(chat_id=sess.chat_id).first()
        if not user:
            return jsonify({"error": "Access denied"}), 403

        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "Il campo 'name' è obbligatorio"}), 400

        try:
            if user.storage_backend == "postgres":
                pg = PostgresStorage(session=s, user_id=user.chat_id)
                if entity_type == "category":
                    # Lo unique constraint (user_id, name) vale anche sulle archiviate:
                    # senza includerle il pre-check passerebbe e il commit fallirebbe
                    # con un 409 generico che non spiega nulla all'utente.
                    for cat in pg.fetch_categories_full(include_archived=True):
                        if cat["name"].lower() != name.lower():
                            continue
                        if cat.get("archived"):
                            return jsonify({
                                "error": f"Categoria '{name}' esiste ed è archiviata",
                                "archived_category_id": cat["id"],
                                "can_restore": True,
                            }), 409
                        return jsonify({"error": f"Categoria '{name}' già esistente"}), 409
                    monthly_budget, budget_error = _parse_money(
                        data.get("monthly_budget"), "monthly_budget"
                    )
                    if budget_error:
                        return budget_error
                    coherence_error = _validate_category_budgets_with_general_budget(
                        user.chat_id,
                        name,
                        monthly_budget,
                    )
                    if coherence_error:
                        return coherence_error
                    result = pg.create_category(name, monthly_budget=monthly_budget)
                elif entity_type == "account":
                    result = pg.create_account(
                        name,
                        initial_balance=float(data.get("initial_balance") or 0.0),
                        account_type=data.get("account_type") or None,
                    )
                elif entity_type == "subscription":
                    result = pg.create_subscription(
                        name,
                        amount=float(data["amount"]) if data.get("amount") not in (None, "", "0", 0) else None,
                        last_billed=data.get("last_billed") or None,
                        sub_type=data.get("sub_type") or None,
                        account_id=int(data["account_id"]) if data.get("account_id") else None,
                        category_id=int(data["category_id"]) if data.get("category_id") else None,
                    )
                else:
                    return jsonify({"error": f"entity_type '{entity_type}' non supportato"}), 400
            else:
                # Notion backend
                stored_schemas = store.get_database_schemas(user.chat_id)
                add_db_schemas: dict = {}
                for db_key, schema_data in stored_schemas.items():
                    _props = schema_data.get("properties")
                    _mapped = schema_data.get("mapped")
                    add_db_schemas[db_key] = {
                        "database_id": schema_data.get("database_id"),
                        "properties": json.loads(_props) if isinstance(_props, str) else (_props or {}),
                        "mapped": json.loads(_mapped) if isinstance(_mapped, str) else (_mapped or {}),
                    }
                notion = NotionFinanceClient(
                    api_key=user.notion_access_token,
                    accounts_db_id=user.accounts_db_id,
                    categories_db_id=user.categories_db_id,
                    subscriptions_db_id=user.subscriptions_db_id,
                    db_schemas=add_db_schemas,
                )
                if entity_type == "category":
                    monthly_budget, budget_error = _parse_money(
                        data.get("monthly_budget"), "monthly_budget"
                    )
                    if budget_error:
                        return budget_error
                    raw = notion.create_category(name, monthly_budget=monthly_budget)
                    result = {"id": raw["id"], "name": name, "monthly_budget": monthly_budget}
                elif entity_type == "account":
                    raw = notion.create_account(
                        name,
                        initial_amount=float(data.get("initial_balance") or 0.0),
                        account_type=data.get("account_type"),
                    )
                    result = {"id": raw["id"], "name": name, "balance": data.get("initial_balance") or 0.0}
                elif entity_type == "subscription":
                    raw = notion.create_subscription(
                        name,
                        sub_type=data.get("sub_type"),
                        amount=float(data["amount"]) if data.get("amount") else None,
                        last_billed=data.get("last_billed") or None,
                        category_id=data.get("category_id") or None,
                        account_id=data.get("account_id") or None,
                    )
                    result = {"id": raw["id"], "name": name, "last_billed": data.get("last_billed")}
                else:
                    return jsonify({"error": f"entity_type '{entity_type}' non supportato"}), 400

            if entity_type == "category":
                _resync_category_cache_from_notion(user)
            return jsonify({"status": "ok", "entity": result})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


@setup_bp.route("/api/manage/remove", methods=["DELETE"])
def api_manage_remove():
    """Rimuove una singola entità per entrambi i backend.

    Body JSON:
        {
          "reg_token": "...",
          "entity_type": "account" | "category" | "subscription",
          "entity_id": <int per Postgres, page_id UUID per Notion>
        }
    """
    store = _store()
    payload = request.json or {}
    reg_token = payload.get("reg_token")
    entity_type = payload.get("entity_type")
    entity_id = payload.get("entity_id")

    if not reg_token or not entity_type or entity_id is None:
        return jsonify({"error": "Missing reg_token, entity_type o entity_id"}), 400

    from src.user_store import OAuthSession, User
    with store.Session() as s:
        sess = s.query(OAuthSession).filter_by(state=reg_token).first()
        if not sess:
            return jsonify({"error": "Access denied"}), 403

        # Lega la RLS prima di qualsiasi altra query protetta (vedi rls.rebind_user).
        from src.storage import rls
        rls.rebind_user(s, sess.chat_id)

        user = s.query(User).filter_by(chat_id=sess.chat_id).first()
        if not user:
            return jsonify({"error": "Access denied"}), 403

        try:
            if user.storage_backend == "postgres":
                pg = PostgresStorage(session=s, user_id=user.chat_id)
                if entity_type == "category":
                    # Stessa guardia dell'endpoint dedicato: senza, cancellare
                    # «Altro» ne farebbe ricreare una col nome alterato, e il
                    # conteggio dei mesi puliti smetterebbe di riconoscerla.
                    if _is_fallback_category(pg, int(entity_id)):
                        return jsonify({
                            "error": (
                                f"La categoria «{Config.CATEGORY_FALLBACK_NAME}» "
                                "non può essere eliminata"
                            )
                        }), 400
                    ok = pg.delete_category(int(entity_id)) is not None
                elif entity_type == "account":
                    ok = pg.delete_account(int(entity_id))
                elif entity_type == "subscription":
                    ok = pg.delete_subscription(int(entity_id))
                else:
                    return jsonify({"error": f"entity_type '{entity_type}' non supportato"}), 400
                if not ok:
                    return jsonify({"error": "Elemento non trovato"}), 404
            else:
                notion_raw = NotionClient(auth=user.notion_access_token)
                notion_raw.pages.update(page_id=str(entity_id), archived=True)

            if entity_type == "category":
                _resync_category_cache_from_notion(user)
            return jsonify({"status": "ok"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


@setup_bp.route("/api/manage/update", methods=["PUT"])
def api_manage_update():
    """Modifica un'entità esistente.

    Body JSON:
        {
          "reg_token": "...",
          "entity_type": "account" | "category" | "subscription",
          "entity_id": <int per Postgres, page_id UUID per Notion>,
          "data": { campi da aggiornare }
        }
    """
    store = _store()
    payload = request.json or {}
    reg_token = payload.get("reg_token")
    entity_type = payload.get("entity_type")
    entity_id = payload.get("entity_id")
    data = payload.get("data") or {}

    if not reg_token or not entity_type or entity_id is None:
        return jsonify({"error": "Missing reg_token, entity_type o entity_id"}), 400

    from src.user_store import OAuthSession, User
    with store.Session() as s:
        sess = s.query(OAuthSession).filter_by(state=reg_token).first()
        if not sess:
            return jsonify({"error": "Access denied"}), 403

        # Lega la RLS prima di qualsiasi altra query protetta (vedi rls.rebind_user).
        from src.storage import rls
        rls.rebind_user(s, sess.chat_id)

        user = s.query(User).filter_by(chat_id=sess.chat_id).first()
        if not user:
            return jsonify({"error": "Access denied"}), 403

        try:
            if user.storage_backend == "postgres":
                pg = PostgresStorage(session=s, user_id=user.chat_id)
                if entity_type == "category":
                    monthly_budget, budget_error = _parse_money(
                        data.get("monthly_budget"), "monthly_budget"
                    )
                    if budget_error:
                        return budget_error
                    current_category = next(
                        (
                            item for item in pg.fetch_categories_full(include_archived=False)
                            if item["id"] == int(entity_id)
                        ),
                        None,
                    )
                    if current_category is None:
                        return jsonify({"error": "Elemento non trovato"}), 404
                    next_name = data.get("name") or current_category["name"]
                    coherence_error = _validate_category_budgets_with_general_budget(
                        user.chat_id,
                        next_name,
                        monthly_budget,
                    )
                    if coherence_error:
                        return coherence_error
                    result = pg.update_category(
                        int(entity_id),
                        name=data.get("name") or None,
                        monthly_budget=monthly_budget,
                    )
                elif entity_type == "account":
                    result = pg.update_account(
                        int(entity_id),
                        name=data.get("name") or None,
                        balance=float(data["balance"]) if data.get("balance") is not None else None,
                        account_type=data.get("account_type") or None,
                    )
                elif entity_type == "subscription":
                    result = pg.update_subscription(
                        int(entity_id),
                        name=data.get("name") or None,
                        amount=float(data["amount"]) if data.get("amount") not in (None, "", "0", 0) else None,
                        last_billed=data.get("last_billed") or None,
                        sub_type=data.get("sub_type") or None,
                        account_id=int(data["account_id"]) if data.get("account_id") else None,
                        category_id=int(data["category_id"]) if data.get("category_id") else None,
                    )
                else:
                    return jsonify({"error": f"entity_type '{entity_type}' non supportato"}), 400
                if result is None:
                    return jsonify({"error": "Elemento non trovato"}), 404
            else:
                # Notion: risolvi i nomi colonna reali dagli schemi salvati
                stored_schemas = store.get_database_schemas(user.chat_id)
                db_schemas: dict = {}
                for db_key, schema_data in stored_schemas.items():
                    props = schema_data.get("properties")
                    mapped = schema_data.get("mapped")
                    db_schemas[db_key] = {
                        "database_id": schema_data.get("database_id"),
                        "properties": json.loads(props) if isinstance(props, str) else (props or {}),
                        "mapped": json.loads(mapped) if isinstance(mapped, str) else (mapped or {}),
                    }
                notion_client = NotionFinanceClient(
                    api_key=user.notion_access_token,
                    accounts_db_id=user.accounts_db_id,
                    categories_db_id=user.categories_db_id,
                    subscriptions_db_id=user.subscriptions_db_id,
                    db_schemas=db_schemas,
                )

                properties: dict = {}
                if data.get("name"):
                    title_col = notion_client._resolve_title_property_name(
                        entity_type + "s_db_id",
                        getattr(user, entity_type + "s_db_id", None) or "",
                    )
                    properties[title_col] = {"title": [{"text": {"content": data["name"]}}]}
                if data.get("last_billed"):
                    col = notion_client._get_property_name(
                        "subscriptions_db_id", "last_billed", Config.NOTION_SUB_COL_LAST_BILLED
                    )
                    properties[col] = {"date": {"start": data["last_billed"]}}
                if data.get("amount") is not None:
                    col = notion_client._get_property_name(
                        "subscriptions_db_id", "sub_amount", Config.NOTION_SUB_COL_AMOUNT
                    )
                    properties[col] = {"number": float(data["amount"])}
                if data.get("account_type"):
                    col = notion_client._get_property_name(
                        "accounts_db_id", "account_type", Config.NOTION_ACCOUNTS_COL_TYPE
                    )
                    properties[col] = {"select": {"name": data["account_type"]}}
                if data.get("monthly_budget") is not None:
                    monthly_budget, budget_error = _parse_money(
                        data.get("monthly_budget"), "monthly_budget"
                    )
                    if budget_error:
                        return budget_error
                    col = notion_client._get_property_name(
                        "categories_db_id", "monthly_budget", "Monthly Budget"
                    )
                    if col:
                        properties[col] = {"number": float(monthly_budget)}
                if data.get("sub_type"):
                    col = notion_client._get_property_name(
                        "subscriptions_db_id", "sub_type", Config.NOTION_SUB_COL_TYPE
                    )
                    properties[col] = {"select": {"name": data["sub_type"]}}
                if data.get("account_id"):
                    col = notion_client._get_property_name(
                        "subscriptions_db_id", "account", Config.NOTION_SUB_COL_ACCOUNT
                    )
                    properties[col] = {"relation": [{"id": str(data["account_id"])}]}
                if data.get("category_id"):
                    col = notion_client._get_property_name(
                        "subscriptions_db_id", "category", Config.NOTION_SUB_COL_CATEGORY
                    )
                    properties[col] = {"relation": [{"id": str(data["category_id"])}]}
                if properties:
                    try:
                        notion_client._client.pages.update(page_id=str(entity_id), properties=properties)
                    except Exception as notion_err:
                        err_str = str(notion_err)
                        # Se Notion rifiuta una property perché non esiste nel DB, riprova
                        # senza le property opzionali (monthly_budget, account_type, relations)
                        optional_cols = {
                            notion_client._get_property_name("categories_db_id", "monthly_budget", "Monthly Budget"),
                            notion_client._get_property_name("accounts_db_id", "account_type", Config.NOTION_ACCOUNTS_COL_TYPE),
                            notion_client._get_property_name("subscriptions_db_id", "sub_type", Config.NOTION_SUB_COL_TYPE),
                            notion_client._get_property_name("subscriptions_db_id", "account", Config.NOTION_SUB_COL_ACCOUNT),
                            notion_client._get_property_name("subscriptions_db_id", "category", Config.NOTION_SUB_COL_CATEGORY),
                        }
                        optional_cols.discard(None)
                        if "is not a property that exists" in err_str:
                            # Estrai il nome della property incriminata dall'errore Notion
                            bad_prop_match = re.search(r": (.+) is not a property that exists", err_str)
                            if bad_prop_match:
                                bad_prop = bad_prop_match.group(1)
                                logger.warning(
                                    "Notion ha rifiutato property '%s' (schema stale?), retry senza.",
                                    bad_prop,
                                )
                                retry_props = {k: v for k, v in properties.items() if k != bad_prop}
                                if retry_props:
                                    notion_client._client.pages.update(
                                        page_id=str(entity_id), properties=retry_props
                                    )
                                # Invalida il mapping stale dallo schema in memoria
                                for db_key, schema in notion_client._db_schemas.items():
                                    mapped = schema.get("mapped") or {}
                                    stale_keys = [k for k, v in mapped.items() if v == bad_prop]
                                    for k in stale_keys:
                                        del mapped[k]
                                    props = schema.get("properties") or {}
                                    props.pop(bad_prop, None)
                            else:
                                raise
                        else:
                            raise
                result = {"id": entity_id, **data}

            if entity_type == "category":
                _resync_category_cache_from_notion(user)
            return jsonify({"status": "ok", "entity": result})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Onboarding API
# ---------------------------------------------------------------------------

@setup_bp.route("/api/onboarding/status", methods=["GET"])
def api_onboarding_status():
    """Stato corrente del wizard di onboarding."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"authorized": False}), 401
    prefs = _store().get_user_preferences(chat_id)
    return jsonify(prefs)


@setup_bp.route("/api/onboarding/step", methods=["POST"])
def api_onboarding_step():
    """Salva i dati di uno step del wizard."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    step = body.get("step")
    data = body.get("data", {})
    if not step:
        return jsonify({"error": "step required"}), 400
    _store().save_onboarding_progress(chat_id, step, data)
    return jsonify({"status": "ok"})


@setup_bp.route("/api/onboarding/profile", methods=["POST"])
def api_onboarding_profile():
    """Persist validated ordered goals and optional progressive profile data."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    raw_goals = body.get("goals")
    if not isinstance(raw_goals, list) or not raw_goals:
        return jsonify({"error": "At least one goal is required"}), 400
    if len(raw_goals) > len(ONBOARDING_GOALS):
        return jsonify({"error": "Too many goals"}), 400
    goals = []
    for index, item in enumerate(raw_goals, start=1):
        if not isinstance(item, dict) or item.get("code") not in ONBOARDING_GOALS:
            return jsonify({"error": "Invalid goal"}), 400
        goals.append({"code": item["code"], "priority_order": index})
    if len({item["code"] for item in goals}) != len(goals):
        return jsonify({"error": "Duplicate goal"}), 400
    profile = body.get("profile") or {}
    if not isinstance(profile, dict) or set(profile) - PROFILE_FIELDS:
        return jsonify({"error": "Invalid profile field"}), 400
    _store().save_onboarding_profile(chat_id, goals, profile)
    return jsonify({"status": "ok", "goals": goals})


@setup_bp.route("/api/onboarding/income", methods=["POST"])
def api_onboarding_income():
    """Configure an optional recurring salary and its destination account."""
    store = _store()
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    try:
        amount = float(body["amount"])
        payday_day = int(body["payday_day"])
        account_name = str(body["account_name"]).strip()
        income_name = str(body.get("income_name") or "Stipendio").strip()
        cadence = str(body.get("cadence") or "monthly")
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Invalid recurring income payload"}), 400
    user = _get_user_by_chat_id(chat_id)
    if not user or user.storage_backend != "postgres":
        return jsonify({"error": "Recurring income requires the internal storage"}), 400
    db_session = store.Session()
    try:
        storage = PostgresStorage(session=db_session, user_id=chat_id)
        result = RecurringIncomeService(
            store, storage, chat_id, currency=user.currency or "EUR"
        ).configure_salary(
            account_name=account_name,
            income_name=income_name,
            amount=amount,
            cadence=cadence,
            payday_day=payday_day,
        )
        return jsonify({"status": "ok", "account_id": result.account_id,
                        "rule_id": result.rule_id})
    except (ValueError, KeyError) as exc:
        return jsonify({"error": str(exc)}), 400
    finally:
        db_session.close()


@setup_bp.route("/api/onboarding/generate-categories", methods=["POST"])
def api_onboarding_generate_categories():
    """Genera categorie personalizzate con Mistral Small in base al lifestyle."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    lifestyle = body.get("lifestyle", {})
    try:
        from src.mistral_client import MistralClient
        client = MistralClient()
        categories = client.generate_lifestyle_categories(lifestyle)
    except Exception as e:
        logger.warning("Errore generazione categorie onboarding: %s", e)
        from src.workspace_bootstrapper import DEFAULT_CATEGORIES
        categories = list(DEFAULT_CATEGORIES)
    return jsonify({"categories": categories})


@setup_bp.route("/api/onboarding/complete", methods=["POST"])
def api_onboarding_complete():
    """Finalizza l'onboarding: genera categorie da hobby e segna come completato.

    Body: { "hobbies": ["palestra", "streaming", ...] }
    Le categorie vengono generate via lookup table statica (categories_from_hobbies)
    senza chiamate AI — l'AI per categorie viene usata in futuro su dati reali.
    """
    store = _store()
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    hobbies: list[str] = body.get("hobbies", [])

    user = _get_user_by_chat_id(chat_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    from src.workspace_bootstrapper import categories_from_hobbies
    categories = categories_from_hobbies(hobbies)

    try:
        if user.storage_backend == "postgres":
            db_session = store.Session()
            storage = PostgresStorage(session=db_session, user_id=chat_id)
            created = bootstrap_lifestyle_categories(storage, categories)
            db_session.commit()
        else:
            notion_client = NotionFinanceClient(
                api_key=user.notion_access_token,
                categories_db_id=user.categories_db_id,
            )
            storage = NotionStorage(notion_client)
            created = bootstrap_lifestyle_categories(storage, categories)
    except Exception as e:
        logger.error("Errore bootstrap lifestyle categories: %s", e)
        created = []

    store.complete_onboarding(chat_id)
    analytics.track(chat_id, "onboarding_completed", {"platform": "web", "hobbies": hobbies})
    return jsonify({"status": "ok", "categories_created": created})


@setup_bp.route("/api/onboarding/age-confirm", methods=["POST"])
def api_onboarding_age_confirm():
    """Registra l'attestazione età 18+ dell'utente (D.Lgs. 101/2018)."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    if not body.get("confirmed", False):
        return jsonify({"error": "Age not confirmed"}), 403
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    _store().set_age_attestation(chat_id, ip_address=ip, platform="web")
    return jsonify({"status": "ok"})
