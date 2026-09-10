"""Spazio finanziario: conti, trasferimenti, categorie, abbonamenti, calendario,
spese, entrate. Feature Postgres-only (`_pg_or_401`), CRUD completo per la
pagina "Il mio Spazio".

Blueprint leaf: legge lo store condiviso via `current_app.config["STORE"]`, mai
import diretto di `app.py`/`factory.py` (nessun ciclo).
"""
from __future__ import annotations

import calendar as _calendar
from datetime import date, datetime

from flask import Blueprint, current_app, g, jsonify, request

from config import Config
from src.dashboard.auth import _tg_webapp_auth
from src.dashboard.budget_validation import (
    _parse_money,
    _validate_category_budgets_with_general_budget,
)
from src.dashboard.category_descriptions import _synthesize_category_description
from src.dashboard.storage import _pg_or_401

space_bp = Blueprint("space", __name__)


def _store():
    return current_app.config["STORE"]


# ── Accounts ─────────────────────────────────────────────────────────────────

@space_bp.route("/api/space/accounts", methods=["GET"])
@_tg_webapp_auth
def space_accounts_list():
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        return jsonify({"accounts": pg.fetch_accounts()})


@space_bp.route("/api/space/accounts", methods=["POST"])
@_tg_webapp_auth
def space_accounts_create():
    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Il campo 'name' è obbligatorio"}), 400
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        result = pg.create_account(
            name,
            initial_balance=float(data.get("initial_balance") or 0),
            account_type=data.get("account_type") or None,
        )
        return jsonify(result), 201


@space_bp.route("/api/space/accounts/<int:account_id>", methods=["PUT"])
@_tg_webapp_auth
def space_accounts_update(account_id: int):
    data = request.json or {}
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        result = pg.update_account(
            account_id,
            name=data.get("name") or None,
            balance=float(data["balance"]) if data.get("balance") not in (None, "") else None,
            account_type=data.get("account_type") or None,
        )
        if result is None:
            return jsonify({"error": "Conto non trovato"}), 404
        return jsonify(result)


@space_bp.route("/api/space/accounts/<int:account_id>", methods=["DELETE"])
@_tg_webapp_auth
def space_accounts_delete(account_id: int):
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        ok = pg.delete_account(account_id)
        if not ok:
            return jsonify({"error": "Conto non trovato"}), 404
        return jsonify({"status": "ok"})


# ── Transfers ────────────────────────────────────────────────────────────────

@space_bp.route("/api/space/transfers", methods=["GET"])
@_tg_webapp_auth
def space_transfers_list():
    today = date.today()
    start = request.args.get("start", date(today.year, today.month, 1).isoformat())
    end = request.args.get("end", today.isoformat())
    try:
        start_d = datetime.strptime(start, "%Y-%m-%d").date()
        end_d = datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Formato data non valido (YYYY-MM-DD)"}), 400
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        items = pg.fetch_transfers(start_d, end_d)
        for item in items:
            if hasattr(item.get("date"), "isoformat"):
                item["date"] = item["date"].isoformat()
        return jsonify({"transfers": items})


