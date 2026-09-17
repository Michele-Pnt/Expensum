"""Analytics (Telegram Mini App / webapp) e correzione manuale delle voci di spesa
(`/api/expense-labels/*`, raggruppate qui perché la correzione parte sempre dal
grafico Analytics).

Blueprint leaf: legge lo store condiviso via `current_app.config["STORE"]`, mai
import diretto di `app.py`/`factory.py` (nessun ciclo).
"""
from __future__ import annotations

import logging
from calendar import month_abbr, monthrange
from collections import defaultdict
from datetime import date, timedelta

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import func

from src.dashboard.auth import _tg_webapp_auth
from src.dashboard.storage import _get_user_plan_type, _pg_or_401
from src.billing_utils import get_occurrences_in_range
from src.income_forecast import IncomeForecastEngine
from src.storage.postgres_storage import PostgresStorage

logger = logging.getLogger(__name__)

analytics_bp = Blueprint("analytics", __name__)


def _store():
    return current_app.config["STORE"]


def _month_label(year: int, month: int) -> str:
    return f"{month_abbr[month]} {str(year)[-2:]}"


def _analytics_bucket(day: date, granularity: str, today: date) -> tuple[str, str, bool]:
    """Return the stable key, display label and partial flag for an analytics bucket."""
    if granularity == "yearly":
        return str(day.year), str(day.year), day.year == today.year
    if granularity == "quarterly":
        quarter = (day.month - 1) // 3 + 1
        current_quarter = (today.month - 1) // 3 + 1
        return (
            f"{day.year}-Q{quarter}",
            f"Q{quarter} {day.year}",
            day.year == today.year and quarter == current_quarter,
        )
    return (
        f"{day.year}-{day.month:02d}",
        _month_label(day.year, day.month),
        day.year == today.year and day.month == today.month,
    )


def _analytics_granularity(value: str | None) -> str:
    """Normalize unsupported analytics granularities to the monthly default."""
    return value if value in {"monthly", "quarterly", "yearly"} else "monthly"


def _start_date_for_months(months: int):
    today = date.today()
    # Torna al primo giorno del mese, months-1 mesi indietro,
    # così da includere esattamente `months` mesi (incluso il corrente).
    offset = months - 1
    m = today.month - offset
    y = today.year + m // 12
    m = m % 12
    if m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


@analytics_bp.route("/api/analytics/overview")
@_tg_webapp_auth
def analytics_overview():
    """Ritorna risparmio mensile e spesa mensile per account negli ultimi N mesi."""
    plan_type = _get_user_plan_type(g.chat_id)
    months = min(int(request.args.get("months", 6)), 24)
    start = _start_date_for_months(months)
    end = date.today()
    current_month_start = date(end.year, end.month, 1)
    current_month_end = date(end.year, end.month, monthrange(end.year, end.month)[1])
    # Sei mesi completati alimentano la media; 19 mesi fino a oggi consentono di
    # riconoscere anche tre ricorrenze semestrali senza ampliare il grafico.
    income_history_start = _start_date_for_months(19)
    granularity = _analytics_granularity(request.args.get("granularity"))

    with _store().Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)

        transactions = storage.fetch_all_transactions(start, end)
        incomes = storage.fetch_income(start, end)
        accounts = storage.fetch_accounts()
        current_transactions = storage.fetch_all_transactions(current_month_start, end)
        income_history = storage.fetch_income(income_history_start, end)
        subscriptions = storage.fetch_subscriptions()

    account_map = {a["id"]: a["name"] for a in accounts}

    expenses: dict[str, float] = defaultdict(float)
    by_account: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    by_account_count: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    bucket_meta: dict[str, dict[str, object]] = {}
    bucket_months: dict[str, set[tuple[int, int]]] = defaultdict(set)

    for t in transactions:
        d = t["date"]
        key, label, partial = _analytics_bucket(d, granularity, end)
        expenses[key] += t["amount"]
        bucket_meta[key] = {"period_label": label, "is_partial": partial}
        bucket_months[key].add((d.year, d.month))
        acc_name = account_map.get(t["account_id"], "Altro")
        by_account[key][acc_name] += t["amount"]
        by_account_count[key][acc_name] += 1

    income: dict[str, float] = defaultdict(float)
    for inc in incomes:
        d = inc["date"]
        key, label, partial = _analytics_bucket(d, granularity, end)
        income[key] += inc["amount"]
        bucket_meta[key] = {"period_label": label, "is_partial": partial}
        bucket_months[key].add((d.year, d.month))

    all_keys = sorted(set(expenses) | set(income))
    savings = []
    for key in all_keys:
        meta = bucket_meta[key]
        inc_total = round(income.get(key, 0.0), 2)
        exp_total = round(expenses.get(key, 0.0), 2)
        savings.append({
            "month": meta["period_label"],
            "period_key": key,
            "period_label": meta["period_label"],
            "is_partial": meta["is_partial"],
            "months_included": len(bucket_months[key]),
            "income": inc_total,
            "expenses": exp_total,
            "net": round(inc_total - exp_total, 2),
        })

    totals_by_account = []
    for key in all_keys:
        meta = bucket_meta[key]
        for acc_name, amount in by_account[key].items():
            totals_by_account.append({
                "month": meta["period_label"],
                "period_key": key,
                "period_label": meta["period_label"],
                "is_partial": meta["is_partial"],
                "months_included": len(bucket_months[key]),
                "account": acc_name,
                "amount": round(amount, 2),
                "count": by_account_count[key][acc_name],
            })

    current_expenses = sum(abs(float(item.get("amount") or 0.0)) for item in current_transactions)
    current_income = sum(
        abs(float(item.get("amount") or 0.0))
        for item in income_history
        if current_month_start <= item.get("date") <= end
    )
    remaining_days = (current_month_end - end).days
    variable_expense_projection = (
        current_expenses / end.day * remaining_days if remaining_days > 0 else 0.0
    )
    scheduled_expenses = 0.0
    future_start = end + timedelta(days=1)
    for subscription in subscriptions:
        occurrences = get_occurrences_in_range(
            subscription.get("last_billed"),
            subscription.get("sub_type") or subscription.get("cadence"),
            future_start,
            current_month_end,
        )
        scheduled_expenses += abs(float(subscription.get("amount") or 0.0)) * len(occurrences)

    income_result = IncomeForecastEngine().forecast(
        income_history,
        month_start=current_month_start,
        month_end=current_month_end,
        as_of=end,
    )
    current_net = current_income - current_expenses
    month_end_forecast = {
        "variable_expense_projection": round(variable_expense_projection, 2),
        "scheduled_expenses": round(scheduled_expenses, 2),
        "remaining_expected_income": round(income_result.remaining_total, 2),
        "projected_end_amount": round(
            current_net
            - variable_expense_projection
            - scheduled_expenses
            + income_result.remaining_total,
            2,
        ),
    }

    return jsonify({"savings": savings, "totals_by_account": totals_by_account,
                    "plan_type": plan_type, "granularity": granularity,
                    "month_end_forecast": month_end_forecast})


