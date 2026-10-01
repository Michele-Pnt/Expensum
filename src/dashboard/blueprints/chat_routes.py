"""API Chat — interfaccia conversazionale stile Telegram per la web app: parsing
LLM multi-transazione, conferma, trascrizione voce, OCR scontrino, cronologia,
bottoni spesa rapida.

Blueprint leaf: legge lo store condiviso via `current_app.config["STORE"]`, mai
import diretto di `app.py`/`factory.py` (nessun ciclo).
"""
from __future__ import annotations

import asyncio
import difflib
import logging
import os
from datetime import date, datetime, timedelta

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func

from config import Config
from src import analytics
from src.ai_improvement import capture_quality_sample
from src.dashboard.auth import _get_user_by_chat_id, _resolve_request_chat_id
from src.dashboard.blueprints.goals_routes import _complete_reached_goals_safe
from src.dashboard.storage import (
    _build_financial_storage,
    _get_storage_for_chat,
    _pg_or_401,
    _QuickExpensesStorageError,
)
from src.report_schema import render_preview_text
from src.storage.base import FinancialStorage
from src.storage.postgres_storage import PostgresStorage
from src.telegram_client import TelegramClient

logger = logging.getLogger(__name__)

chat_bp = Blueprint("chat", __name__)


def _store():
    return current_app.config["STORE"]


def _normalize_quick_expense_name(value: object) -> str:
    """Normalizza una descrizione per il confronto cross-storage."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).casefold()


def _quick_expense_date(value: object) -> date | None:
    """Converte le date dei backend nel solo formato utile al ranking."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _build_auto_quick_expense(chat_id: str) -> dict[str, str] | None:
    """Costruisce il bottone automatico (la spesa più frequente/recente), escludendo
    gli abbonamenti registrati — vedi anche `_fetch_custom_quick_expenses` per i
    bottoni personalizzati dall'utente. `None` se non c'è nessuna spesa idonea (il
    tipo di ritorno rende esplicito, anche nella firma, l'invariante "al massimo un
    bottone automatico" — prima era una lista che poteva solo contenere 0 o 1
    elemento, un dettaglio implicito condiviso solo col frontend)."""
    storage: FinancialStorage | None = None

    try:
        storage = _get_storage_for_chat(chat_id)
        if storage is None:
            return []
        today = date.today()
        start_date = today - timedelta(days=59)
        transactions = storage.fetch_all_transactions(start_date, today)
        subscriptions = storage.fetch_subscriptions()
        accounts = storage.fetch_accounts()
    except Exception:
        logger.error(
            "quick_expenses_storage_error",
            exc_info=True,
            extra={
                "domain": "app",
                "event": "quick_expenses_storage_error",
                "meta": {"chat_id": chat_id},
            },
        )
        raise _QuickExpensesStorageError from None
    finally:
        if storage is not None:
            storage.close()

    subscription_names = {
        normalized
        for subscription in subscriptions
        if (normalized := _normalize_quick_expense_name(subscription.get("name")))
    }
    account_names = {
        str(account["id"]): account["name"]
        for account in accounts
        if account.get("id") is not None
        and isinstance(account.get("name"), str)
        and account["name"].strip()
    }
    grouped: dict[str, dict] = {}

    for transaction in transactions:
        name = transaction.get("name")
        # Raggruppa per la voce di spesa normalizzata (metadato di aggregazione,
        # es. "coca"/"coca cola" -> stesso bottone) invece che per il nome grezzo
        # casefold-ato: due modi diversi di scrivere la stessa spesa devono produrre
        # UN bottone, non due mezzo-pieni che non raggiungono mai il conteggio utile.
        # Fallback sul nome grezzo se `normalized_name` manca (backend che non lo
        # popola, es. dato storico pre-feature su Notion) — mai mostrare la forma
        # minuscola/casefold come etichetta, quella serve solo per raggruppare.
        display_name = transaction.get("normalized_name") or name
        group_key = _normalize_quick_expense_name(display_name)
        account_id = transaction.get("account_id")
        transaction_date = _quick_expense_date(transaction.get("date"))
        if (
            not group_key
            or group_key in subscription_names
            or account_id is None
            or transaction_date is None
        ):
            continue

        account_id_str = str(account_id)
        account_name = account_names.get(account_id_str)
        if account_name is None:
            continue

        category = transaction.get("category") or ""
        current = grouped.get(group_key)
        if current is None:
            grouped[group_key] = {
                "count": 1,
                "date": transaction_date,
                "name": " ".join(display_name.split()),
                "category": category,
                "account_id": account_id_str,
                "account_name": account_name,
            }
            continue

        current["count"] += 1
        if transaction_date > current["date"]:
            current.update(
                date=transaction_date,
                name=" ".join(display_name.split()),
                category=category,
                account_id=account_id_str,
                account_name=account_name,
            )

    if not grouped:
        return None
    top = max(grouped.values(), key=lambda item: (item["count"], item["date"].toordinal()))
    return {
        "label": top["name"],
        "name": top["name"],
        "category": top["category"],
        "account_id": top["account_id"],
        "account_name": top["account_name"],
        "source": "auto",
    }