@space_bp.route("/api/space/transfers", methods=["POST"])
@_tg_webapp_auth
def space_transfers_create():
    data = request.json or {}
    try:
        amount = float(data.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"error": "Il campo 'amount' è obbligatorio ed è un numero"}), 400
    if amount <= 0:
        return jsonify({"error": "L'importo deve essere positivo"}), 400
    from_account_id = data.get("from_account_id")
    to_account_id = data.get("to_account_id")
    if not from_account_id or not to_account_id:
        return jsonify({"error": "I campi 'from_account_id' e 'to_account_id' sono obbligatori"}), 400
    if str(from_account_id) == str(to_account_id):
        return jsonify({"error": "Il conto di origine e di destinazione devono essere diversi"}), 400
    try:
        transfer_date = datetime.strptime(data.get("date") or datetime.today().strftime("%Y-%m-%d"), "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Formato data non valido (YYYY-MM-DD)"}), 400
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        try:
            result = pg.create_transfer(
                transfer_date=transfer_date,
                amount=amount,
                from_account_id=from_account_id,
                to_account_id=to_account_id,
                name=(data.get("name") or "").strip() or None,
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if hasattr(result.get("date"), "isoformat"):
            result["date"] = result["date"].isoformat()
        return jsonify(result), 201


@space_bp.route("/api/space/transfers/<int:transfer_id>", methods=["PUT"])
@_tg_webapp_auth
def space_transfers_update(transfer_id: int):
    data = request.json or {}
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        transfer_date = None
        if data.get("date"):
            try:
                transfer_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
            except ValueError:
                return jsonify({"error": "Formato data non valido (YYYY-MM-DD)"}), 400
        try:
            result = pg.update_transfer(
                transfer_id,
                name=(data.get("name") or "").strip() or None if "name" in data else None,
                amount=float(data["amount"]) if data.get("amount") not in (None, "") else None,
                date=transfer_date,
                from_account_id=data.get("from_account_id") or None,
                to_account_id=data.get("to_account_id") or None,
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if result is None:
            return jsonify({"error": "Trasferimento non trovato"}), 404
        if hasattr(result.get("date"), "isoformat"):
            result["date"] = result["date"].isoformat()
        return jsonify(result)


@space_bp.route("/api/space/transfers/<int:transfer_id>", methods=["DELETE"])
@_tg_webapp_auth
def space_transfers_delete(transfer_id: int):
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        ok = pg.delete_transfer(transfer_id)
        if not ok:
            return jsonify({"error": "Trasferimento non trovato"}), 404
        return jsonify({"status": "ok"})


# ── Categories ────────────────────────────────────────────────────────────────

@space_bp.route("/api/space/categories", methods=["GET"])
@_tg_webapp_auth
def space_categories_list():
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        return jsonify({"categories": pg.fetch_categories_full()})


@space_bp.route("/api/space/categories/suggestions", methods=["GET"])
@_tg_webapp_auth
def space_categories_suggestions():
    """Piano di budget mensile costruito a partire dal reddito e dall'obiettivo.

    Sostituisce la vecchia media delle spese: la risposta contiene anche reddito
    stimato, risparmio target, costi fissi e quota distribuibile, così la UI può
    spiegare *perché* propone quei numeri invece di mostrarli e basta.
    """
    from src.budget_planner import build_budget_plan

    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        plan = build_budget_plan(pg)
        dismissed = pg.get_dismissed_budget_suggestions()

    payload = plan.to_dict()
    payload["categories"] = [
        c for c in payload["categories"] if c["category_id"] not in dismissed
    ]
    # `suggestions` resta per compatibilità con il client attuale, che si aspetta
    # una mappa nome → importo.
    payload["suggestions"] = {c["name"]: c["proposed_budget"] for c in payload["categories"]}
    return jsonify(payload)


@space_bp.route("/api/space/categories/<int:cat_id>/accept-suggestion", methods=["POST"])
@_tg_webapp_auth
def space_categories_accept_suggestion(cat_id: int):
    data = request.json or {}
    suggested = data.get("suggested_budget")
    if suggested is None:
        return jsonify({"error": "suggested_budget obbligatorio"}), 400
    budget, error = _parse_money(suggested, "suggested_budget")
    if error:
        return error
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        category = next(
            (item for item in pg.fetch_categories_full(include_archived=False) if item["id"] == cat_id),
            None,
        )
        if category is None:
            return jsonify({"error": "Categoria non trovata"}), 404
        budget_error = _validate_category_budgets_with_general_budget(
            g.chat_id,
            category["name"],
            budget,
        )
        if budget_error:
            return budget_error
        result = pg.update_category(cat_id, monthly_budget=budget)
        return jsonify(result)


@space_bp.route("/api/space/categories/<int:cat_id>/dismiss-suggestion", methods=["POST"])
@_tg_webapp_auth
def space_categories_dismiss_suggestion(cat_id: int):
    """Rifiuta un suggerimento in modo persistente.

    Prima il rifiuto viveva solo nello stato React e il suggerimento ricompariva
    al reload della pagina.
    """
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        if not pg.dismiss_budget_suggestion(cat_id):
            return jsonify({"error": "Categoria non trovata"}), 404
        return jsonify({"status": "ok"})


_CATEGORY_DESCRIPTION_MAX_LEN = 500


@space_bp.route("/api/space/categories", methods=["POST"])
@_tg_webapp_auth
def space_categories_create():
    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Il campo 'name' è obbligatorio"}), 400
    description = (data.get("description") or "").strip() or None
    if description and len(description) > _CATEGORY_DESCRIPTION_MAX_LEN:
        return jsonify({"error": f"Descrizione troppo lunga (max {_CATEGORY_DESCRIPTION_MAX_LEN} caratteri)"}), 400
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        # Lo unique constraint (user_id, name) vale anche sulle archiviate: se il nome
        # collide con una categoria archiviata, la risposta indica che si può
        # ripristinare invece di lasciare l'utente davanti a un 409 inspiegabile.
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
        monthly_budget, budget_error = _parse_money(data.get("monthly_budget"), "monthly_budget")
        if budget_error:
            return budget_error
        coherence_error = _validate_category_budgets_with_general_budget(
            g.chat_id,
            name,
            monthly_budget,
        )
        if coherence_error:
            return coherence_error
        description_summary = _synthesize_category_description(description) if description else None
        result = pg.create_category(
            name, monthly_budget=monthly_budget,
            description=description, description_summary=description_summary,
        )
        return jsonify(result), 201


@space_bp.route("/api/space/categories/<int:cat_id>", methods=["PUT"])
@_tg_webapp_auth
def space_categories_update(cat_id: int):
    data = request.json or {}
    description = data.get("description")
    if description is not None:
        description = description.strip() or None
        if description and len(description) > _CATEGORY_DESCRIPTION_MAX_LEN:
            return jsonify({"error": f"Descrizione troppo lunga (max {_CATEGORY_DESCRIPTION_MAX_LEN} caratteri)"}), 400
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        monthly_budget, budget_error = _parse_money(data.get("monthly_budget"), "monthly_budget")
        if budget_error:
            return budget_error
        current_category = next(
            (item for item in pg.fetch_categories_full(include_archived=False) if item["id"] == cat_id),
            None,
        )
        if current_category is None:
            return jsonify({"error": "Categoria non trovata"}), 404
        next_name = data.get("name") or current_category["name"]
        coherence_error = _validate_category_budgets_with_general_budget(
            g.chat_id,
            next_name,
            monthly_budget,
        )
        if coherence_error:
            return coherence_error
        description_summary = _synthesize_category_description(description) if description else None
        result = pg.update_category(
            cat_id, name=data.get("name") or None, monthly_budget=monthly_budget,
            description=description, description_summary=description_summary,
        )
        return jsonify(result)


def _is_fallback_category(pg, cat_id: int) -> bool:
    """La categoria di fallback ("Altro") non è né archiviabile né cancellabile.

    È la destinazione di ogni riassegnazione e il ripiego del matcher: senza di lei
    il salvataggio di una spesa non categorizzabile non avrebbe dove atterrare.
    """
    for cat in pg.fetch_categories_full(include_archived=True):
        if cat["id"] == cat_id:
            return cat["name"].lower() == Config.CATEGORY_FALLBACK_NAME.lower()
    return False


@space_bp.route("/api/space/categories/<int:cat_id>/usage")
@_tg_webapp_auth
def space_categories_usage(cat_id: int):
    """Conteggio dei record collegati, per una conferma informata prima di cancellare."""
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        usage = pg.get_category_usage(cat_id)
        if usage is None:
            return jsonify({"error": "Categoria non trovata"}), 404
        return jsonify({
            "usage": usage,
            "total": sum(usage.values()),
            "is_fallback": _is_fallback_category(pg, cat_id),
        })


@space_bp.route("/api/space/categories/<int:cat_id>/archive", methods=["POST"])
@_tg_webapp_auth
def space_categories_archive(cat_id: int):
    """Archivia una categoria: sparisce dalle scelte future, lo storico resta intatto."""
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        if _is_fallback_category(pg, cat_id):
            return jsonify({
                "error": f"La categoria «{Config.CATEGORY_FALLBACK_NAME}» non può essere archiviata"
            }), 400
        result = pg.set_category_archived(cat_id, True)
        if result is None:
            return jsonify({"error": "Categoria non trovata"}), 404
        return jsonify(result)


@space_bp.route("/api/space/categories/<int:cat_id>/unarchive", methods=["POST"])
@_tg_webapp_auth
def space_categories_unarchive(cat_id: int):
    """Ripristina una categoria archiviata."""
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        category = next(
            (item for item in pg.fetch_categories_full(include_archived=True) if item["id"] == cat_id),
            None,
        )
        if category is None:
            return jsonify({"error": "Categoria non trovata"}), 404
        budget_value, budget_error = _parse_money(category.get("monthly_budget"), "monthly_budget")
        if budget_error:
            return budget_error
        coherence_error = _validate_category_budgets_with_general_budget(
            g.chat_id,
            category["name"],
            budget_value,
        )
        if coherence_error:
            return coherence_error
        result = pg.set_category_archived(cat_id, False)
        if result is None:
            return jsonify({"error": "Categoria non trovata"}), 404
        return jsonify(result)


@space_bp.route("/api/space/categories/<int:cat_id>", methods=["DELETE"])
@_tg_webapp_auth
def space_categories_delete(cat_id: int):
    """Elimina una categoria riassegnando spese, abbonamenti e obiettivi collegati.

    `?reassign_to=<id>` sceglie la destinazione; senza parametro i record finiscono
    sulla categoria di fallback. Per non perdere nulla si preferisca l'archiviazione.
    """
    reassign_to = request.args.get("reassign_to", type=int)
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        if _is_fallback_category(pg, cat_id):
            return jsonify({
                "error": f"La categoria «{Config.CATEGORY_FALLBACK_NAME}» non può essere eliminata"
            }), 400
        try:
            reassigned = pg.delete_category(cat_id, reassign_to=reassign_to)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if reassigned is None:
            return jsonify({"error": "Categoria non trovata"}), 404
        return jsonify({"status": "ok", "reassigned": reassigned})


# ── Subscriptions ─────────────────────────────────────────────────────────────

@space_bp.route("/api/space/subscriptions", methods=["GET"])
@_tg_webapp_auth
def space_subscriptions_list():
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        return jsonify({"subscriptions": pg.fetch_subscriptions_with_account_name()})


@space_bp.route("/api/space/subscriptions", methods=["POST"])
@_tg_webapp_auth
def space_subscriptions_create():
    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Il campo 'name' è obbligatorio"}), 400
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        result = pg.create_subscription(
            name,
            amount=float(data["amount"]) if data.get("amount") not in (None, "") else None,
            last_billed=data.get("last_billed") or None,
            sub_type=data.get("sub_type") or None,
            account_id=int(data["account_id"]) if data.get("account_id") else None,
            category_id=int(data["category_id"]) if data.get("category_id") else None,
        )
        return jsonify(result), 201


@space_bp.route("/api/space/subscriptions/<int:sub_id>", methods=["PUT"])
@_tg_webapp_auth
def space_subscriptions_update(sub_id: int):
    data = request.json or {}
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        last_billed = None
        if data.get("last_billed"):
            try:
                last_billed = datetime.strptime(data["last_billed"], "%Y-%m-%d").date()
            except ValueError:
                pass
        result = pg.update_subscription(
            sub_id,
            name=data.get("name") or None,
            amount=float(data["amount"]) if data.get("amount") not in (None, "") else None,
            last_billed=last_billed,
            sub_type=data.get("sub_type") or None,
            account_id=int(data["account_id"]) if data.get("account_id") else None,
            category_id=int(data["category_id"]) if data.get("category_id") else None,
        )
        if result is None:
            return jsonify({"error": "Abbonamento non trovato"}), 404
        return jsonify(result)


@space_bp.route("/api/space/subscriptions/<int:sub_id>", methods=["DELETE"])
@_tg_webapp_auth
def space_subscriptions_delete(sub_id: int):
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        ok = pg.delete_subscription(sub_id)
        if not ok:
            return jsonify({"error": "Abbonamento non trovato"}), 404
        return jsonify({"status": "ok"})


# ── Calendar ──────────────────────────────────────────────────────────────────

@space_bp.route("/api/calendar/month", methods=["GET"])
@_tg_webapp_auth
def calendar_month():
    """Spese reali + occorrenze di abbonamento proiettate per un mese, raggruppate per giorno.

    Query params: year=YYYY, month=1-12 (default: mese corrente).
    """
    today = date.today()
    try:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
        if not (1 <= month <= 12):
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "Parametri year/month non validi"}), 400

    start_date = date(year, month, 1)
    end_date = date(year, month, _calendar.monthrange(year, month)[1])

    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        data = pg.fetch_calendar_month(start_date, end_date)

    days: dict[str, dict] = {}

    for exp in data["expenses"]:
        day_key = exp["date"].isoformat() if hasattr(exp["date"], "isoformat") else str(exp["date"])
        days.setdefault(day_key, {"expenses": [], "subscription_occurrences": []})["expenses"].append({
            "id": exp.get("id"),
            "name": exp.get("name", ""),
            "amount": round(exp["amount"], 2),
            "category": exp.get("category") or "Altro",
        })

    for occ in data["subscription_occurrences"]:
        days.setdefault(occ["date"], {"expenses": [], "subscription_occurrences": []})["subscription_occurrences"].append({
            "subscription_id": occ["subscription_id"],
            "name": occ.get("name", ""),
            "amount": round(occ["amount"], 2) if occ.get("amount") is not None else None,
        })

    return jsonify({
        "year": year,
        "month": month,
        "days": days,
    })