@analytics_bp.route("/api/analytics/categories-expense")
@_tg_webapp_auth
def analytics_categories_expense():
    """Ritorna spese per categoria: storico mensile e medie per ultimi N mesi.

    Query params:
        months=N        (default 6, max 24)
        category=NAME   (filtra per categoria, solo Pro)
        granularity=    "monthly" (default) | "weekly" (solo Pro)
    """
    plan_type = _get_user_plan_type(g.chat_id)
    months = min(int(request.args.get("months", 6)), 24)
    start = _start_date_for_months(months)
    end = date.today()

    # Filtro categoria (solo Pro puo' filtrare)
    category_filter = request.args.get("category", "").strip() if plan_type == "pro" else ""
    requested_granularity = request.args.get("granularity", "monthly")
    # Weekly remains a backwards-compatible Pro view; the advanced buckets are
    # monthly, quarterly and yearly.
    granularity = (
        requested_granularity if plan_type == "pro" and requested_granularity == "weekly"
        else _analytics_granularity(requested_granularity)
    )

    with _store().Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        transactions = storage.fetch_all_transactions(start, end)
        # Archiviate incluse: una categoria messa da parte a metà periodo ha comunque
        # speso, e la sua riga non deve sparire dal consuntivo.
        categories = storage.get_categories(include_archived=True)

    budget_map = {c["name"]: c.get("monthly_budget") for c in categories}

    if category_filter:
        transactions = [t for t in transactions if (t.get("category") or "Altro").lower() == category_filter.lower()]

    # Aggrega per (anno, mese, categoria) o (anno, week, categoria)
    monthly_cat: dict[tuple, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    monthly_cat_count: dict[tuple, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    bucket_meta: dict[tuple, dict[str, object]] = {}
    bucket_months: dict[tuple, set[tuple[int, int]]] = defaultdict(set)
    for t in transactions:
        d = t["date"]
        if granularity == "weekly":
            iso = d.isocalendar()
            key = (iso[0], iso[1])
            label = f"W{iso[1]} {str(iso[0])[-2:]}"
            partial = False
        else:
            period_key, label, partial = _analytics_bucket(d, granularity, end)
            key = period_key
        cat = t.get("category") or "Altro"
        monthly_cat[key][cat] += t["amount"]
        monthly_cat_count[key][cat] += 1
        bucket_meta[key] = {"period_label": label, "is_partial": partial}
        bucket_months[key].add((d.year, d.month))

    all_keys = sorted(monthly_cat.keys())

    by_category = []
    for key in all_keys:
        if granularity == "weekly":
            label = bucket_meta[key]["period_label"]
        else:
            label = bucket_meta[key]["period_label"]
        for cat, amount in monthly_cat[key].items():
            row = {
                "month": label,
                "name": cat,
                "amount": round(amount, 2),
                "count": monthly_cat_count[key][cat],
                "budget": budget_map.get(cat),
            }
            if granularity != "weekly":
                row.update({
                    "period_key": key,
                    "period_label": label,
                    "is_partial": bucket_meta[key]["is_partial"],
                    "months_included": len(bucket_months[key]),
                })
            by_category.append(row)

    # Media per categoria su tutto il periodo
    cat_totals: dict[str, list[float]] = defaultdict(list)
    for key, cats in monthly_cat.items():
        for cat, amount in cats.items():
            cat_totals[cat].append(amount)

    averages = [
        {"name": cat, "avg": round(sum(vals) / len(vals), 2)}
        for cat, vals in cat_totals.items()
    ]
    averages.sort(key=lambda x: x["avg"], reverse=True)

    return jsonify({"by_category": by_category, "averages": averages,
                    "plan_type": plan_type, "granularity": granularity})


@analytics_bp.route("/api/analytics/income")
@_tg_webapp_auth
def analytics_income():
    """Ritorna storico entrate mensili negli ultimi N mesi."""
    plan_type = _get_user_plan_type(g.chat_id)
    max_months = 24 if plan_type == "pro" else 6
    months = min(int(request.args.get("months", 6)), max_months)
    start = _start_date_for_months(months)
    end = date.today()
    granularity = _analytics_granularity(request.args.get("granularity"))

    with _store().Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        incomes = storage.fetch_income(start, end)

    monthly: dict[str, float] = defaultdict(float)
    bucket_meta: dict[str, dict[str, object]] = {}
    bucket_months: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for inc in incomes:
        d = inc["date"]
        key, label, partial = _analytics_bucket(d, granularity, end)
        monthly[key] += inc["amount"]
        bucket_meta[key] = {"period_label": label, "is_partial": partial}
        bucket_months[key].add((d.year, d.month))

    result = [
        {"month": bucket_meta[key]["period_label"], "period_key": key,
         "period_label": bucket_meta[key]["period_label"],
         "is_partial": bucket_meta[key]["is_partial"],
         "months_included": len(bucket_months[key]), "total": round(amount, 2)}
        for key, amount in sorted(monthly.items())
    ]
    return jsonify({"monthly": result, "plan_type": plan_type, "granularity": granularity})


@analytics_bp.route("/api/analytics/wealth")
@_tg_webapp_auth
def analytics_wealth():
    """Ritorna saldo corrente per account (capitale totale)."""
    plan_type = _get_user_plan_type(g.chat_id)
    with _store().Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        accounts = storage.fetch_accounts()

    result = [
        {"name": a["name"], "balance": round(a["current_balance"] or 0.0, 2)}
        for a in accounts
        if a.get("current_balance") is not None
    ]
    return jsonify({"accounts": result, "plan_type": plan_type})


# ---------------------------------------------------------------------------
# NUOVI ENDPOINT ANALYTICS (Fase 2)
# ---------------------------------------------------------------------------

@analytics_bp.route("/api/analytics/capital-trend")
@_tg_webapp_auth
def analytics_capital_trend():
    """Ritorna lo storico del capitale (somma saldi conti) mese per mese.

    Il calcolo è delegato a `src.wealth.build_wealth_series`, la stessa funzione
    usata dagli obiettivi di risparmio: l'ultimo punto della serie coincide quindi
    sempre con la somma dei saldi mostrati in "Il mio spazio".
    """
    from src.wealth import build_wealth_series

    end = date.today()

    plan_type = _get_user_plan_type(g.chat_id)
    max_months = 24 if plan_type == "pro" else 6
    months = min(int(request.args.get("months", 6)), max_months)
    view_start = _start_date_for_months(months)
    granularity = _analytics_granularity(request.args.get("granularity"))

    with _store().Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        accounts = storage.fetch_accounts()
        series = build_wealth_series(storage, end, since=view_start)

    # A quarterly/yearly point is the last monthly snapshot in that bucket.
    buckets: dict[str, dict[str, object]] = {}
    bucket_months: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for point in series.points:
        point_date = date(point.year, point.month, 1)
        period_key, period_label, is_partial = _analytics_bucket(
            point_date, granularity, end
        )
        buckets[period_key] = {
            "point": point,
            "period_label": period_label,
            "is_partial": is_partial,
        }
        bucket_months[period_key].add((point.year, point.month))

    capital_trend = []
    for period_key, bucket in sorted(buckets.items()):
        point = bucket["point"]
        entry = {
            "month": bucket["period_label"],
            "period_key": period_key,
            "period_label": bucket["period_label"],
            "is_partial": bucket["is_partial"],
            "months_included": len(bucket_months[period_key]),
            "total": point.total,
        }
        # Solo ai Pro mostriamo la scomposizione per singolo conto.
        if plan_type == "pro":
            for acc_id, balance in point.by_account.items():
                entry[series.account_names.get(acc_id, f"Conto {acc_id}")] = balance
        capital_trend.append(entry)

    return jsonify({
        "capital_trend": capital_trend,
        "plan_type": plan_type,
        "granularity": granularity,
        "accounts": [a["name"] for a in accounts] if plan_type == "pro" else [],
        # Spese non attribuite ad alcun conto: escluse dal capitale (non sono
        # imputabili a nessun saldo), ma esposte perché la UI possa spiegare la
        # differenza e invitare l'utente ad assegnare un conto.
        "unassigned_expenses": series.unassigned_expenses,
        "unassigned_incomes": series.unassigned_incomes,
    })


@analytics_bp.route("/api/analytics/budget-status")
@_tg_webapp_auth
def analytics_budget_status():
    """Ritorna lo stato budget per ogni categoria nel mese corrente (o specificato).

    Query params:
        month=YYYY-MM   (default: mese corrente)
    Richiede Pro — per Free ritorna errore con plan_type.
    """
    plan_type = _get_user_plan_type(g.chat_id)
    if plan_type != "pro":
        return jsonify({
            "error": "Funzionalita' riservata agli utenti Pro",
            "plan_type": "free",
            "budget_status": [],
        })

    month_str = request.args.get("month", "")
    if month_str:
        try:
            parts = month_str.split("-")
            target_year, target_month = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            target_year, target_month = date.today().year, date.today().month
    else:
        target_year, target_month = date.today().year, date.today().month

    month_start = date(target_year, target_month, 1)
    _, last_day = monthrange(target_year, target_month)
    month_end = date(target_year, target_month, last_day)

    with _store().Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        transactions = storage.fetch_all_transactions(month_start, month_end)
        incomes = storage.fetch_income(month_start, month_end)
        # Archiviate incluse: il consuntivo di un mese passato non deve cambiare
        # perché nel frattempo l'utente ha archiviato una categoria.
        categories = storage.get_categories(include_archived=True)
    preferences = _store().get_user_preferences(g.chat_id)

    # Budget impostati
    budget_map = {c["name"]: (c.get("monthly_budget") or 0.0) for c in categories}

    # Speso per categoria
    spent_by_cat: dict[str, float] = defaultdict(float)
    for t in transactions:
        cat = t.get("category") or "Altro"
        spent_by_cat[cat] += t["amount"]

    # Solo categorie con budget
    budget_status = []
    for cat_name, budget in budget_map.items():
        if budget <= 0:
            continue
        spent = round(spent_by_cat.get(cat_name, 0.0), 2)
        percentage = round((spent / budget) * 100, 1) if budget > 0 else 0.0
        budget_status.append({
            "category": cat_name,
            "budget": round(budget, 2),
            "spent": spent,
            "remaining": round(max(budget - spent, 0), 2),
            "percentage": percentage,
        })

    # Ordina per % spesa decrescente
    budget_status.sort(key=lambda x: x["percentage"], reverse=True)

    # Totale entrate del mese
    total_income = round(sum(inc["amount"] for inc in incomes), 2)
    total_spent = round(sum(spent_by_cat.values()), 2)

    return jsonify({
        "budget_status": budget_status,
        "month": _month_label(target_year, target_month),
        "total_income": total_income,
        "total_spent": total_spent,
        "monthly_budget": preferences.get("monthly_budget"),
        "plan_type": plan_type,
    })


@analytics_bp.route("/api/analytics/transactions")
@_tg_webapp_auth
def analytics_transactions():
    """Lista transazioni filtrabile per periodo, categoria, conto.

    Query params:
        start=YYYY-MM-DD   (default: 30 giorni fa)
        end=YYYY-MM-DD     (default: oggi)
        category=NAME      (filtro categoria, opzionale)
        account=NAME       (filtro conto, opzionale)
        merchant=NAME      (filtra per voce, opzionale)
        group=1|0          (voce normalizzata o nome esatto, usato con merchant)
        limit=N            (default 50, max 100 per pagina)
        offset=N           (default 0, paginazione)
    """
    plan_type = _get_user_plan_type(g.chat_id)
    limit = min(int(request.args.get("limit", 50)), 100)
    offset = max(int(request.args.get("offset", 0)), 0)

    # Il default è l'ultimo mese, ma Esplora può richiedere qualsiasi intervallo
    # incluso nei suoi aggregati anche per Free.
    today = date.today()
    end_str = request.args.get("end", today.isoformat())
    try:
        end_date = date.fromisoformat(end_str)
    except (ValueError, TypeError):
        end_date = today

    thirty_days_ago = today - timedelta(days=30)
    start_str = request.args.get("start", thirty_days_ago.isoformat())
    try:
        start_date = date.fromisoformat(start_str)
    except (ValueError, TypeError):
        start_date = today - timedelta(days=30)

    category_filter = request.args.get("category", "").strip()
    account_filter = request.args.get("account", "").strip()
    merchant_filter = request.args.get("merchant", "").strip()
    grouped = request.args.get("group", "1") not in ("0", "false")

    with _store().Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        transactions = storage.fetch_all_transactions(start_date, end_date)
        accounts = storage.fetch_accounts()

    acc_map = {a["id"]: a["name"] for a in accounts}

    # Arricchisci con nome account e categoria
    enriched = []
    for t in transactions:
        acc_name = acc_map.get(t.get("account_id"), "Altro")
        cat = t.get("category") or "Altro"

        if category_filter and cat.lower() != category_filter.lower():
            continue
        if account_filter and acc_name.lower() != account_filter.lower():
            continue
        merchant_name = (
            t.get("normalized_name") if grouped else t.get("name")
        ) or t.get("name") or "Sconosciuto"
        if merchant_filter and merchant_name.strip().casefold() != merchant_filter.casefold():
            continue

        d = t["date"]
        enriched.append({
            "id": t.get("id", 0),
            "date": d.isoformat() if hasattr(d, "isoformat") else str(d),
            "name": t.get("name", ""),
            "normalized_name": t.get("normalized_name") or t.get("name", ""),
            "label_cluster_id": t.get("label_cluster_id"),
            "category_id": t.get("category_id"),
            "amount": round(t["amount"], 2),
            "category": cat,
            "account": acc_name,
            "created_at": t.get("created_at") or "",
        })

    # Ordina per data decrescente, a parità di data dalla più recente (created_at desc)
    enriched.sort(key=lambda x: (x["date"], x["created_at"]), reverse=True)

    total_count = len(enriched)
    total_amount = round(sum(e["amount"] for e in enriched), 2)

    # Paginazione
    page = enriched[offset:offset + limit]

    return jsonify({
        "transactions": page,
        "total": total_count,
        "total_amount": total_amount,
        "offset": offset,
        "limit": limit,
        "plan_type": plan_type,
    })


@analytics_bp.route("/api/analytics/top-merchants")
@_tg_webapp_auth
def analytics_top_merchants():
    """Top voci di spesa per totale speso.

    Di default raggruppa per `normalized_name` (voce di spesa normalizzata, es. "coca
    cola" e "coca-cola" unite) — la funzione mostra ancora il nome "merchant" nel
    codice per non rifare tutta la nomenclatura interna, ma dal 2026-09-02 la
    dimensione è "voce di spesa" (vedi rinomina frontend Esercenti -> Voci).

    Con `group=0` aggrega invece per `name` grezzo: è lo switch "per nome" della UI,
    che mostra ogni variante di scrittura separata senza applicare il raggruppamento
    automatico. Il troncamento a `limit` avviene DOPO l'aggregazione, quindi la
    scelta non è delegabile al client: dalla top-N raggruppata non è ricostruibile
    quella per nome grezzo.

    `cluster_id` viene comunque calcolato e restituito anche con `group=0`, ma la UI
    non offre lì la correzione manuale (Unisci/Dividi): quei bottoni compaiono solo
    nella vista raggruppata per etichette (`group=1`), dove operano sul cluster
    intero. È valorizzato solo quando tutte le spese di una riga condividono lo
    stesso cluster; altrimenti è `None`.

    Query params:
        months=N   (default 3)
        limit=N    (nessun limite se omesso; altrimenti onora il valore richiesto —
                    es. i grafici che vogliono sempre e solo la top 10)
        group=1|0  (default: preferenza utente `analytics_group_labels`)
    """
    plan_type = _get_user_plan_type(g.chat_id)
    months = min(int(request.args.get("months", 3)), 24)
    raw_limit = request.args.get("limit")
    limit = int(raw_limit) if raw_limit is not None else None
    raw_group = request.args.get("group")
    if raw_group is not None:
        grouped = raw_group not in ("0", "false")
    else:
        prefs = _store().get_user_preferences(g.chat_id) or {}
        grouped = bool(prefs.get("analytics_group_labels", True))
    start = _start_date_for_months(months)
    end = date.today()

    with _store().Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        transactions = storage.fetch_all_transactions(start, end)

    merchant_totals: dict[str, float] = defaultdict(float)
    merchant_cats: dict[str, str] = {}
    merchant_counts: dict[str, int] = defaultdict(int)
    merchant_clusters: dict[str, set] = defaultdict(set)
    merchant_cat_ids: dict[str, set] = defaultdict(set)

    for t in transactions:
        source = t.get("normalized_name") if grouped else t.get("name")
        name = (source or t.get("name") or "Sconosciuto").strip() or "Sconosciuto"
        merchant_totals[name] += t["amount"]
        merchant_counts[name] += 1
        merchant_clusters[name].add(t.get("label_cluster_id"))
        merchant_cat_ids[name].add(t.get("category_id"))
        if name not in merchant_cats:
            merchant_cats[name] = t.get("category") or "Altro"

    # Top N esplicita oppure tutte le voci del periodo.
    top = sorted(merchant_totals.items(), key=lambda x: x[1], reverse=True)[:limit]

    def _single(values: set):
        """L'unico valore condiviso dalle righe del gruppo, o None se ce n'è più d'uno."""
        return next(iter(values)) if len(values) == 1 else None

    result = [
        {
            "name": name,
            "total": round(total, 2),
            "count": merchant_counts[name],
            "category": merchant_cats.get(name, "Altro"),
            "cluster_id": _single(merchant_clusters[name]),
            "category_id": _single(merchant_cat_ids[name]),
        }
        for name, total in top
    ]

    return jsonify({"merchants": result, "grouped": grouped, "plan_type": plan_type})


# ---------------------------------------------------------------------------
# /api/expense-labels — correzione manuale del raggruppamento voci di spesa
#
# Il matching automatico (src/expense_label_normalizer.py) è conservativo ma può
# sbagliare in due direzioni: lasciare separate voci che sono la stessa cosa, o
# unire voci diverse. Questi endpoint sono il percorso guidato con cui l'utente
# corregge dal grafico Analytics. Nessun testo libero: le etichette proposte
# vengono sempre da dati già esistenti.
#
# Attenzione al logging: i nomi delle voci di spesa sono contenuto dell'utente e
# non vanno mai nei log né nei messaggi d'errore restituiti al client.
# ---------------------------------------------------------------------------

from src.expense_label_normalizer import MAX_MERGE_SOURCES as _MAX_MERGE_SOURCES
from src.expense_label_normalizer import MAX_SPLIT_VARIANTS as _MAX_SPLIT_VARIANTS

# Spese mostrate espandendo un chip: è un'anteprima per riconoscere la voce, non
# l'elenco completo dei movimenti (quello vive in "Il mio Spazio").
_MAX_VARIANT_EXPENSES = 20


def _label_error_response(exc):
    """Mappa un LabelClusterError sul suo status HTTP."""
    status = 404 if exc.code == "cluster_not_found" else 400
    return jsonify({"error": exc.message, "code": exc.code}), status


def _variants_from_name_totals(rows: list[tuple[str, int, float]]) -> list[dict]:
    """Come `_variants_from_expenses`, ma partendo da conteggi già aggregati dal DB.

    Serve alla lista dei candidati di "Unisci", dove interessano quante spese e
    quanto pesa ogni voce ma non i singoli movimenti: aggregare nel database evita
    di caricare una riga per spesa solo per contarle.
    """
    from src.expense_label_normalizer import _light_normalize

    grouped: dict[str, dict] = {}
    for name, count, total in rows:
        entry = grouped.setdefault(
            _light_normalize(name), {"count": 0, "total": 0.0, "forms": {}}
        )
        entry["count"] += count
        entry["total"] += total
        entry["forms"][name] = entry["forms"].get(name, 0) + count

    variants = []
    for entry in sorted(grouped.values(), key=lambda v: v["count"], reverse=True):
        forms = entry.pop("forms")
        entry["text"] = max(forms.items(), key=lambda item: item[1])[0]
        entry["total"] = round(entry["total"], 2)
        variants.append(entry)
    return variants


def _variants_from_expenses(expenses: list) -> list[dict]:
    """Raggruppa le spese di un gruppo nelle voci che l'utente può selezionare.

    Le voci si calcolano dalle spese reali, non da `variant_counts`: quel campo non
    viene mai decrementato quando una spesa è cancellata o rinominata, quindi
    mostrerebbe voci fantasma proprio nella schermata in cui si decide cosa spostare.

    Il raggruppamento è per forma normalizzata (la stessa chiave usata dalle regole di
    correzione): "Coca Cola" e "coca  cola" sono una voce sola, etichettata con la
    grafia più frequente. Separarle sarebbe impossibile da onorare, perché le regole
    non distinguono maiuscole e spazi.
    """
    from src.expense_label_normalizer import _light_normalize

    grouped: dict[str, dict] = {}
    for expense in expenses:
        key = _light_normalize(expense.name)
        entry = grouped.setdefault(
            key, {"text": expense.name, "count": 0, "total": 0.0, "expenses": [], "forms": {}}
        )
        entry["count"] += 1
        entry["total"] += float(expense.amount or 0)
        entry["forms"][expense.name] = entry["forms"].get(expense.name, 0) + 1
        if len(entry["expenses"]) < _MAX_VARIANT_EXPENSES:
            entry["expenses"].append({
                "id": expense.id,
                "name": expense.name,
                "date": expense.expense_date.isoformat(),
                "amount": float(expense.amount or 0),
            })

    variants = sorted(grouped.values(), key=lambda v: v["count"], reverse=True)
    for variant in variants:
        # Etichetta della voce: la grafia usata più spesso dall'utente.
        forms = variant.pop("forms")
        variant["text"] = max(forms.items(), key=lambda item: item[1])[0]
        variant["total"] = round(variant["total"], 2)
    return variants


@analytics_bp.route("/api/expense-labels/clusters")
@_tg_webapp_auth
def expense_labels_clusters():
    """Gruppi di voci proponibili per "Unisci", con tutto ciò che contengono.

    Il periodo decide **quali** gruppi proporre: solo quelli con almeno una spesa nel
    periodo, cioè quelli che l'utente sta guardando nel grafico. Un gruppo senza spese
    lì non compare, quindi proporlo confonderebbe.

    Conteggi, totali e voci si riferiscono invece all'**intero** gruppo, periodo
    incluso o no: l'unione sposta tutto quello che il gruppo contiene, e mostrare i
    soli numeri del periodo farebbe credere di spostare una spesa quando se ne
    spostano quattro. È anche la stessa fotografia che dà il pannello "Dividi".

    Le voci arrivano senza il dettaglio delle spese: quello lo carica
    `/clusters/<id>/variants` quando l'utente apre un gruppo, così l'elenco resta
    leggero anche per chi ha molto storico.

    `category_id` filtra i candidati compatibili — il merge è ammesso solo dentro la
    stessa categoria.
    """
    from src.storage.models import Expense, ExpenseLabelCluster, UserCategory

    plan_type = _get_user_plan_type(g.chat_id)
    max_months = 24 if plan_type == "pro" else 3
    try:
        months = min(int(request.args.get("months", 3)), max_months)
    except (TypeError, ValueError):
        months = 3
    months = max(months, 1)
    raw_category = request.args.get("category_id")
    category_id = None
    if raw_category not in (None, ""):
        try:
            category_id = int(raw_category)
        except (TypeError, ValueError):
            return jsonify({"error": "category_id non valido"}), 400

    start = _start_date_for_months(months)
    end = date.today()

    with _store().Session() as s:
        # `_pg_or_401` non serve per lo storage ma per il binding RLS della sessione
        # (+ gating sul backend): va chiamata prima di qualunque query, non rimuovere.
        _pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        # 1. Quali gruppi proporre: quelli visibili nel grafico del periodo.
        candidates = (
            s.query(ExpenseLabelCluster.id)
            .join(Expense, Expense.label_cluster_id == ExpenseLabelCluster.id)
            .filter(
                ExpenseLabelCluster.user_id == g.chat_id,
                Expense.user_id == g.chat_id,
                Expense.expense_date >= start,
                Expense.expense_date <= end,
            )
        )
        if category_id is not None:
            candidates = candidates.filter(ExpenseLabelCluster.category_id == category_id)
        candidate_ids = [row[0] for row in candidates.distinct().all()]
        if not candidate_ids:
            return jsonify({"clusters": [], "plan_type": plan_type})

        meta = (
            s.query(ExpenseLabelCluster, UserCategory.name)
            .outerjoin(UserCategory, UserCategory.id == ExpenseLabelCluster.category_id)
            .filter(ExpenseLabelCluster.id.in_(candidate_ids))
            .all()
        )

        # 2. Cosa contengono, su tutto lo storico: aggregazione nel database, senza
        #    portare in memoria una riga per spesa.
        totals = (
            s.query(
                Expense.label_cluster_id,
                Expense.name,
                func.count(Expense.id),
                func.sum(Expense.amount),
            )
            .filter(
                Expense.user_id == g.chat_id,
                Expense.label_cluster_id.in_(candidate_ids),
            )
            .group_by(Expense.label_cluster_id, Expense.name)
            .all()
        )
        rows_by_cluster: dict[int, list] = {}
        for cluster_id, name, count, total in totals:
            rows_by_cluster.setdefault(cluster_id, []).append(
                (name, int(count or 0), float(total or 0))
            )

        clusters = []
        for cluster, category_name in meta:
            variants = _variants_from_name_totals(rows_by_cluster.get(cluster.id, []))
            clusters.append({
                "id": cluster.id,
                "anchor_text": cluster.anchor_text,
                "category_id": cluster.category_id,
                "category": category_name or "Altro",
                "count": sum(v["count"] for v in variants),
                "total": round(sum(v["total"] for v in variants), 2),
                "variants": variants,
            })

    clusters.sort(key=lambda c: c["total"], reverse=True)
    return jsonify({"clusters": clusters, "plan_type": plan_type})


@analytics_bp.route("/api/expense-labels/clusters/<int:cluster_id>/variants")
@_tg_webapp_auth
def expense_labels_cluster_variants(cluster_id: int):
    """Varianti testuali dentro un gruppo, per la scelta guidata di "Dividi".

    Le varianti si calcolano dalle spese reali, non da `variant_counts`: quel campo
    non viene mai decrementato quando una spesa viene cancellata o rinominata, quindi
    mostrerebbe voci fantasma con conteggi sbagliati proprio nella schermata in cui
    l'utente decide cosa spostare.

    Il raggruppamento è per forma normalizzata (stessa chiave usata dalle regole di
    correzione): "Coca Cola" e "coca  cola" sono un chip solo, etichettato con la
    forma più frequente. Separarle sarebbe impossibile da onorare, perché le regole
    non distinguono maiuscole e spazi.
    """
    from src.storage.models import Expense, ExpenseLabelCluster

    with _store().Session() as s:
        # `_pg_or_401` non serve per lo storage ma per il binding RLS della sessione
        # (+ gating sul backend): va chiamata prima di qualunque query, non rimuovere.
        _pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        cluster = (
            s.query(ExpenseLabelCluster)
            .filter_by(id=cluster_id, user_id=g.chat_id)
            .first()
        )
        if cluster is None:
            return jsonify({"error": "Voce non trovata"}), 404

        expenses = (
            s.query(Expense)
            .filter(Expense.user_id == g.chat_id, Expense.label_cluster_id == cluster_id)
            .order_by(Expense.expense_date.desc())
            .all()
        )
        variants = _variants_from_expenses(expenses)

        return jsonify({
            "cluster_id": cluster.id,
            "anchor_text": cluster.anchor_text,
            "category_id": cluster.category_id,
            "variants": variants,
        })


@analytics_bp.route("/api/expense-labels/merge", methods=["POST"])
@_tg_webapp_auth
def expense_labels_merge():
    """Unisce più gruppi in uno solo (correzione manuale dell'utente)."""
    from src.expense_label_normalizer import LabelClusterError, merge_clusters

    data = request.get_json(silent=True) or {}
    target_id = data.get("target_cluster_id")
    if not isinstance(target_id, int):
        return jsonify({"error": "target_cluster_id è obbligatorio"}), 400
    source_ids = data.get("source_cluster_ids")
    if (
        not isinstance(source_ids, list)
        or not source_ids
        or len(source_ids) > _MAX_MERGE_SOURCES
        or not all(isinstance(cid, int) for cid in source_ids)
    ):
        return jsonify({
            "error": f"Seleziona da 1 a {_MAX_MERGE_SOURCES} voci da unire"
        }), 400
    if target_id in source_ids:
        return jsonify({"error": "Non puoi unire una voce con sé stessa"}), 400
    anchor_text = data.get("anchor_text")
    if anchor_text is not None and not isinstance(anchor_text, str):
        return jsonify({"error": "L'etichetta scelta non è valida"}), 400

    # Unione parziale: {cluster_id: [voci da spostare]}. I cluster non citati si
    # spostano per intero. Le chiavi arrivano come stringhe dal JSON.
    raw_variants = data.get("source_variants")
    source_variants: dict[int, list[str]] | None = None
    if raw_variants is not None:
        if not isinstance(raw_variants, dict):
            return jsonify({"error": "Selezione delle voci non valida"}), 400
        source_variants = {}
        for key, value in raw_variants.items():
            try:
                cluster_key = int(key)
            except (TypeError, ValueError):
                return jsonify({"error": "Selezione delle voci non valida"}), 400
            if (
                not isinstance(value, list)
                or not value
                or len(value) > _MAX_SPLIT_VARIANTS
                or not all(isinstance(item, str) for item in value)
            ):
                return jsonify({"error": "Selezione delle voci non valida"}), 400
            source_variants[cluster_key] = value

    with _store().Session() as s:
        # `_pg_or_401` non serve per lo storage ma per il binding RLS della sessione
        # (+ gating sul backend): va chiamata prima di qualunque query, non rimuovere.
        _pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        try:
            result = merge_clusters(
                s, g.chat_id, target_id, source_ids, anchor_text, source_variants,
            )
        except LabelClusterError as exc:
            return _label_error_response(exc)
        s.commit()

    logger.info(
        "expense_labels_merged",
        extra={
            "domain": "usage",
            "event": "expense_labels_merged",
            "chat_id": g.chat_id,
            "meta": {
                "target_cluster_id": result.target_cluster_id,
                "absorbed": len(result.absorbed_cluster_ids),
                "moved_expenses": result.moved_expenses,
            },
        },
    )
    return jsonify({
        "cluster_id": result.target_cluster_id,
        "anchor_text": result.anchor_text,
        "merged": len(result.absorbed_cluster_ids),
        "moved_expenses": result.moved_expenses,
    })


@analytics_bp.route("/api/expense-labels/rename", methods=["POST"])
@_tg_webapp_auth
def expense_labels_rename():
    """Rinomina un gruppo scegliendo una delle sue grafie esistenti, senza unirlo ad altri."""
    from src.expense_label_normalizer import LabelClusterError, rename_cluster

    data = request.get_json(silent=True) or {}
    cluster_id = data.get("cluster_id")
    if not isinstance(cluster_id, int):
        return jsonify({"error": "cluster_id è obbligatorio"}), 400
    anchor_text = data.get("anchor_text")
    if not isinstance(anchor_text, str) or not anchor_text:
        return jsonify({"error": "L'etichetta scelta non è valida"}), 400

    with _store().Session() as s:
        # `_pg_or_401` non serve per lo storage ma per il binding RLS della sessione
        # (+ gating sul backend): va chiamata prima di qualunque query, non rimuovere.
        _pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        try:
            result = rename_cluster(s, g.chat_id, cluster_id, anchor_text)
        except LabelClusterError as exc:
            return _label_error_response(exc)
        s.commit()

    return jsonify({"cluster_id": result.cluster_id, "anchor_text": result.anchor_text})


@analytics_bp.route("/api/expense-labels/split", methods=["POST"])
@_tg_webapp_auth
def expense_labels_split():
    """Separa alcune varianti di un gruppo in un gruppo nuovo."""
    from src.expense_label_normalizer import LabelClusterError, split_variants

    data = request.get_json(silent=True) or {}
    cluster_id = data.get("cluster_id")
    if not isinstance(cluster_id, int):
        return jsonify({"error": "cluster_id è obbligatorio"}), 400
    variants = data.get("variants")
    if (
        not isinstance(variants, list)
        or not variants
        or len(variants) > _MAX_SPLIT_VARIANTS
        or not all(isinstance(v, str) for v in variants)
    ):
        return jsonify({"error": "Seleziona almeno una voce da separare"}), 400
    new_anchor = data.get("new_anchor")
    if new_anchor is not None and not isinstance(new_anchor, str):
        return jsonify({"error": "L'etichetta scelta non è valida"}), 400

    with _store().Session() as s:
        # `_pg_or_401` non serve per lo storage ma per il binding RLS della sessione
        # (+ gating sul backend): va chiamata prima di qualunque query, non rimuovere.
        _pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        try:
            result = split_variants(s, g.chat_id, cluster_id, variants, new_anchor)
        except LabelClusterError as exc:
            return _label_error_response(exc)
        s.commit()

    logger.info(
        "expense_labels_split",
        extra={
            "domain": "usage",
            "event": "expense_labels_split",
            "chat_id": g.chat_id,
            "meta": {
                "cluster_id": cluster_id,
                "new_cluster_id": result.new_cluster_id,
                "variants_moved": len(variants),
                "moved_expenses": result.moved_expenses,
            },
        },
    )
    return jsonify({
        "cluster_id": result.new_cluster_id,
        "anchor_text": result.anchor_text,
        "moved_expenses": result.moved_expenses,
    }), 201


@analytics_bp.route("/api/analytics/savings-rate")
@_tg_webapp_auth
def analytics_savings_rate():
    """Tasso di risparmio mensile: (entrate - uscite) / entrate * 100.

    Richiede Pro — per Free ritorna errore con plan_type.
    """
    plan_type = _get_user_plan_type(g.chat_id)
    if plan_type != "pro":
        return jsonify({
            "error": "Funzionalita' riservata agli utenti Pro",
            "plan_type": "free",
            "savings_rate": [],
        })

    months = min(int(request.args.get("months", 6)), 24)
    start = _start_date_for_months(months)
    end = date.today()
    granularity = _analytics_granularity(request.args.get("granularity"))

    with _store().Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        transactions = storage.fetch_all_transactions(start, end)
        incomes = storage.fetch_income(start, end)

    monthly_expenses: dict[str, float] = defaultdict(float)
    bucket_meta: dict[str, dict[str, object]] = {}
    bucket_months: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for t in transactions:
        d = t["date"]
        key, label, partial = _analytics_bucket(d, granularity, end)
        monthly_expenses[key] += t["amount"]
        bucket_meta[key] = {"period_label": label, "is_partial": partial}
        bucket_months[key].add((d.year, d.month))

    monthly_income: dict[str, float] = defaultdict(float)
    for inc in incomes:
        d = inc["date"]
        key, label, partial = _analytics_bucket(d, granularity, end)
        monthly_income[key] += inc["amount"]
        bucket_meta[key] = {"period_label": label, "is_partial": partial}
        bucket_months[key].add((d.year, d.month))

    all_keys = sorted(set(monthly_expenses) | set(monthly_income))

    savings_rate = []
    for key in all_keys:
        meta = bucket_meta[key]
        inc = round(monthly_income.get(key, 0.0), 2)
        exp = round(monthly_expenses.get(key, 0.0), 2)
        savings = round(inc - exp, 2)
        rate = round((savings / inc) * 100, 1) if inc > 0 else 0.0
        savings_rate.append({
            "month": meta["period_label"],
            "period_key": key,
            "period_label": meta["period_label"],
            "is_partial": meta["is_partial"],
            "months_included": len(bucket_months[key]),
            "income": inc,
            "expenses": exp,
            "savings": savings,
            "rate": rate,
        })

    return jsonify({"savings_rate": savings_rate, "plan_type": plan_type,
                    "granularity": granularity})


@analytics_bp.route("/api/analytics/month-comparison")
@_tg_webapp_auth
def analytics_month_comparison():
    """Confronto spese per categoria: mese corrente vs mese precedente vs media 3 mesi.

    Richiede Pro — per Free ritorna errore con plan_type.
    """
    plan_type = _get_user_plan_type(g.chat_id)
    if plan_type != "pro":
        return jsonify({
            "error": "Funzionalita' riservata agli utenti Pro",
            "plan_type": "free",
            "comparisons": [],
        })

    today = date.today()
    granularity = _analytics_granularity(request.args.get("granularity"))
    current_date = date(today.year, today.month, 1)
    span_months = {"monthly": 4, "quarterly": 15, "yearly": 60}[granularity]
    history_start = _start_date_for_months(span_months)

    with _store().Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        transactions = storage.fetch_all_transactions(history_start, today)

    bucket_cat: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    bucket_months: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for t in transactions:
        d = t["date"]
        key, _, _ = _analytics_bucket(d, granularity, today)
        cat = t.get("category") or "Altro"
        bucket_cat[key][cat] += t["amount"]
        bucket_months[key].add((d.year, d.month))

    def _shift_month(value: date, delta: int) -> date:
        absolute = value.year * 12 + value.month - 1 + delta
        return date(absolute // 12, absolute % 12 + 1, 1)

    step = {"monthly": 1, "quarterly": 3, "yearly": 12}[granularity]
    current_key, current_label, current_partial = _analytics_bucket(
        today, granularity, today
    )
    previous_date = _shift_month(current_date, -step)
    previous_key, previous_label, previous_partial = _analytics_bucket(
        previous_date, granularity, today
    )
    previous_keys = []
    for index in range(3):
        period_date = _shift_month(current_date, -step * (index + 1))
        key, label, partial = _analytics_bucket(period_date, granularity, today)
        previous_keys.append((key, label, partial))

    cur_spending = bucket_cat.get(current_key, {})
    prev_spending = bucket_cat.get(previous_key, {})
    avg_spending: dict[str, float] = defaultdict(float)
    if granularity == "monthly":
        # Preserve the historical monthly behavior: empty months are not part
        # of the denominator, while the selected periods remain calendar-based.
        average_keys = [key for key in sorted(bucket_cat) if key != current_key][-3:]
    else:
        average_keys = [key for key, _, _ in previous_keys]
    for key in average_keys:
        for cat, amount in bucket_cat.get(key, {}).items():
            avg_spending[cat] += amount
    for cat in avg_spending:
        avg_spending[cat] = round(avg_spending[cat] / len(average_keys), 2)

    # Costruisci il confronto
    all_cats = set(cur_spending) | set(prev_spending) | set(avg_spending)
    comparisons = []
    for cat in sorted(all_cats):
        cur_val = round(cur_spending.get(cat, 0.0), 2)
        prev_val = round(prev_spending.get(cat, 0.0), 2)
        avg_val = round(avg_spending.get(cat, 0.0), 2)

        change_pct = round(((cur_val - prev_val) / prev_val) * 100, 1) if prev_val > 0 else 0.0

        comparisons.append({
            "category": cat,
            "current_month": cur_val,
            "last_month": prev_val,
            "avg_3m": avg_val,
            "change_pct": change_pct,
        })

        comparisons[-1].update({
            "period_key": current_key,
            "period_label": current_label,
            "is_partial": current_partial,
            "months_included": len(bucket_months.get(current_key, set())),
        })

    return jsonify({
        "comparisons": comparisons,
        "plan_type": plan_type,
        "granularity": granularity,
        "current_bucket": {"period_key": current_key, "period_label": current_label,
                           "is_partial": current_partial,
                           "months_included": len(bucket_months.get(current_key, set()))},
        "previous_bucket": {"period_key": previous_key, "period_label": previous_label,
                            "is_partial": previous_partial,
                            "months_included": len(bucket_months.get(previous_key, set()))},
        "average_buckets": [
            {"period_key": key, "period_label": label, "is_partial": partial,
             "months_included": len(bucket_months.get(key, set()))}
            for key, label, partial in previous_keys
        ],
    })