def _fetch_custom_quick_expenses(chat_id: str) -> list[dict[str, object]]:
    """Bottoni spesa rapida creati manualmente dall'utente (vedi QuickExpenseShortcut).

    A differenza del bottone automatico, non svaniscono se l'utente smette di
    registrare quella spesa: restano finché non li cancella esplicitamente.
    """
    from src.storage.models import Account, QuickExpenseShortcut, UserCategory

    with _store().Session() as s:
        _, err = _pg_or_401(s, chat_id)
        if err:
            return []
        rows = (
            s.query(QuickExpenseShortcut, UserCategory, Account)
            .outerjoin(UserCategory, UserCategory.id == QuickExpenseShortcut.category_id)
            .outerjoin(Account, Account.id == QuickExpenseShortcut.account_id)
            .filter(QuickExpenseShortcut.user_id == chat_id)
            .order_by(QuickExpenseShortcut.position, QuickExpenseShortcut.created_at)
            .all()
        )
        return [
            {
                "id": shortcut.id,
                "label": shortcut.name,
                "name": shortcut.name,
                "category": cat.name if cat else "",
                "account_id": str(acc.id) if acc else None,
                "account_name": acc.name if acc else None,
                "source": "custom",
            }
            for shortcut, cat, acc in rows
        ]


@chat_bp.route("/api/chat/quick-expenses/custom", methods=["POST"])
def api_chat_quick_expenses_custom_create():
    """Crea un bottone spesa rapida personalizzato — campi scelti dall'utente."""
    from src.storage.models import QuickExpenseShortcut

    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Il nome è obbligatorio"}), 400
    if len(name) > 60:
        return jsonify({"error": "Il nome non può superare i 60 caratteri"}), 400

    with _store().Session() as s:
        _, err = _pg_or_401(s, chat_id)
        if err:
            return err
        try:
            category_id = int(data["category_id"]) if data.get("category_id") else None
            account_id = int(data["account_id"]) if data.get("account_id") else None
        except (TypeError, ValueError):
            return jsonify({"error": "category_id/account_id non validi"}), 400
        max_position = s.query(func.max(QuickExpenseShortcut.position)).filter(
            QuickExpenseShortcut.user_id == chat_id
        ).scalar()
        shortcut = QuickExpenseShortcut(
            user_id=chat_id, name=name, category_id=category_id, account_id=account_id,
            position=(max_position or 0) + 1,
        )
        s.add(shortcut)
        s.commit()
        return jsonify({"id": shortcut.id}), 201


@chat_bp.route("/api/chat/quick-expenses/custom/reorder", methods=["PUT"])
def api_chat_quick_expenses_custom_reorder():
    """Salva il nuovo ordine dopo un tocca-e-trascina in chat.

    `order` è la lista completa degli id personalizzati nel nuovo ordine (l'automatico
    non ne fa parte, resta sempre primo lato frontend). Id che non appartengono
    all'utente vengono ignorati silenziosamente, non sollevano errore — evita che un
    id stantio (es. cancellato da un'altra tab nel frattempo) blocchi il riordino
    degli altri.
    """
    from src.storage.models import QuickExpenseShortcut

    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json or {}
    order = data.get("order")
    if not isinstance(order, list):
        return jsonify({"error": "'order' deve essere una lista di id"}), 400

    with _store().Session() as s:
        _, err = _pg_or_401(s, chat_id)
        if err:
            return err
        owned_ids = {
            row.id for row in s.query(QuickExpenseShortcut.id).filter(
                QuickExpenseShortcut.user_id == chat_id
            ).all()
        }
        for position, shortcut_id in enumerate(order):
            if shortcut_id not in owned_ids:
                continue
            s.query(QuickExpenseShortcut).filter_by(id=shortcut_id, user_id=chat_id).update(
                {"position": position}
            )
        s.commit()
        return jsonify({"ok": True})


@chat_bp.route("/api/chat/quick-expenses/custom/<int:shortcut_id>", methods=["DELETE"])
def api_chat_quick_expenses_custom_delete(shortcut_id: int):
    """Cancella un bottone spesa rapida personalizzato — solo se appartiene all'utente."""
    from src.storage.models import QuickExpenseShortcut

    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    with _store().Session() as s:
        _, err = _pg_or_401(s, chat_id)
        if err:
            return err
        row = s.query(QuickExpenseShortcut).filter_by(id=shortcut_id, user_id=chat_id).first()
        if not row:
            return jsonify({"error": "Non trovato"}), 404
        s.delete(row)
        s.commit()
        return jsonify({"ok": True})


# --- DEBITO TECNICO — proprietà futura: Piano A -----------------------------
# Duplicata identica in bot.py:_resolve_account_hint. Il piano di refactor
# generale prevede che Piano A la estragga in src/application/account_matching.py
# (funzione pubblica resolve_account_hint) e che questo modulo la sostituisca con:
#     from src.application.account_matching import resolve_account_hint
# Piano B NON crea src/application/account_matching.py (fuori dal proprio
# perimetro) e NON sposta questa funzione altrove (es. in un nuovo modulo
# condiviso sotto src/dashboard/): farlo creerebbe un secondo punto di verità
# che confliggerebbe con l'ownership futura di Piano A. Fino a quel momento
# resta qui, invariata riga per riga rispetto alla versione originale di
# app.py, per rendere la futura sostituzione un diff a una riga (import al
# posto della definizione).
# -----------------------------------------------------------------------------
def _resolve_account_hint(hint: str | None, accounts: list[dict]) -> dict | None:
    """Risolve un nome conto libero (hint estratto dall'NLP) su un conto reale dell'utente.

    Stessa logica di `_resolve_account_hint` in bot.py: match esatto case-insensitive,
    poi fuzzy match (soglia 0.6) sui nomi conto. None se non menzionato o senza match.
    """
    if not hint:
        return None
    hint_low = hint.strip().lower()
    for acc in accounts:
        if acc["name"].strip().lower() == hint_low:
            return acc
    names_low = [a["name"].strip().lower() for a in accounts]
    matches = difflib.get_close_matches(hint_low, names_low, n=1, cutoff=0.6)
    if matches:
        return next(a for a in accounts if a["name"].strip().lower() == matches[0])
    return None