# ── Expenses ──────────────────────────────────────────────────────────────────

@space_bp.route("/api/space/expenses", methods=["GET"])
@_tg_webapp_auth
def space_expenses_list():
    today = date.today()
    start = request.args.get("start", date(today.year, today.month, 1).isoformat())
    end = request.args.get("end", today.isoformat())
    limit = min(int(request.args.get("limit", 25)), 100)
    offset = int(request.args.get("offset", 0))
    try:
        start_d = datetime.strptime(start, "%Y-%m-%d").date()
        end_d = datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Formato data non valido (YYYY-MM-DD)"}), 400
    search = request.args.get("search") or None
    category_id = int(request.args.get("category_id")) if request.args.get("category_id") else None
    account_id_f = int(request.args.get("account_id")) if request.args.get("account_id") else None
    sort_by = request.args.get("sort_by", "date")
    if sort_by not in ("date", "amount", "name"):
        sort_by = "date"
    sort_dir = request.args.get("sort_dir", "desc")
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        items, total = pg.fetch_expenses_paginated(
            start_d, end_d, limit=limit, offset=offset,
            search=search, category_id=category_id, account_id=account_id_f,
            sort_by=sort_by, sort_dir=sort_dir,
        )
        return jsonify({"expenses": items, "total": total})