def _chat_parse_text(
    chat_id: str, text: str, skip_length_check: bool = False, input_method: str = "text",
) -> tuple[list[dict] | None, dict | None, str]:
    """Valida, sanitizza e lancia il parsing LLM (multi-transazione) su un messaggio testuale.

    Ritorna (results, usage, error_reply). Se error_reply è non-None il chiamante
    deve restituire un errore al client senza procedere. `results` è una lista di
    transazioni rilevate (può contenerne più di una, es. scontrino con più voci).
    skip_length_check=True per testo OCR (generato dal sistema, non digitato dall'utente).
    input_method taggato nel ledger token: 'text' (default, chat scritta),
    'voice' (dopo trascrizione) o 'photo' (dopo OCR scontrino) — impostato dal
    chiamante, che sa da quale endpoint (/api/chat/message|voice|photo) proviene.
    """
    from src.expense_parser import ExpenseParser
    from src.rate_limiter import is_rate_limited

    store = _store()

    # Validazione lunghezza — non applicata a testo OCR (scontrini possono essere lunghi)
    if not skip_length_check and len(text) > Config.MAX_MESSAGE_LEN:
        return None, None, f"⚠️ Messaggio troppo lungo! Massimo {Config.MAX_MESSAGE_LEN} caratteri."

    # Rate limiting
    if is_rate_limited(chat_id, max_messages=Config.MAX_MESSAGES_PER_MINUTE):
        return None, None, "⏳ Stai inviando troppi messaggi. Attendi qualche secondo e riprova."

    # Token check
    try:
        plan = store.get_user_plan(chat_id)
        tokens_remaining = plan.get("tokens_remaining", 0)
        TEXT_COST = 800
        if plan.get("plan_type") != "pro" and tokens_remaining < TEXT_COST:
            return None, None, "🔒 Hai esaurito i token mensili. Passa al piano Pro o attendi il rinnovo."
    except Exception:
        pass  # best-effort: non bloccare per errori di quota

    # Sanitizzazione input — difesa da prompt injection
    safe_input = f"[INIZIO INPUT UTENTE]\n{text}\n[FINE INPUT UTENTE]"

    # Carica categorie dal backend corretto
    categories: list[str] = []
    income_categories: list[str] = []
    income_category_descriptions: dict[str, str] = {}
    category_descriptions: dict[str, str] = {}
    try:
        user = _get_user_by_chat_id(chat_id)
        if user.storage_backend == "postgres":
            with store.Session() as s:
                storage = _build_financial_storage(user, pg_session=s)
                categories_raw = storage.get_categories()
                categories = [c["name"] for c in categories_raw if c.get("name")]
                income_categories_raw = storage.get_income_categories()
                income_categories = [c["name"] for c in income_categories_raw]
                income_category_descriptions = {
                    c["name"]: c["description_summary"]
                    for c in income_categories_raw if c.get("description_summary")
                }
        else:
            storage = _build_financial_storage(user)
            categories_raw = storage.get_categories()
            categories = [c["name"] for c in categories_raw if c.get("name")]
            income_categories_raw = storage.get_income_categories()
            income_categories = [c["name"] for c in income_categories_raw]
            income_category_descriptions = {
                c["name"]: c["description_summary"]
                for c in income_categories_raw if c.get("description_summary")
            }
        category_descriptions = {
            c["name"]: c["description_summary"]
            for c in categories_raw if c.get("name") and c.get("description_summary")
        }
    except Exception:
        pass

    # Parsing LLM (multi-transazione: un messaggio può contenere più spese/entrate)
    try:
        parser = ExpenseParser(
            categories=categories, category_descriptions=category_descriptions,
            income_categories=income_categories,
            income_category_descriptions=income_category_descriptions,
        )
        results, usage = parser.parse_multi_with_usage(safe_input, chat_id, when=datetime.now())
    except Exception as e:
        logger.exception("Errore ExpenseParser chat: %s", e)
        return None, None, "⚠️ Errore interno durante il parsing. Riprova."

    # Token tracking (best-effort)
    if usage:
        try:
            import uuid
            store.finalize_llm_usage(
                chat_id=chat_id,
                request_key=str(uuid.uuid4()),
                operation="chat_parse",
                provider=usage.get("provider", "unknown"),
                model=usage.get("model", "unknown"),
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                input_method=input_method,
            )
        except Exception:
            pass

    # NB: la categorizzazione adattiva NON va eseguita qui. Il chiamante
    # (_build_chat_parse_result) la applica una volta sola su ogni transazione e ne
    # propaga anche `awaiting_confirmation` al client. Tracciarla anche qui faceva
    # girare il matcher due volte per la stessa spesa: la seconda passata riceveva
    # la categoria già riscritta (il fallback "Altro"), quindi non chiedeva mai
    # conferma di creare la categoria dedicata, e ogni spesa contava doppio verso
    # la soglia di promozione.
    return results, usage, ""


def _build_parse_reply(result: dict, from_name: str | None = None, to_name: str | None = None) -> tuple[str, dict]:
    """Costruisce il testo di preview e il dict parsed da mandare al client."""
    parsed_type = result.get("type", "expense")
    amount_str = f"€{result['amount']:.2f}" if result.get("amount") else "importo non specificato"
    date_obj = result.get("date")
    date_str = date_obj.strftime("%d/%m/%Y") if date_obj else "oggi"

    if parsed_type == "expense":
        cat = result.get("category") or "Altro"
        name = result.get("name") or "Spesa"
        reply = f"Ho interpretato **{name}** di {amount_str} nella categoria _{cat}_ ({date_str}). Confermi?"
    elif parsed_type == "transfer":
        name = result.get("name") or "Trasferimento"
        reply = (
            f"📝 Nuovo trasferimento riconosciuto:\n\n"
            f"💰 Importo: **{amount_str}**\n"
            f"🏦 Da: **{from_name or '—'}**\n"
            f"🏦 A: **{to_name or '—'}**\n"
            f"📝 Descrizione: **{name}**\n\nConfermi?"
        )
    else:
        income_type = result.get("income_category") or result.get("income_type") or "Entrata"
        name = result.get("name") or "Entrata"
        reply = f"Ho interpretato **{name}** ({income_type}) di {amount_str} ({date_str}). Confermi?"

    parsed = {
        "type": parsed_type,
        "amount": result.get("amount"),
        "category": result.get("category"),
        "income_type": result.get("income_type"),
        "income_category": result.get("income_category"),
        "name": result.get("name"),
        "date": str(result.get("date")),
    }
    return reply, parsed


def _build_transaction_payload(
    result: dict, accounts: list[dict], categories: list[str], income_categories: list[str],
) -> dict:
    """Arricchisce un item parsato con conti/categorie e i flag di step successivo.

    Replica le domande sequenziali del bot Telegram: importo mancante, risoluzione
    conti (con hint LLM) per i trasferimenti, e blocco se mancano conti sufficienti.
    I conti (e per i trasferimenti gli hint risolti) sono sempre inclusi nel `parsed`,
    anche quando manca l'importo, così il frontend non deve rifare un giro di rete
    quando l'utente completa l'importo in un messaggio successivo.
    """
    parsed_type = result.get("type", "expense")
    amount_missing = result.get("amount") is None

    if parsed_type == "transfer":
        from_match = _resolve_account_hint(result.get("from_account"), accounts)
        to_match = _resolve_account_hint(result.get("to_account"), accounts)
        if from_match and to_match and str(from_match["id"]) == str(to_match["id"]):
            to_match = None
        from_name = from_match["name"] if from_match else None
        to_name = to_match["name"] if to_match else None

        reply, parsed = _build_parse_reply(result, from_name=from_name, to_name=to_name)
        parsed["accounts"] = accounts
        parsed["resolved_from_account_id"] = from_match["id"] if from_match else None
        parsed["resolved_from_account_name"] = from_match["name"] if from_match else None
        parsed["resolved_to_account_id"] = to_match["id"] if to_match else None
        parsed["resolved_to_account_name"] = to_match["name"] if to_match else None

        if amount_missing:
            return {
                "type": parsed_type,
                "reply": "📝 Quanto vuoi trasferire? Scrivi solo l'importo (es. 100).",
                "parsed": parsed,
                "needs_amount": True,
                "awaiting_confirm": False,
            }
        if len(accounts) < 2:
            return {
                "type": parsed_type,
                "reply": (
                    "🏦 Ti servono almeno due conti per fare un trasferimento.\n\n"
                    "Aggiungine uno nella tab \"Conti\" del tuo spazio."
                ),
                "parsed": parsed,
                "needs_second_account": True,
                "awaiting_confirm": False,
            }
        # Come bot.py:_advance_transfer_flow — se un conto non è stato risolto dagli hint
        # LLM, si chiede via picker PRIMA di mostrare il riepilogo di conferma.
        if not from_match:
            return {
                "type": parsed_type,
                "reply": "🏦 Da quale conto vuoi spostare i soldi?",
                "parsed": parsed,
                "needs_account_pick": "from",
                "awaiting_confirm": False,
            }
        if not to_match:
            return {
                "type": parsed_type,
                "reply": "🏦 Su quale conto vuoi spostare i soldi?",
                "parsed": parsed,
                "needs_account_pick": "to",
                "awaiting_confirm": False,
            }
        return {"type": parsed_type, "reply": reply, "parsed": parsed, "awaiting_confirm": True}

    reply, parsed = _build_parse_reply(result)
    parsed["accounts"] = accounts
    if parsed_type == "expense":
        parsed["categories"] = categories
    elif parsed_type == "income":
        # Stesso campo `categories` del ramo spesa: il frontend lo interpreta in base
        # a `parsed.type`, così il picker può restare generico (vedi ParsedData/model.ts).
        parsed["categories"] = income_categories

    if amount_missing:
        return {
            "type": parsed_type,
            "reply": "📝 Non ho capito l'importo. Prova a ridirmelo, scrivendo solo il numero (es. 20 o 20,50).",
            "parsed": parsed,
            "needs_amount": True,
            "awaiting_confirm": False,
        }
    return {"type": parsed_type, "reply": reply, "parsed": parsed, "awaiting_confirm": True}