@space_bp.route("/api/space/expenses", methods=["POST"])
@_tg_webapp_auth
def space_expenses_create():
    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name or not data.get("amount") or not data.get("date"):
        return jsonify({"error": "name, amount e date sono obbligatori"}), 400
    try:
        exp_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Formato data non valido"}), 400
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        result = pg.create_expense(
            expense_date=exp_date,
            amount=float(data["amount"]),
            name=name,
            category_name=data.get("category") or "Altro",
            account_id=data.get("account_id"),
        )
        return jsonify(result), 201


@space_bp.route("/api/space/expenses/<int:expense_id>", methods=["PUT"])
@_tg_webapp_auth
def space_expenses_update(expense_id: int):
    data = request.json or {}
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        exp_date = None
        if data.get("date"):
            try:
                exp_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
            except ValueError:
                return jsonify({"error": "Formato data non valido"}), 400
        result = pg.update_expense(
            expense_id,
            name=data.get("name") or None,
            amount=float(data["amount"]) if data.get("amount") not in (None, "") else None,
            date=exp_date,
            category_id=int(data["category_id"]) if data.get("category_id") else None,
            account_id=int(data["account_id"]) if data.get("account_id") else None,
        )
        if result is None:
            return jsonify({"error": "Spesa non trovata"}), 404
        return jsonify(result)