def _build_chat_parse_result(chat_id: str, results: list[dict] | None, error_reply: str) -> dict:
    """Costruisce il payload JSON-able per una risposta di parsing chat (0+ transazioni).

    Condiviso da /api/chat/message, /api/chat/voice, /api/chat/photo: tutti e tre
    lanciano lo stesso parsing multi-transazione e devono offrire la stessa UX
    (conti, categorie, trasferimenti) indipendentemente dal canale di input.
    """
    store = _store()

    if error_reply:
        try:
            store.log_message(chat_id, source="webapp", role="bot", text=error_reply)
        except Exception:
            pass
        return {"ok": False, "type": "error", "reply": error_reply, "saved": False}

    if not results:
        unknown_reply = "Non ho riconosciuto una transazione nel tuo messaggio. Prova con qualcosa come «ho speso 20€ al supermercato» 🛒"
        try:
            store.log_message(chat_id, source="webapp", role="bot", text=unknown_reply)
        except Exception:
            pass
        return {"ok": True, "type": "unknown", "reply": unknown_reply, "saved": False}

    accounts: list[dict] = []
    categories: list[str] = []
    income_categories: list[str] = []
    try:
        user = _get_user_by_chat_id(chat_id)
        if user.storage_backend == "postgres":
            with store.Session() as s:
                storage = _build_financial_storage(user, pg_session=s)
                accounts = storage.fetch_accounts()
                categories = storage.get_category_names()
                income_categories = storage.get_income_category_names()
        else:
            storage = _build_financial_storage(user)
            accounts = storage.fetch_accounts()
            categories = storage.get_category_names()
            income_categories = storage.get_income_category_names()
    except Exception as e:
        logger.exception("Errore fetch accounts/categorie chat: %s", e)

    if not accounts:
        no_account_reply = (
            "🏦 Non hai ancora nessun conto su Expensum, quindi non posso registrare la transazione.\n\n"
            "Aggiungine uno nella tab \"Conti\" del tuo spazio, poi rimanda il messaggio."
        )
        try:
            store.log_message(chat_id, source="webapp", role="bot", text=no_account_reply)
        except Exception:
            pass
        return {"ok": False, "type": "no_account", "reply": no_account_reply, "saved": False, "setup_path": "/spazio"}

    # Categorizzazione adattiva — stessa logica del bot Telegram (bot.py::_process_expense_text),
    # condivisa via src/category_matcher.py: dopo N ricorrenze chiede conferma prima di
    # creare una categoria reale invece di promuovere silenziosamente.
    category_promotion_by_index: dict[int, dict] = {}
    expense_results = [(i, r) for i, r in enumerate(results) if r.get("type") == "expense" and r.get("category")]
    if expense_results:
        from src import category_matcher
        known_categories = store.get_user_category_names(chat_id)
        with store.Session() as cm_session:
            for i, r in expense_results:
                match_result = category_matcher.evaluate_and_track(
                    cm_session, storage, store, chat_id, r.get("name") or "", r["category"], known_categories,
                )
                r["category"] = match_result.category_name
                if match_result.awaiting_confirmation:
                    category_promotion_by_index[i] = {
                        "candidate_id": match_result.candidate_id,
                        "suggested_name": match_result.suggested_name,
                    }

    transactions = [_build_transaction_payload(r, accounts, categories, income_categories) for r in results]
    for i, tx in enumerate(transactions):
        if i in category_promotion_by_index:
            tx["category_promotion"] = category_promotion_by_index[i]
        try:
            store.log_message(chat_id, source="webapp", role="bot", text=tx["reply"], metadata=tx["parsed"])
        except Exception:
            pass

    return {"ok": True, "transactions": transactions}


@chat_bp.route("/api/chat/quick-expenses", methods=["GET"])
def api_chat_quick_expenses():
    """Restituisce i suggerimenti frequenti per il composer della chat."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        auto = _build_auto_quick_expense(chat_id)
    except _QuickExpensesStorageError:
        return jsonify({"error": "Impossibile caricare i suggerimenti"}), 500
    quick_expenses = ([auto] if auto else []) + _fetch_custom_quick_expenses(chat_id)
    return jsonify({"quick_expenses": quick_expenses})


@chat_bp.route("/api/chat/message", methods=["POST"])
def api_chat_message():
    """Parse-only: interpreta il messaggio via LLM (anche multi-transazione), non salva."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Testo vuoto"}), 400

    results, _usage, error_reply = _chat_parse_text(chat_id, text)

    try:
        _store().log_message(chat_id, source="webapp", role="user", text=text)
    except Exception:
        pass

    return jsonify(_build_chat_parse_result(chat_id, results, error_reply))


@chat_bp.route("/api/chat/confirm", methods=["POST"])
def api_chat_confirm():
    """Salva la transazione parsata dopo conferma esplicita dell'utente.

    Il conto (o i due conti, per un trasferimento) va scelto esplicitamente dal
    frontend — niente più default silenzioso sul primo conto dell'utente, per
    parità con il bot Telegram (bot.py:2472-2515, 2517-2549).
    """
    store = _store()
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    parsed = data.get("parsed") or {}
    parsed_type = parsed.get("type", "expense")
    category_override = data.get("category")
    # Il frontend lo imposta quando l'utente ha usato il picker "Cambia categoria"
    # prima di confermare (spesa o entrata) — vedi model.ts::applyCategorySelection.
    category_was_corrected = bool(data.get("category_was_corrected"))
    account_id = data.get("account_id")
    from_account_id = data.get("from_account_id")
    to_account_id = data.get("to_account_id")

    if not parsed.get("amount"):
        return jsonify({"error": "Dati transazione mancanti"}), 400

    if parsed_type == "transfer":
        if not from_account_id or not to_account_id:
            return jsonify({"error": "Conto di origine/destinazione mancante"}), 400
        if str(from_account_id) == str(to_account_id):
            return jsonify({"error": "Il conto di destinazione deve essere diverso da quello di origine"}), 400
    elif not account_id:
        return jsonify({"error": "Conto mancante"}), 400

    user = _get_user_by_chat_id(chat_id)
    if not user:
        return jsonify({"error": "Utente non trovato"}), 404

    # Converti la data da stringa a oggetto date (il parser la serializza come str)
    raw_date = parsed.get("date")
    try:
        tx_date = datetime.strptime(str(raw_date).split("T")[0], "%Y-%m-%d").date()
    except (ValueError, AttributeError, TypeError):
        tx_date = date.today()

    # Controlla se è la prima spesa (per first_expense_tracked) prima di salvare
    _is_first_expense = False
    try:
        if user.storage_backend == "postgres" and parsed_type == "expense":
            # Sessione bindata al tenant per la RLS (expenses è protetta).
            with store._user_session(chat_id) as _s:
                from src.storage.models import Expense as _ExpenseModel
                _count = _s.query(_ExpenseModel).filter_by(user_id=chat_id).count()
                _is_first_expense = _count == 0
    except Exception:
        pass

    def _save(storage) -> None:
        if parsed_type == "expense":
            storage.create_expense(
                expense_date=tx_date,
                amount=float(parsed.get("amount") or 0),
                category_name=category_override or parsed.get("category") or "Altro",
                name=parsed.get("name") or "Spesa",
                account_id=account_id,
            )
        elif parsed_type == "transfer":
            storage.create_transfer(
                transfer_date=tx_date,
                amount=float(parsed.get("amount") or 0),
                from_account_id=from_account_id,
                to_account_id=to_account_id,
                name=parsed.get("name") or "Trasferimento",
            )
        else:
            storage.create_income(
                income_date=tx_date,
                amount=float(parsed.get("amount") or 0),
                income_category_name=parsed.get("income_category") or parsed.get("income_type"),
                income_type=parsed.get("income_type") or "Stipendio",
                name=parsed.get("name") or "Entrata",
                account_id=account_id,
            )

    saved = False
    try:
        if user.storage_backend == "postgres":
            with store.Session() as s:
                storage = _build_financial_storage(user, pg_session=s)
                _save(storage)
        else:
            storage = _build_financial_storage(user)
            _save(storage)
        saved = True
    except Exception as e:
        logger.exception("Errore salvataggio transazione confermata: %s", e)

    if saved:
        input_method = data.get("input_method", "text")
        analytics.track(chat_id, "expense_tracked", {
            "input_method": input_method,
            "storage_backend": user.storage_backend,
            "transaction_type": parsed_type,
            "platform": "web",
        })
        rewards = store.record_tx_event(
            chat_id, parsed_type, input_method, "confirmed", "webapp",
            reason="category_corrected" if category_was_corrected else None,
        ) or {}
        try:
            if input_method in {"text", "voice", "ocr"}:
                capture_quality_sample(
                    store, chat_id, input_method, data, data,
                    {"provider": "mistral", "model": "small"},
                )
        except Exception as exc:
            current_app.logger.warning(
                "ai_quality_capture_failed",
                extra={
                    "domain": "usage",
                    "event": "ai_quality_capture_failed",
                    "meta": {"input_method": input_method, "error": type(exc).__name__},
                },
            )
        # Le chiavi della streak ci sono solo a ciclo completato; gli achievement
        # non si notificano da qui, li mostra la webapp leggendo `unseen_unlocks`.
        if rewards.get("cycle_completed_days"):
            try:
                asyncio.run(TelegramClient(chat_id).send_report(
                    f"🎉 Hai completato {rewards['cycle_completed_days']} giorni di streak!\n"
                    f"Ti abbiamo regalato 2 settimane di Pro.\n"
                    f"La prossima streak sarà di {rewards['next_target_days']} giorni."
                ))
            except Exception as _se:
                logger.warning("Errore invio messaggio streak per %s: %s", chat_id, _se)
        # Obiettivi raggiunti: rilevati subito, non al 1° del mese. Gli sblocchi
        # arrivano al client dal prossimo /api/gamification/summary.
        _complete_reached_goals_safe(chat_id)
        if _is_first_expense:
            analytics.track(chat_id, "first_expense_tracked", {"input_method": input_method, "platform": "web"})
    else:
        analytics.track(chat_id, "expense_tracking_failed", {"reason": "save_error", "platform": "web"})
        store.record_tx_event(
            chat_id, parsed_type, data.get("input_method", "text"), "failed", "webapp",
            reason="save_error",
        )

    amount_str = f"€{float(parsed.get('amount', 0)):.2f}"
    if parsed_type == "expense":
        cat = category_override or parsed.get("category") or "Altro"
        name = parsed.get("name") or "Spesa"
        if saved:
            reply = f"✅ Ho registrato **{name}** di {amount_str} nella categoria _{cat}_."
        else:
            reply = f"⚠️ Ho interpretato **{name}** di {amount_str}, ma non sono riuscito a salvarlo. Riprova."
    elif parsed_type == "transfer":
        from_name = parsed.get("resolved_from_account_name") or "—"
        to_name = parsed.get("resolved_to_account_name") or "—"
        if saved:
            reply = f"✅ Trasferiti {amount_str} da **{from_name}** a **{to_name}**."
        else:
            reply = f"⚠️ Ho interpretato il trasferimento di {amount_str}, ma non sono riuscito a salvarlo. Riprova."
    else:
        income_type = parsed.get("income_type") or "Entrata"
        name = parsed.get("name") or "Entrata"
        if saved:
            reply = f"✅ Ho registrato **{name}** ({income_type}) di {amount_str}."
        else:
            reply = f"⚠️ Ho interpretato **{name}** di {amount_str}, ma non sono riuscito a salvarlo. Riprova."

    # Log risposta finale bot
    try:
        store.log_message(chat_id, source="webapp", role="bot", text=reply, metadata=parsed if saved else None)
    except Exception:
        pass

    return jsonify({"ok": saved, "saved": saved, "reply": reply, "is_first_expense": _is_first_expense and saved})