@space_bp.route("/api/space/expenses/<int:expense_id>", methods=["DELETE"])
@_tg_webapp_auth
def space_expenses_delete(expense_id: int):
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        ok = pg.delete_expense(expense_id)
        if not ok:
            return jsonify({"error": "Spesa non trovata"}), 404
        return jsonify({"status": "ok"})


# ── Incomes ───────────────────────────────────────────────────────────────────
# Le categorie di entrata (/api/income-categories*) vivono nel blueprint
# income_categories_bp — vedi src/dashboard/blueprints/income_categories_routes.py

@space_bp.route("/api/space/incomes", methods=["GET"])
@_tg_webapp_auth
def space_incomes_list():
    today = date.today()
    start = request.args.get("start", date(today.year, today.month, 1).isoformat())
    end = request.args.get("end", today.isoformat())
    limit = min(int(request.args.get("limit", 25)), 100)
    offset = int(request.args.get("offset", 0))
    try:
        start_d = datetime.strptime(start, "%Y-%m-%d").date()
        end_d = datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Formato data non valido (YYYY-MM-DD)"}), 400
    search = request.args.get("search") or None
    income_type_f = request.args.get("income_type") or None
    try:
        income_category_id_f = int(request.args.get("income_category_id")) if request.args.get("income_category_id") else None
        account_id_f = int(request.args.get("account_id")) if request.args.get("account_id") else None
    except ValueError:
        return jsonify({"error": "Filtro categoria o conto non valido"}), 400
    sort_by = request.args.get("sort_by", "date")
    if sort_by not in ("date", "amount", "name"):
        sort_by = "date"
    sort_dir = request.args.get("sort_dir", "desc")
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        items, total = pg.fetch_incomes_paginated(
            start_d, end_d, limit=limit, offset=offset,
            search=search, income_category_id=income_category_id_f,
            income_type=income_type_f, account_id=account_id_f,
            sort_by=sort_by, sort_dir=sort_dir,
        )
        return jsonify({"incomes": items, "total": total})