@chat_bp.route("/api/chat/category-confirm", methods=["POST"])
def api_chat_category_confirm():
    """Esito della richiesta di conferma categorizzazione adattiva (Sì/No).

    Stessa logica di bot.py::handle_callback per i callback catpromote_yes/catpromote_no
    — chiama le stesse funzioni condivise di src/category_matcher.py, nessuna
    duplicazione di logica tra bot Telegram e webapp.
    """
    from src import category_matcher

    store = _store()
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    candidate_id = data.get("candidate_id")
    decision = data.get("decision")
    if not candidate_id or decision not in ("yes", "no"):
        return jsonify({"error": "Parametri mancanti"}), 400

    if decision == "no":
        with store.Session() as cm_session:
            category_matcher.decline_promotion(cm_session, int(candidate_id))
        return jsonify({"ok": True, "reply": "👍 Nessun problema, non creo la categoria."})

    user = _get_user_by_chat_id(chat_id)
    if not user:
        return jsonify({"error": "Utente non trovato"}), 404

    with store.Session() as cm_session:
        if user.storage_backend == "postgres":
            storage = _build_financial_storage(user, pg_session=cm_session)
        else:
            storage = _build_financial_storage(user)
        match_result = category_matcher.confirm_promotion(cm_session, storage, store, int(candidate_id))

    if match_result.promoted:
        reply = (
            f"✅ Categoria «{match_result.promoted_category_name}» creata! Le prossime spese simili "
            "verranno categorizzate automaticamente."
        )
    else:
        reply = (
            "⚠️ Non sono riuscito a creare la categoria in questo momento (problema temporaneo col tuo "
            "storage). Riproverò automaticamente alla prossima spesa simile."
        )
    return jsonify({"ok": bool(match_result.promoted), "reply": reply})


@chat_bp.route("/api/chat/voice", methods=["POST"])
def api_chat_voice():
    """Trascrive un messaggio vocale via Gemini e lo processa come testo."""
    from src.rate_limiter import is_rate_limited

    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    if is_rate_limited(chat_id, max_messages=Config.MAX_MESSAGES_PER_MINUTE):
        return jsonify({"ok": False, "reply": "⏳ Troppi messaggi. Attendi qualche secondo.", "saved": False})

    audio_file = request.files.get("audio")
    if not audio_file:
        return jsonify({"error": "File audio mancante"}), 400

    max_bytes = Config.MAX_FILE_SIZE_MB * 1024 * 1024
    if request.content_length and request.content_length > max_bytes:
        return jsonify({
            "ok": False,
            "reply": f"⚠️ Audio troppo grande! Limite: {Config.MAX_FILE_SIZE_MB}MB.",
            "saved": False,
        }), 413

    # Trascrizione Gemini Vertex AI
    transcribed = ""
    try:
        from google.genai import types as genai_types

        from src.vertex_ai_client import get_vertex_ai_client

        audio_bytes = audio_file.read()
        if len(audio_bytes) > max_bytes:
            return jsonify({
                "ok": False,
                "reply": f"⚠️ Audio troppo grande! Limite: {Config.MAX_FILE_SIZE_MB}MB.",
                "saved": False,
            }), 413
        if len(audio_bytes) < 100:
            return jsonify({"ok": False, "reply": "⚠️ Audio troppo corto o vuoto.", "saved": False})

        client_ai = get_vertex_ai_client()
        audio_part = genai_types.Part.from_bytes(data=audio_bytes, mime_type="audio/webm")
        response = client_ai.models.generate_content(
            model=Config.GEMINI_MODEL,
            contents=[
                "Trascrivi esattamente e parola per parola questo audio in italiano. "
                "Restituisci SOLO ed esclusivamente il testo trascritto, nient'altro.",
                audio_part,
            ],
        )
        transcribed = (response.text or "").strip()
    except Exception as e:
        logger.exception("Errore trascrizione voce chat: %s", e)
        return jsonify({"ok": False, "reply": "⚠️ Errore durante la trascrizione audio. Riprova o scrivi il messaggio.", "saved": False})

    if not transcribed:
        return jsonify({"ok": False, "reply": "⚠️ Non sono riuscito a trascrivere l'audio. Parla più chiaramente o scrivi il messaggio.", "saved": False})

    results, _usage, error_reply = _chat_parse_text(chat_id, transcribed, input_method="voice")

    user_text = f"🎤 {transcribed}"
    try:
        _store().log_message(chat_id, source="webapp", role="user", text=user_text)
    except Exception:
        pass

    payload = _build_chat_parse_result(chat_id, results, error_reply)
    payload["transcription"] = transcribed
    return jsonify(payload)