@space_bp.route("/api/space/incomes", methods=["POST"])
@_tg_webapp_auth
def space_incomes_create():
    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name or not data.get("amount") or not data.get("date"):
        return jsonify({"error": "name, amount e date sono obbligatori"}), 400
    try:
        inc_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Formato data non valido"}), 400
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        try:
            result = pg.create_income(
                income_date=inc_date,
                amount=float(data["amount"]),
                name=name,
                account_id=data.get("account_id"),
                income_category_id=data.get("income_category_id") or None,
                income_category_name=data.get("income_category") or None,
                income_type=data.get("income_type") or None,
            )
        except (TypeError, ValueError):
            return jsonify({"error": "Categoria entrata non trovata"}), 400
        return jsonify(result), 201


@space_bp.route("/api/space/incomes/<int:income_id>", methods=["PUT"])
@_tg_webapp_auth
def space_incomes_update(income_id: int):
    data = request.json or {}
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        inc_date = None
        if data.get("date"):
            try:
                inc_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
            except ValueError:
                return jsonify({"error": "Formato data non valido"}), 400
        try:
            result = pg.update_income(
                income_id,
                name=data.get("name") or None,
                amount=float(data["amount"]) if data.get("amount") not in (None, "") else None,
                date=inc_date,
                income_category_id=data.get("income_category_id") if "income_category_id" in data else None,
                income_category_name=data.get("income_category") or None,
                income_type=data.get("income_type") or None,
                account_id=int(data["account_id"]) if data.get("account_id") else None,
            )
        except (TypeError, ValueError):
            return jsonify({"error": "Categoria entrata non trovata"}), 400
        if result is None:
            return jsonify({"error": "Entrata non trovata"}), 404
        return jsonify(result)


@space_bp.route("/api/space/incomes/<int:income_id>", methods=["DELETE"])
@_tg_webapp_auth
def space_incomes_delete(income_id: int):
    with _store().Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        ok = pg.delete_income(income_id)
        if not ok:
            return jsonify({"error": "Entrata non trovata"}), 404
        return jsonify({"status": "ok"})