@chat_bp.route("/api/chat/photo", methods=["POST"])
def api_chat_photo():
    """Analizza un'immagine di scontrino via OCR e la processa come testo."""
    import tempfile

    from src.rate_limiter import is_rate_limited

    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    if is_rate_limited(chat_id, max_messages=Config.MAX_MESSAGES_PER_MINUTE):
        return jsonify({"ok": False, "reply": "⏳ Troppi messaggi. Attendi qualche secondo.", "saved": False})

    image_file = request.files.get("image")
    if not image_file:
        return jsonify({"error": "Immagine mancante"}), 400

    max_bytes = Config.MAX_FILE_SIZE_MB * 1024 * 1024
    if request.content_length and request.content_length > max_bytes:
        return jsonify({
            "ok": False,
            "reply": f"⚠️ Immagine troppo grande! Limite: {Config.MAX_FILE_SIZE_MB}MB.",
            "saved": False,
        }), 413

    ocr_text = ""
    try:
        from src.ocr_client import OcrClient, OCRError

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            image_file.save(tmp.name)
            tmp_path = tmp.name

        if os.path.getsize(tmp_path) > max_bytes:
            os.unlink(tmp_path)
            return jsonify({
                "ok": False,
                "reply": f"⚠️ Immagine troppo grande! Limite: {Config.MAX_FILE_SIZE_MB}MB.",
                "saved": False,
            }), 413

        try:
            ocr_text = OcrClient().extract_text_from_image(tmp_path, chat_id)
        except OCRError:
            return jsonify({"ok": False, "reply": "⚠️ Non riesco a leggere lo scontrino. Riprova con una foto più nitida e ben illuminata.", "saved": False})
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    except Exception as e:
        logger.exception("Errore OCR chat: %s", e)
        return jsonify({"ok": False, "reply": "⚠️ Errore durante l'analisi dell'immagine. Riprova.", "saved": False})

    # 🛡️ Sanitizzazione testo OCR — rimuove Unicode pericolosi e rileva injection
    from src.input_sanitizer import InjectionDetectedError, sanitize_ocr_text
    try:
        ocr_text = sanitize_ocr_text(ocr_text, chat_id)
    except InjectionDetectedError:
        _store().logout_user(chat_id)
        return jsonify({
            "ok": False,
            "reply": (
                f"🚫 Comportamento malevolo rilevato. "
                f"Il tuo account è stato disabilitato. "
                f"Per chiarimenti scrivi a: {Config.SUPPORT_EMAIL}"
            ),
            "saved": False,
            "banned": True,
        })

    results, _usage, error_reply = _chat_parse_text(chat_id, ocr_text, skip_length_check=True, input_method="photo")

    user_text = f"📷 {ocr_text[:200]}"
    try:
        _store().log_message(chat_id, source="webapp", role="user", text=user_text)
    except Exception:
        pass

    payload = _build_chat_parse_result(chat_id, results, error_reply)
    if payload.get("type") == "unknown":
        payload["reply"] = "⚠️ Ho letto il testo dello scontrino ma non ho riconosciuto una transazione. Prova a scrivere la spesa manualmente."
    return jsonify(payload)


@chat_bp.route("/api/chat/history", methods=["GET"])
def api_chat_history():
    """Ritorna la cronologia condivisa: messaggi da Telegram e web app + report."""
    store = _store()
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    limit = min(int(request.args.get("limit", 60)), 100)

    try:
        messages = store.get_chat_history(chat_id, limit=limit)

        # Arricchisce con i report salvati (appaiono inline come messaggi bot), evitando
        # doppioni per i report che hanno già un messaggio esplicito di notifica in chat
        # (weekly/monthly plan loggano un saluto con lo stesso share_token in metadata).
        try:
            already_notified_tokens = {
                m.get("metadata", {}).get("share_token")
                for m in messages
                if m.get("metadata", {}).get("share_token")
            }
            user = _get_user_by_chat_id(chat_id)
            if user:
                if user.storage_backend == "postgres":
                    with store.Session() as s:
                        pg = PostgresStorage(session=s, user_id=chat_id)
                        reports = pg.get_reports_for_user(chat_id, limit=10)
                else:
                    storage = _build_financial_storage(user)
                    reports = storage.get_reports_for_user(chat_id, limit=10)

                for r in reports:
                    if r.get("share_token") in already_notified_tokens:
                        continue
                    messages.append({
                        "id": f"report-{r.get('share_token', '')}",
                        "source": "telegram",
                        "role": "bot",
                        "text": render_preview_text(r.get("text_content") or ""),
                        "created_at": str(r.get("report_date") or r.get("created_at") or ""),
                        "metadata": {
                            "report_type": r.get("report_type"),
                            "share_token": r.get("share_token"),
                        },
                    })

                messages.sort(key=lambda m: m.get("created_at") or "", reverse=False)
                messages = messages[-limit:]
        except Exception:
            pass  # i report sono opzionali

        return jsonify({"messages": messages, "count": len(messages)})
    except Exception as e:
        logger.exception("Errore api_chat_history: %s", e)
        return jsonify({"messages": [], "count": 0})
