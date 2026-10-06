"""Layer di aggregazione per la dashboard admin di Expensum.

Contiene **solo** funzioni pure di query/aggregazione: ognuna riceve una
`Session` SQLAlchemy già aperta e restituisce strutture dati semplici (dict/list)
pronte per il template o per un endpoint JSON. Nessuna logica Flask qui dentro,
così le funzioni sono testabili in isolamento (`pytest -m unit`) e la dashboard
resta un semplice orchestratore.

Principi:
- Portabilità SQLite (test) / PostgreSQL (prod): si evita SQL dialect-specifico;
  le aggregazioni per mese e gli intervalli tra eventi sono calcolati lato Python.
- I valori `Numeric` (Decimal) sono convertiti a float prima di uscire.
- Le metriche di timing spese sono **cross-backend**: si basano su `chat_messages`
  (una riga per transazione confermata, sia Notion sia Postgres), non su
  `expenses`/`incomes` che esistono solo per il backend Postgres.
"""
from __future__ import annotations

import os
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from src.user_store import (
    ChatMessage,
    DailyMetrics,
    Feedback,
    JobRun,
    LlmUsageEvent,
    PlanChange,
    ReferralReward,
    TallyLead,
    TxEvent,
    User,
    UserPlan,
    RegistrationCapacity,
    UserProfile,
    UserProfileGoal,
    ConsentEvent,
    MarketingSyncTask,
)
from src.storage.models import (
    AiImprovementSample,
    Expense,
    ExpenseLabelCluster,
    RecurringIncomeRule,
    SubscriptionCandidate,
)

# Soglia storica del ledger token: coerente con la dashboard esistente, si
# considerano solo gli eventi dal 2026-05-01 in avanti (prima i dati non erano
# affidabili).
LEDGER_EPOCH = datetime(2026, 5, 1)

# Prezzo del piano Pro usato per stimare l'MRR. Non è un dato di prodotto salvato
# a DB: va impostato via env `PRO_PRICE_EUR` e aggiornato se cambia il listino.
PRO_PRICE_EUR = float(os.getenv("PRO_PRICE_EUR", "4.99"))


def get_registration_access_metrics(s: Session) -> dict[str, Any]:
    """Return capacity and registration funnel aggregates without identifiers."""
    capacity = s.query(RegistrationCapacity).filter_by(id=1).first()
    max_accounts = capacity.max_accounts if capacity else 0
    active = s.query(User).filter(User.registration_status == "active").count()
    reserved = s.query(User).filter(
        User.registration_status == "pending_verification"
    ).count()
    return {
        "capacity": {
            "max": max_accounts,
            "occupied": active,
            "reserved": reserved,
            "remaining": max(0, max_accounts - active - reserved),
        },
        "funnel": {
            "pending_verification": reserved,
            "verified": active,
            "onboarding_completed": s.query(User).filter(
                User.onboarding_completed_at.isnot(None)
            ).count(),
        },
    }


def get_ai_quality_metrics(s: Session) -> dict[str, Any]:
    """Return aggregate correction counts, never sample content or OCR."""
    rows = s.query(
        AiImprovementSample.input_method,
        AiImprovementSample.model_provider,
        func.count(AiImprovementSample.id),
    ).group_by(
        AiImprovementSample.input_method, AiImprovementSample.model_provider
    ).all()
    return {
        "samples": [
            {"input_method": method, "provider": provider, "count": int(count)}
            for method, provider, count in rows
        ],
        "total": sum(int(count) for _, _, count in rows),
    }

# Operazioni LLM generate automaticamente dal sistema. La definizione è per
# opt-out: una nuova operazione interattiva contribuisce alle metriche finché non
# viene esplicitamente classificata come automatica.
AUTOMATED_LLM_OPERATIONS = frozenset({
    "monthly_plan",
    "monthly_report",
    "weekly_plan",
})


def _f(value: Any, ndigits: int = 2) -> float:
    """Converte Decimal/None/numerico in float arrotondato (0.0 se None)."""
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        value = float(value)
    return round(float(value), ndigits)


def _month_key(dt: datetime) -> str:
    """Bucket mensile portabile 'YYYY-MM' (calcolato in Python, non in SQL)."""
    return f"{dt.year:04d}-{dt.month:02d}"


MAX_USAGE_CHART_DAYS = 180


def get_usage_chart(s: Session, days: int = 10, now: datetime | None = None) -> dict[str, list]:
    """Token consumati per giorno negli ultimi `days` giorni (grafico "Consumo Token LLM").

    Estratta da get_overview_kpis così il periodo è selezionabile a runtime (selettore
    10gg/1mese/2mesi/N a scelta in dashboard) senza duplicare la logica di bucketing.
    `days` è limitato a MAX_USAGE_CHART_DAYS per evitare query e payload spropositati
    se un admin digita un numero enorme nel campo "a scelta".
    """
    now = now or datetime.utcnow()
    days = max(1, min(days, MAX_USAGE_CHART_DAYS))
    since = now - timedelta(days=days)

    rows = s.query(
        func.date(LlmUsageEvent.occurred_at),
        func.sum(LlmUsageEvent.prompt_tokens),
        func.sum(LlmUsageEvent.completion_tokens),
        func.sum(LlmUsageEvent.total_tokens),
    ).filter(
        LlmUsageEvent.occurred_at >= max(since, LEDGER_EPOCH)
    ).group_by(func.date(LlmUsageEvent.occurred_at)).all()

    chart_data: dict[str, dict[str, int]] = {}
    for x in range(days):
        d = (now - timedelta(days=days - 1 - x)).date()
        chart_data[d.isoformat()] = {"prompt": 0, "completion": 0, "total": 0}
    for d_val, pt, ct, tt in rows:
        d_str = str(d_val)
        if d_str in chart_data:
            chart_data[d_str]["prompt"] += int(pt or 0)
            chart_data[d_str]["completion"] += int(ct or 0)
            chart_data[d_str]["total"] += int(tt or 0)

    return {
        "chart_labels": list(chart_data.keys()),
        "chart_prompt": [v["prompt"] for v in chart_data.values()],
        "chart_completion": [v["completion"] for v in chart_data.values()],
        "chart_total": [v["total"] for v in chart_data.values()],
    }


# ---------------------------------------------------------------------------
# 1. KPI di overview + grafico ledger token (estratto da index())
# ---------------------------------------------------------------------------
def get_overview_kpis(s: Session) -> dict[str, Any]:
    """KPI principali della dashboard: utenti, feedback, token, costi, AI metrics.

    Replica la logica storica di `index()` così che la route diventi un semplice
    orchestratore. Ritorna un dict serializzabile per il template.
    """
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    users_count = s.query(User).count()
    active_users = s.query(User).filter(User.is_active.is_(True)).count()
    unread_feedback = s.query(Feedback).filter(Feedback.status == "unread").count()

    tokens_today = s.query(
        func.coalesce(func.sum(LlmUsageEvent.total_tokens), 0)
    ).filter(LlmUsageEvent.occurred_at >= today_start).scalar() or 0

    tokens_month = s.query(
        func.coalesce(func.sum(LlmUsageEvent.total_tokens), 0)
    ).filter(LlmUsageEvent.occurred_at >= max(thirty_days_ago, LEDGER_EPOCH)).scalar() or 0

    cost_month = s.query(
        func.coalesce(func.sum(LlmUsageEvent.estimated_cost_amount), 0.0)
    ).filter(LlmUsageEvent.occurred_at >= max(thirty_days_ago, LEDGER_EPOCH)).scalar() or 0.0

    cost_total = s.query(
        func.coalesce(func.sum(LlmUsageEvent.estimated_cost_amount), 0.0)
    ).filter(LlmUsageEvent.occurred_at >= LEDGER_EPOCH).scalar() or 0.0

    # Breakdown token per giorno (ultimi 10 giorni) per il grafico line.
    chart = get_usage_chart(s, days=10, now=now)
    labels = chart["chart_labels"]
    data_prompt = chart["chart_prompt"]
    data_completion = chart["chart_completion"]
    data_total = chart["chart_total"]

    total_messages = sum(data_total)
    avg_msg_per_user = round(total_messages / active_users, 0) if active_users > 0 else 0

    # GCR e Fallback Rate dai DailyMetrics (ultimi 10 giorni).
    ten_days_ago_date = now.date() - timedelta(days=10)
    ai_metrics = s.query(DailyMetrics).filter(
        DailyMetrics.metrics_date >= ten_days_ago_date
    ).all()
    total_completions = sum(m.goal_completions or 0 for m in ai_metrics)
    total_fallbacks = sum(m.fallbacks or 0 for m in ai_metrics)
    total_ai = total_completions + total_fallbacks
    if total_ai > 0:
        goal_completion_rate = round(total_completions / total_ai * 100, 1)
        fallback_rate = round(total_fallbacks / total_ai * 100, 1)
    else:
        goal_completion_rate = None
        fallback_rate = None

    return {
        "users_count": users_count,
        "active_users": active_users,
        "unread_feedback": unread_feedback,
        "tokens_today": tokens_today,
        "tokens_month": tokens_month,
        "cost_month": _f(cost_month, 4),
        "cost_total": _f(cost_total, 4),
        "chart_labels": labels,
        "chart_prompt": data_prompt,
        "chart_completion": data_completion,
        "chart_total": data_total,
        "avg_msg_per_user": avg_msg_per_user,
        "goal_completion_rate": goal_completion_rate,
        "fallback_rate": fallback_rate,
    }


# ---------------------------------------------------------------------------
# 2. Token analytics 90 giorni per operazione e plan_type (estratto da index())
# ---------------------------------------------------------------------------
def get_token_analytics_90d(s: Session) -> dict[str, Any]:
    """Analytics token 90gg disaggregate per operazione e plan_type (free/pro)."""
    ninety_days_ago = datetime.utcnow() - timedelta(days=90)

    # Le stesse espressioni (oggetti, non nuove chiamate) vanno usate sia nel SELECT
    # sia nel GROUP BY: chiamare due volte func.coalesce(..., "free") crea due bind
    # parameter distinti per il letterale "free" e Postgres, che confronta le
    # espressioni GROUP BY/SELECT a livello sintattico prima di sostituire i
    # parametri, le tratta come diverse e rifiuta la query con GroupingError
    # (visto in produzione: "column user_plans.plan_type must appear in GROUP BY").
    day_expr = func.date(LlmUsageEvent.occurred_at)
    plan_expr = func.coalesce(UserPlan.plan_type, "free")

    rows = s.query(
        day_expr.label("d"),
        LlmUsageEvent.operation,
        plan_expr.label("plan_type"),
        func.count().label("req_count"),
        func.avg(LlmUsageEvent.total_tokens).label("avg_tokens"),
        func.sum(case((LlmUsageEvent.total_tokens > 0, 1), else_=0)).label("success_count"),
    ).outerjoin(
        UserPlan, LlmUsageEvent.chat_id == UserPlan.chat_id
    ).filter(
        LlmUsageEvent.occurred_at >= max(ninety_days_ago, LEDGER_EPOCH)
    ).group_by(
        day_expr,
        LlmUsageEvent.operation,
        plan_expr,
    ).all()

    requests_by_op: dict[str, dict[str, dict[str, int]]] = {}
    token_stats: dict[str, dict[str, Any]] = {}
    conversion: dict[str, dict[str, Any]] = {}
    # Totali grezzi su TUTTE le righe (non per-operazione): servono per l'overall
    # conversion rate mostrato nelle stat card in alto nel tab. In precedenza il
    # frontend tentava di ricalcolarlo sommando strutture annidate per operazione/
    # data ma non sommava mai i successi (variabile mai incrementata): il totale
    # restava sempre 0. Calcolarlo qui, una volta sola, elimina quel bug alla radice.
    overall_requests = 0
    overall_success = 0
    overall_token_weighted = 0.0

    operations = {r[1] for r in rows}
    for op in operations:
        token_stats[op] = {"free": {"tt": 0.0, "cnt": 0}, "pro": {"tt": 0.0, "cnt": 0}}
        conversion[op] = {"free": {"ok": 0, "tot": 0}, "pro": {"ok": 0, "tot": 0}}

    for d_val, op, plan, req_count, avg_tokens, success_count in rows:
        date_str = str(d_val)
        plan = plan if plan in ("free", "pro") else "free"
        requests_by_op.setdefault(op, {}).setdefault(
            date_str, {"free": 0, "pro": 0, "total": 0}
        )
        requests_by_op[op][date_str][plan] = req_count
        requests_by_op[op][date_str]["total"] += req_count

        if avg_tokens:
            token_stats[op][plan]["tt"] += float(avg_tokens) * req_count
            token_stats[op][plan]["cnt"] += req_count
            overall_token_weighted += float(avg_tokens) * req_count

        conversion[op][plan]["ok"] += int(success_count or 0)
        conversion[op][plan]["tot"] += req_count
        overall_requests += req_count
        overall_success += int(success_count or 0)

    token_display: dict[str, dict[str, int]] = {}
    for op, plans in token_stats.items():
        token_display[op] = {}
        gt = gc = 0.0
        for plan in ("free", "pro"):
            cnt = plans[plan]["cnt"]
            token_display[op][plan] = int(round(plans[plan]["tt"] / cnt, 0)) if cnt else 0
            gt += plans[plan]["tt"]
            gc += cnt
        token_display[op]["total"] = int(round(gt / gc, 0)) if gc else 0

    conv_display: dict[str, dict[str, float]] = {}
    for op, plans in conversion.items():
        conv_display[op] = {}
        gs = gtot = 0
        for plan in ("free", "pro"):
            tot = plans[plan]["tot"]
            ok = plans[plan]["ok"]
            conv_display[op][plan] = round(100 * ok / tot, 1) if tot else 0
            gs += ok
            gtot += tot
        conv_display[op]["total"] = round(100 * gs / gtot, 1) if gtot else 0

    return {
        "requests_by_operation": requests_by_op,
        "token_stats": token_display,
        "conversion_rates": conv_display,
        "overall": {
            "total_requests": overall_requests,
            "avg_tokens": int(round(overall_token_weighted / overall_requests, 0)) if overall_requests else 0,
            "conversion_rate_pct": round(100 * overall_success / overall_requests, 1) if overall_requests else 0.0,
            "operation_count": len(operations),
        },
    }


# ---------------------------------------------------------------------------
# 3. Consumo token per utente (ciclo/storico) — estratto da users_token_usage
# ---------------------------------------------------------------------------
def get_token_usage_per_user(s: Session) -> list[dict[str, Any]]:
    """Consumo token e costo per ogni utente (tutto lo storico ledger)."""
    rows = s.query(
        LlmUsageEvent.chat_id,
        User.username,
        func.count().label("req_count"),
        func.sum(LlmUsageEvent.total_tokens).label("total_tokens"),
        func.sum(func.coalesce(LlmUsageEvent.estimated_cost_amount, 0)).label("cost"),
    ).outerjoin(
        User, User.chat_id == LlmUsageEvent.chat_id
    ).group_by(
        LlmUsageEvent.chat_id, User.username
    ).order_by(func.sum(LlmUsageEvent.total_tokens).desc()).all()

    # "Ultima Attività" reale = ultimo messaggio inviato dall'utente (role="user"),
    # non l'ultimo LlmUsageEvent: quello viene scritto anche da job schedulati
    # (es. weekly_plan_job) che chiamano l'LLM per conto dell'utente senza che lui
    # abbia fatto nulla, producendo timestamp identici per tutti gli utenti attivi.
    last_user_msg = dict(
        s.query(ChatMessage.chat_id, func.max(ChatMessage.created_at))
        .filter(ChatMessage.role == "user")
        .group_by(ChatMessage.chat_id)
        .all()
    )

    out = []
    for chat_id, username, req_count, total_tokens, cost in rows:
        last_seen = last_user_msg.get(chat_id)
        out.append({
            "chat_id": chat_id,
            "username": username or chat_id,
            "req_count": req_count,
            "total_tokens": int(total_tokens or 0),
            "total_cost_usd": _f(cost, 6),
            "last_seen": str(last_seen)[:16] if last_seen else "—",
        })
    return out


# ---------------------------------------------------------------------------
# 4. Consumo token mensile per utente + media (per tarare le quote)
# ---------------------------------------------------------------------------
def get_monthly_token_usage(
    s: Session, months: int = 6, now: datetime | None = None
) -> dict[str, Any]:
    """Consumo token per mese e per utente, con statistiche per tarare le quote.

    `now` è iniettabile per gli stessi motivi di `get_retention`: ancorare i bucket
    mensili al tempo reale rende i test silenziosamente rossi al cambio di mese.

    Ritorna:
    - `months`: elenco ordinato dei bucket 'YYYY-MM' considerati
    - `per_user`: righe per utente con consumo per mese e totale
    - `monthly_avg`: media token per utente attivo, per mese
    - `current_month_stats`: avg/median/p90/max del mese corrente (per decidere
      il tetto free, oggi 150k)
    """
    now = now or datetime.utcnow()
    # Primo giorno del mese `months-1` mesi fa.
    start_year = now.year
    start_month = now.month - (months - 1)
    while start_month <= 0:
        start_month += 12
        start_year -= 1
    since = datetime(start_year, start_month, 1)

    rows = s.query(
        LlmUsageEvent.chat_id, LlmUsageEvent.occurred_at, LlmUsageEvent.total_tokens
    ).filter(LlmUsageEvent.occurred_at >= max(since, LEDGER_EPOCH)).all()

    # Bucket labels ordinate.
    month_labels: list[str] = []
    y, m = start_year, start_month
    for _ in range(months):
        month_labels.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1

    # chat_id -> {ym: tokens}
    usage: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for chat_id, occurred_at, tokens in rows:
        usage[chat_id][_month_key(occurred_at)] += int(tokens or 0)

    usernames = dict(s.query(User.chat_id, User.username).all())

    per_user = []
    for chat_id, by_month in usage.items():
        total = sum(by_month.values())
        per_user.append({
            "chat_id": chat_id,
            "username": usernames.get(chat_id) or chat_id,
            "by_month": {ym: by_month.get(ym, 0) for ym in month_labels},
            "total": total,
        })
    per_user.sort(key=lambda r: r["total"], reverse=True)

    # Media per utente attivo, per mese (denominatore = utenti con consumo nel mese).
    monthly_avg: dict[str, float] = {}
    for ym in month_labels:
        vals = [u["by_month"][ym] for u in per_user if u["by_month"][ym] > 0]
        monthly_avg[ym] = round(statistics.mean(vals), 0) if vals else 0.0

    current_ym = _month_key(now)
    current_vals = [u["by_month"].get(current_ym, 0) for u in per_user
                    if u["by_month"].get(current_ym, 0) > 0]
    if current_vals:
        srt = sorted(current_vals)
        p90_idx = max(0, int(len(srt) * 0.9) - 1)
        current_stats = {
            "avg": round(statistics.mean(current_vals), 0),
            "median": round(statistics.median(current_vals), 0),
            "p90": srt[p90_idx],
            "max": max(current_vals),
            "active_users": len(current_vals),
        }
    else:
        current_stats = {"avg": 0, "median": 0, "p90": 0, "max": 0, "active_users": 0}

    return {
        "months": month_labels,
        "per_user": per_user,
        "monthly_avg": monthly_avg,
        "current_month_stats": current_stats,
    }


# ---------------------------------------------------------------------------
# 5. Retention: attivi a 7/14/60 giorni
# ---------------------------------------------------------------------------
def _last_active_map(s: Session) -> dict[str, datetime]:
    """chat_id -> ultima attività esplicita dell'utente.

    Sono validi solo gli eventi LLM interattivi e i messaggi scritti dall'utente.
    In particolare, i messaggi bot e le operazioni schedulate (piani/report) non
    possono rendere attivo un utente.
    """
    last: dict[str, datetime] = {}
    for chat_id, ts in s.query(
        LlmUsageEvent.chat_id, func.max(LlmUsageEvent.occurred_at)
    ).filter(
        LlmUsageEvent.operation.notin_(AUTOMATED_LLM_OPERATIONS)
    ).group_by(LlmUsageEvent.chat_id).all():
        if ts:
            last[chat_id] = ts
    for chat_id, ts in s.query(
        ChatMessage.chat_id, func.max(ChatMessage.created_at)
    ).filter(
        ChatMessage.role == "user"
    ).group_by(ChatMessage.chat_id).all():
        if ts and (chat_id not in last or ts > last[chat_id]):
            last[chat_id] = ts
    for chat_id, ts in s.query(
        TxEvent.chat_id, func.max(TxEvent.occurred_at)
    ).group_by(TxEvent.chat_id).all():
        if ts and (chat_id not in last or ts > last[chat_id]):
            last[chat_id] = ts
    return last


def get_retention(
    s: Session, windows: tuple[int, ...] = (7, 14, 60), now: datetime | None = None
) -> dict[str, Any]:
    """Retention di prodotto su 7/14/60 giorni.

    - `rolling_active`: quanti utenti hanno avuto attività negli ultimi N giorni
      (stickiness "usano ancora l'app adesso").
    - `cohort_retention`: tra gli utenti il cui account ha almeno N giorni,
      quanti sono rimasti attivi fino ad almeno N giorni dopo la registrazione.

    `now` iniettabile (pattern già usato in get_usage_chart) — nei test permette di
    ancorare il calcolo alla data dei dati seminati invece che al tempo reale, che
    altrimenti fa scadere silenziosamente le finestre rolling man mano che il tempo
    reale si allontana dai timestamp fissi della fixture.
    """
    now = now or datetime.utcnow()
    last_active = _last_active_map(s)
    users = s.query(User.chat_id, User.created_at).all()
    total_users = len(users)

    rolling_active: dict[int, dict[str, Any]] = {}
    for n in windows:
        threshold = now - timedelta(days=n)
        count = sum(1 for cid, _ in users
                    if last_active.get(cid) and last_active[cid] >= threshold)
        rolling_active[n] = {
            "count": count,
            "pct": round(100 * count / total_users, 1) if total_users else 0.0,
        }

    cohort_retention: dict[int, dict[str, Any]] = {}
    for n in windows:
        eligible = [(cid, created) for cid, created in users
                    if created and (now - created).days >= n]
        retained = 0
        for cid, created in eligible:
            la = last_active.get(cid)
            if la and (la - created).days >= n:
                retained += 1
        cohort_retention[n] = {
            "eligible": len(eligible),
            "retained": retained,
            "pct": round(100 * retained / len(eligible), 1) if eligible else 0.0,
        }

    return {
        "total_users": total_users,
        "rolling_active": rolling_active,
        "cohort_retention": cohort_retention,
    }


# ---------------------------------------------------------------------------
# 6/7. Timing spese: tempo alla prima spesa + intervallo tra spese consecutive
# ---------------------------------------------------------------------------
def _confirmed_tx_by_user(s: Session) -> dict[str, list[datetime]]:
    """chat_id -> lista ordinata dei timestamp delle transazioni confermate.

    Una transazione confermata (spesa/entrata/trasferimento salvato dopo il click
    Conferma) lascia una riga `chat_messages` con role='bot' e `metadata_json`
    valorizzato. Cross-backend (vale sia per Notion sia per Postgres).
    """
    rows = s.query(ChatMessage.chat_id, ChatMessage.created_at).filter(
        ChatMessage.role == "bot",
        ChatMessage.metadata_json.isnot(None),
    ).order_by(ChatMessage.chat_id, ChatMessage.created_at).all()
    by_user: dict[str, list[datetime]] = defaultdict(list)
    for chat_id, created_at in rows:
        if created_at:
            by_user[chat_id].append(created_at)
    return by_user


def get_expense_timing(s: Session) -> dict[str, Any]:
    """Tempo alla prima spesa e intervallo mediano tra spese consecutive."""
    tx_by_user = _confirmed_tx_by_user(s)
    users_created = dict(s.query(User.chat_id, User.created_at).all())

    time_to_first_hours: list[float] = []
    for chat_id, timestamps in tx_by_user.items():
        created = users_created.get(chat_id)
        if created and timestamps:
            delta = (timestamps[0] - created).total_seconds() / 3600.0
            if delta >= 0:
                time_to_first_hours.append(delta)

    inter_hours: list[float] = []
    for timestamps in tx_by_user.values():
        for prev, curr in zip(timestamps, timestamps[1:]):
            delta = (curr - prev).total_seconds() / 3600.0
            if delta >= 0:
                inter_hours.append(delta)

    total_users = s.query(User).count()
    users_with_tx = len(tx_by_user)

    def _summary(values: list[float]) -> dict[str, Any]:
        if not values:
            return {"count": 0, "avg_hours": 0.0, "median_hours": 0.0,
                    "avg_days": 0.0, "median_days": 0.0}
        avg = statistics.mean(values)
        med = statistics.median(values)
        return {
            "count": len(values),
            "avg_hours": round(avg, 1),
            "median_hours": round(med, 1),
            "avg_days": round(avg / 24, 2),
            "median_days": round(med / 24, 2),
        }

    return {
        "total_users": total_users,
        "users_with_tx": users_with_tx,
        "users_without_tx": total_users - users_with_tx,
        "time_to_first_expense": _summary(time_to_first_hours),
        "interval_between_expenses": _summary(inter_hours),
    }


# ---------------------------------------------------------------------------
# 8. Funnel onboarding: skip wizard + step di abbandono
# ---------------------------------------------------------------------------
def get_onboarding_funnel(s: Session) -> dict[str, Any]:
    """Distribuzione stato wizard preferenze e setup tecnico.

    - quanti utenti saltano il wizard (onboarding_step ancora 'pending')
    - a che step si fermano (distribuzione onboarding_step != completed)
    - distribuzione setup_status
    """
    total = s.query(User).count()

    step_rows = s.query(User.onboarding_step, func.count()).group_by(
        User.onboarding_step
    ).all()
    by_step = {step or "pending": cnt for step, cnt in step_rows}

    completed = s.query(User).filter(User.onboarding_completed_at.isnot(None)).count()
    pending = by_step.get("pending", 0)
    # In corso = ha uno step nominato ma non ha completato.
    in_progress = max(0, total - completed - pending)

    setup_rows = s.query(User.setup_status, func.count()).group_by(
        User.setup_status
    ).all()
    by_setup = {status or "unknown": cnt for status, cnt in setup_rows}

    return {
        "total": total,
        "by_step": by_step,
        "by_setup_status": by_setup,
        "completed": completed,
        "completed_pct": round(100 * completed / total, 1) if total else 0.0,
        "skipped_pending": pending,
        "skipped_pct": round(100 * pending / total, 1) if total else 0.0,
        "in_progress": in_progress,
    }


# ---------------------------------------------------------------------------
# 9. Funnel & revenue: piani, MRR, churn, unit economics
# ---------------------------------------------------------------------------
def get_funnel_revenue(s: Session, now: datetime | None = None) -> dict[str, Any]:
    """Metriche di business: distribuzione piani, MRR proxy, churn, unit economics.

    `now` è iniettabile per gli stessi motivi di `get_retention`: ancorare le
    finestre rolling al tempo reale rende i test silenziosamente rossi appena
    i dati seminati escono dalla finestra.
    """
    now = now or datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)
    ninety_days_ago = now - timedelta(days=90)

    plan_rows = s.query(UserPlan.plan_type, func.count()).group_by(
        UserPlan.plan_type
    ).all()
    by_plan = {plan or "free": cnt for plan, cnt in plan_rows}
    free_count = by_plan.get("free", 0)
    pro_count = by_plan.get("pro", 0)

    trials_active = s.query(UserPlan).filter(UserPlan.is_trial.is_(True)).count()
    # Pro paganti = pro non in trial (l'MRR non include i trial gratuiti).
    paying_pro = s.query(UserPlan).filter(
        UserPlan.plan_type == "pro", UserPlan.is_trial.is_(False)
    ).count()

    # Distingue i pro "beta grant" (concessi manualmente da script/admin, reason
    # payment_reference="beta_default" — vedi scripts/upgrade_beta_users_to_pro.py
    # e la registrazione web in fase beta) dai pro pagati per davvero via Stripe.
    # Prima del lancio pubblico lo Stripe webhook è uno stub inerte: senza questa
    # distinzione MRR/conversione contavano come "ricavo" utenti che non hanno
    # mai pagato nulla. Si guarda l'ultimo plan_change verso "pro" di ciascun
    # utente attualmente pro (non l'eventuale primo), così un utente beta che in
    # futuro converte per davvero smette di essere contato come grant.
    pro_chat_ids = [row[0] for row in s.query(UserPlan.chat_id).filter(
        UserPlan.plan_type == "pro", UserPlan.is_trial.is_(False)
    ).all()]
    latest_pro_reason: dict[str, str | None] = {}
    if pro_chat_ids:
        change_rows = s.query(PlanChange.chat_id, PlanChange.reason).filter(
            PlanChange.to_plan == "pro", PlanChange.chat_id.in_(pro_chat_ids)
        ).order_by(PlanChange.changed_at.asc()).all()
        for chat_id, reason in change_rows:
            latest_pro_reason[chat_id] = reason  # l'ultimo in ordine asc sovrascrive

    beta_grant_pro = sum(1 for cid in pro_chat_ids if latest_pro_reason.get(cid) == "beta_default")
    real_paying_pro = paying_pro - beta_grant_pro
    mrr = round(real_paying_pro * PRO_PRICE_EUR, 2)

    def _changes(change_type: str, since: datetime) -> int:
        return s.query(PlanChange).filter(
            PlanChange.change_type == change_type, PlanChange.changed_at >= since
        ).count()

    upgrades_30 = _changes("upgrade", thirty_days_ago)
    downgrades_30 = _changes("downgrade", thirty_days_ago)
    trial_expired_90 = _changes("trial_expired", ninety_days_ago)
    upgrades_90 = _changes("upgrade", ninety_days_ago)

    # Unit economics: costo LLM 30gg vs ricavo.
    cost_30 = _f(s.query(
        func.coalesce(func.sum(LlmUsageEvent.estimated_cost_amount), 0.0)
    ).filter(LlmUsageEvent.occurred_at >= max(thirty_days_ago, LEDGER_EPOCH)).scalar(), 2)

    total_users = free_count + pro_count
    cost_per_user = round(cost_30 / total_users, 4) if total_users else 0.0
    cost_revenue_ratio = round(100 * cost_30 / mrr, 1) if mrr else None

    return {
        "by_plan": by_plan,
        "free_count": free_count,
        "pro_count": pro_count,
        "paying_pro": paying_pro,
        "beta_grant_pro": beta_grant_pro,
        "real_paying_pro": real_paying_pro,
        "trials_active": trials_active,
        "pro_conversion_pct": round(100 * pro_count / total_users, 1) if total_users else 0.0,
        "mrr_eur": mrr,
        "pro_price_eur": PRO_PRICE_EUR,
        "upgrades_30d": upgrades_30,
        "downgrades_30d": downgrades_30,
        "upgrades_90d": upgrades_90,
        "trial_expired_90d": trial_expired_90,
        "llm_cost_30d_usd": cost_30,
        "cost_per_user_usd": cost_per_user,
        "cost_revenue_ratio_pct": cost_revenue_ratio,
    }


# ---------------------------------------------------------------------------
# 10. Engagement & acquisizione
# ---------------------------------------------------------------------------
def get_engagement_acquisition(
    s: Session, signup_days: int = 30, now: datetime | None = None
) -> dict[str, Any]:
    """DAU/WAU/MAU basati su attività esplicita, trend registrazioni e waitlist.

    ``now`` e' iniettabile per rendere deterministiche le finestre rolling nei test.
    """
    now = now or datetime.utcnow()

    def _active_since(days: int) -> int:
        since = now - timedelta(days=days)
        llm_users = s.query(LlmUsageEvent.chat_id).filter(
            LlmUsageEvent.occurred_at >= since,
            LlmUsageEvent.operation.notin_(AUTOMATED_LLM_OPERATIONS),
        ).distinct()
        chat_users = s.query(ChatMessage.chat_id).filter(
            ChatMessage.created_at >= since,
            ChatMessage.role == "user",
        ).distinct()
        tx_users = s.query(TxEvent.chat_id).filter(
            TxEvent.occurred_at >= since,
        ).distinct()
        return len(
            {row[0] for row in llm_users.all()}
            | {row[0] for row in chat_users.all()}
            | {row[0] for row in tx_users.all()}
        )

    dau, wau, mau = _active_since(1), _active_since(7), _active_since(30)

    # Nuove registrazioni per giorno (ultimi signup_days giorni).
    since_signup = (now - timedelta(days=signup_days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    created_rows = s.query(User.created_at).filter(
        User.created_at >= since_signup
    ).all()
    signups_by_day: dict[str, int] = {}
    for x in range(signup_days):
        d = (now - timedelta(days=signup_days - 1 - x)).date()
        signups_by_day[d.isoformat()] = 0
    for (created,) in created_rows:
        if created:
            key = created.date().isoformat()
            if key in signups_by_day:
                signups_by_day[key] += 1

    backend_rows = s.query(User.storage_backend, func.count()).group_by(
        User.storage_backend
    ).all()
    by_backend = {backend or "notion": cnt for backend, cnt in backend_rows}

    leads_total = s.query(TallyLead).count()
    leads_synced = s.query(TallyLead).filter(TallyLead.synced_to_brevo.is_(True)).count()
    leads_granted = s.query(TallyLead).filter(
        TallyLead.beta_account_granted.is_(True)
    ).count()

    return {
        "dau": dau,
        "wau": wau,
        "mau": mau,
        "signups_by_day": signups_by_day,
        "signups_total_period": sum(signups_by_day.values()),
        "storage_backend": by_backend,
        "waitlist": {
            "total": leads_total,
            "synced_to_brevo": leads_synced,
            "beta_granted": leads_granted,
            "conversion_pct": round(100 * leads_granted / leads_total, 1) if leads_total else 0.0,
        },
    }


# ---------------------------------------------------------------------------
# 11. Stato scheduled job (esiti + no-show)
# ---------------------------------------------------------------------------
# The schedule uses the same local timezone as BackgroundScheduler in bot.py.
# `now` in this module is naive UTC, so local schedule times must be converted
# before comparing them with the current time.
SCHEDULER_TZ = ZoneInfo("Europe/Rome")

# Expected schedule, aligned with bot.py::_start_scheduler, used to detect missed jobs.
JOB_SCHEDULE: list[dict[str, Any]] = [
    {"job_id": "db_backup", "label": "Backup DB (pg_dump→B2)", "kind": "daily", "hour": 2, "minute": 30},
    {"job_id": "daily_recurring_income_job", "label": "Entrate ricorrenti", "kind": "daily", "hour": 2, "minute": 55},
    {"job_id": "nightly_category_sync", "label": "Sync categorie", "kind": "daily", "hour": 3, "minute": 0},
    {"job_id": "nightly_subscription_job", "label": "Subscription", "kind": "daily", "hour": 3, "minute": 5},
    {"job_id": "nightly_retention_cleanup", "label": "Retention cleanup", "kind": "daily", "hour": 3, "minute": 10},
    {"job_id": "trial_expiry_job", "label": "Trial expiry", "kind": "daily", "hour": 4, "minute": 0},
    {"job_id": "daily_dashboard_job", "label": "Dashboard giornaliera", "kind": "daily", "hour": 8, "minute": 0},
    {"job_id": "weekly_plan_job", "label": "Piano settimanale", "kind": "weekly", "weekday": 0, "hour": 8, "minute": 5},
    {"job_id": "monthly_plan_job", "label": "Piano mensile", "kind": "monthly", "day": 1, "hour": 8, "minute": 0},
    {"job_id": "trial_lifecycle_job", "label": "Trial drip", "kind": "daily", "hour": 9, "minute": 0},
    {"job_id": "health_check_job", "label": "Health check", "kind": "interval", "hours": 4},
    {"job_id": "disk_space_check_job", "label": "Disk check", "kind": "interval", "hours": 6},
]


def _run_to_dict(run: JobRun) -> dict[str, Any]:
    """Serializza una riga JobRun per il template."""
    return {
        "job_id": run.job_id,
        "status": run.status,
        "trigger_type": run.trigger_type,
        "scheduled_at": run.scheduled_at,
        "finished_at": run.finished_at,
        "duration_ms": run.duration_ms,
        "return_code": run.return_code,
        "error_text": run.error_text,
    }


def get_jobs_status(s: Session, now: datetime | None = None) -> dict[str, Any]:
    """Stato dei job schedulati: esito odierno per job + rilevamento no-show.

    Per ogni job dello schedule atteso determina lo stato:
    - `success`/`error`: c'è un'esecuzione (di oggi, o recente per gli interval);
    - `missed`: era atteso e l'orario è passato ma non risulta nessuna esecuzione;
    - `pending`: atteso più tardi oggi;
    - `not_scheduled`: non previsto oggi (job settimanale/mensile in giorno diverso).
    """
    now = now or datetime.utcnow()
    today = now.date()
    lookback = now - timedelta(days=3)

    runs = s.query(JobRun).filter(JobRun.finished_at >= lookback).order_by(
        JobRun.finished_at.desc()
    ).all()

    last_run: dict[str, JobRun] = {}
    today_run: dict[str, JobRun] = {}
    for r in runs:
        if r.job_id not in last_run:
            last_run[r.job_id] = r
        if r.finished_at and r.finished_at.date() == today and r.job_id not in today_run:
            today_run[r.job_id] = r

    jobs: list[dict[str, Any]] = []
    counts = {"success": 0, "error": 0, "missed": 0, "pending": 0, "not_scheduled": 0}

    for spec in JOB_SCHEDULE:
        job_id = spec["job_id"]
        kind = spec["kind"]
        expected_time = None
        state = "pending"

        if kind == "interval":
            grace = timedelta(hours=spec["hours"] * 2)
            lr = last_run.get(job_id)
            if lr and lr.finished_at and (now - lr.finished_at) <= grace:
                state = lr.status if lr.status in ("success", "error") else "success"
            elif lr:
                state = "missed"  # stale: nessuna esecuzione entro la finestra di grazia
            else:
                state = "missed"
        else:
            if kind == "weekly":
                expected_today = now.weekday() == spec["weekday"]
            elif kind == "monthly":
                expected_today = now.day == spec["day"]
            else:  # daily
                expected_today = True

            if expected_today:
                # JOB_SCHEDULE è in ora locale (Europe/Rome, come il cron reale):
                # si localizza sulla data odierna e si converte in UTC naive per
                # confrontarla con `now`, che è sempre UTC.
                local_expected = datetime(
                    today.year, today.month, today.day,
                    spec["hour"], spec["minute"], tzinfo=SCHEDULER_TZ,
                )
                expected_time = local_expected.astimezone(timezone.utc).replace(tzinfo=None)

            tr = today_run.get(job_id)
            if not expected_today:
                state = "not_scheduled"
            elif tr:
                state = tr.status if tr.status in ("success", "error") else "success"
            elif expected_time and now >= expected_time:
                state = "missed"
            else:
                state = "pending"

        counts[state] = counts.get(state, 0) + 1
        lr = today_run.get(job_id) or last_run.get(job_id)
        jobs.append({
            "job_id": job_id,
            "label": spec["label"],
            "kind": kind,
            "expected_time": expected_time,
            "state": state,
            "last_run": _run_to_dict(lr) if lr else None,
        })

    recent = [_run_to_dict(r) for r in runs[:50]]

    return {
        "now": now,
        "jobs": jobs,
        "counts": counts,
        "recent": recent,
        "has_alerts": counts.get("missed", 0) > 0 or counts.get("error", 0) > 0,
    }


# ---------------------------------------------------------------------------
# 12. Split successi parsing per tipo transazione x modalità di input
# ---------------------------------------------------------------------------
TX_TYPES = ("expense", "income", "transfer")
INPUT_METHODS = ("text", "voice", "photo", "button")


def get_tx_success_by_type_method(
    s: Session, days: int = 30, now: datetime | None = None
) -> dict[str, Any]:
    """Successi/fallimenti di parsing per tipo transazione x modalità di input.

    Successo = l'utente ha cliccato Conferma e la transazione è stata salvata
    (outcome='confirmed' in tx_events). Aggrega anche cancellati e falliti per
    calcolare il success-rate. Fonte: tx_events, rispecchiata da bot.py/app.py
    accanto agli eventi PostHog esistenti.
    """
    since = (now or datetime.utcnow()) - timedelta(days=days)
    rows = s.query(
        TxEvent.tx_type, TxEvent.input_method, TxEvent.outcome, func.count()
    ).filter(TxEvent.occurred_at >= since).group_by(
        TxEvent.tx_type, TxEvent.input_method, TxEvent.outcome
    ).all()

    # matrix[tx_type][input_method] = {"confirmed": n, "cancelled": n, "failed": n}
    matrix: dict[str, dict[str, dict[str, int]]] = {}
    seen_types: set[str] = set()
    seen_methods: set[str] = set()
    for tx_type, method, outcome, count in rows:
        seen_types.add(tx_type)
        seen_methods.add(method)
        matrix.setdefault(tx_type, {}).setdefault(
            method, {"confirmed": 0, "cancelled": 0, "failed": 0}
        )[outcome] = count

    types = [t for t in TX_TYPES if t in seen_types] + sorted(seen_types - set(TX_TYPES))
    methods = [m for m in INPUT_METHODS if m in seen_methods] + sorted(seen_methods - set(INPUT_METHODS))

    rows_out = []
    totals_confirmed = totals_cancelled = totals_failed = totals_all = 0
    for tx_type in types:
        for method in methods:
            cell = matrix.get(tx_type, {}).get(method)
            if not cell:
                continue
            total = sum(cell.values())
            confirmed = cell.get("confirmed", 0)
            totals_confirmed += confirmed
            totals_cancelled += cell.get("cancelled", 0)
            totals_failed += cell.get("failed", 0)
            totals_all += total
            rows_out.append({
                "tx_type": tx_type,
                "input_method": method,
                "confirmed": confirmed,
                "cancelled": cell.get("cancelled", 0),
                "failed": cell.get("failed", 0),
                "total": total,
                "success_rate_pct": round(100 * confirmed / total, 1) if total else 0.0,
            })

    # Quota di conferme in cui l'utente ha corretto la categoria proposta dall'AI
    # prima di salvare (reason='category_corrected', vedi bot.py::setcat/msetcat).
    # Non è un fallimento — la transazione è comunque confermata — ma segnala
    # quanto spesso il parsing azzecca l'importo/tipo ma sbaglia la categoria.
    category_corrected_count = s.query(func.count()).filter(
        TxEvent.occurred_at >= since,
        TxEvent.outcome == "confirmed",
        TxEvent.reason == "category_corrected",
    ).scalar() or 0

    return {
        "days": days,
        "rows": rows_out,
        "types": types,
        "methods": methods,
        "overall_success_rate_pct": round(100 * totals_confirmed / totals_all, 1) if totals_all else 0.0,
        # Separati apposta: un errore tecnico (failed, guasto lato AI/salvataggio) e
        # un abbandono deliberato dell'utente (cancelled) sono segnali diversi — il
        # vecchio success_rate li fondeva in un solo "non confermato".
        "overall_error_rate_pct": round(100 * totals_failed / totals_all, 1) if totals_all else 0.0,
        "overall_cancel_rate_pct": round(100 * totals_cancelled / totals_all, 1) if totals_all else 0.0,
        "overall_category_corrected_pct": (
            round(100 * category_corrected_count / totals_confirmed, 1) if totals_confirmed else 0.0
        ),
        "overall_total": totals_all,
    }


def get_source_breakdown_90d(s: Session) -> dict[str, Any]:
    """Richieste/token/costo LLM negli ultimi 90gg, per canale (Telegram vs webapp).

    Il canale non è una colonna: si deriva dal prefisso di chat_id ('web_...' per
    gli account webapp, sia registrati direttamente sia collegati a Telegram —
    vedi src/dashboard/app.py::web_register e user_store.py, entrambi generano
    `f"web_{uuid.uuid4().hex}"`). Nessuna migration necessaria: il prefisso è
    già presente su ogni riga storica del ledger.
    """
    ninety_days_ago = datetime.utcnow() - timedelta(days=90)
    source_expr = case(
        (LlmUsageEvent.chat_id.like("web\\_%", escape="\\"), "webapp"),
        else_="telegram",
    )

    rows = s.query(
        source_expr.label("source"),
        func.count().label("req_count"),
        func.sum(LlmUsageEvent.total_tokens).label("total_tokens"),
        func.sum(func.coalesce(LlmUsageEvent.estimated_cost_amount, 0)).label("cost"),
    ).filter(
        LlmUsageEvent.occurred_at >= max(ninety_days_ago, LEDGER_EPOCH)
    ).group_by(source_expr).all()

    by_source = {
        "telegram": {"requests": 0, "total_tokens": 0, "cost_usd": 0.0},
        "webapp": {"requests": 0, "total_tokens": 0, "cost_usd": 0.0},
    }
    for source, req_count, total_tokens, cost in rows:
        by_source[source] = {
            "requests": req_count,
            "total_tokens": int(total_tokens or 0),
            "cost_usd": _f(cost, 4),
        }
    return by_source


def get_provider_cost_breakdown_90d(s: Session) -> dict[str, Any]:
    """Richieste/token/costo LLM negli ultimi 90gg, per provider AI (Mistral/Gemini/...).

    `provider`/`model` sono colonne dirette di llm_usage_events (sempre valorizzate,
    NOT NULL), nessuna derivazione necessaria. Nota: le foto (OCR scontrini) NON
    generano un costo provider proprio — l'estrazione testo è Tesseract locale
    (gratuito, gira sul VPS), non una chiamata AI; il testo estratto passa poi dallo
    stesso parser Mistral del testo digitato, quindi il suo costo finisce già sotto
    'mistral'. Solo la trascrizione vocale (Gemini/Vertex AI) e il parsing testo
    (Mistral) hanno un costo AI diretto e distinto.
    """
    ninety_days_ago = datetime.utcnow() - timedelta(days=90)

    rows = s.query(
        LlmUsageEvent.provider,
        LlmUsageEvent.model,
        func.count().label("req_count"),
        func.sum(LlmUsageEvent.total_tokens).label("total_tokens"),
        func.sum(func.coalesce(LlmUsageEvent.estimated_cost_amount, 0)).label("cost"),
    ).filter(
        LlmUsageEvent.occurred_at >= max(ninety_days_ago, LEDGER_EPOCH)
    ).group_by(LlmUsageEvent.provider, LlmUsageEvent.model).order_by(
        func.sum(func.coalesce(LlmUsageEvent.estimated_cost_amount, 0)).desc()
    ).all()

    total_cost = 0.0
    out_rows = []
    for provider, model, req_count, total_tokens, cost in rows:
        cost_usd = _f(cost, 4)
        total_cost += cost_usd
        out_rows.append({
            "provider": provider,
            "model": model,
            "requests": req_count,
            "total_tokens": int(total_tokens or 0),
            "cost_usd": cost_usd,
        })
    for row in out_rows:
        row["cost_share_pct"] = round(100 * row["cost_usd"] / total_cost, 1) if total_cost else 0.0

    return {"rows": out_rows, "total_cost_usd": round(total_cost, 4)}


def get_input_method_breakdown_90d(s: Session) -> dict[str, Any]:
    """Richieste/token LLM negli ultimi 90gg, per modalità di input (testo/voce/foto).

    Fonte: llm_usage_events.input_method (colonna aggiunta il 2026-07-14, NON
    retroattiva: le righe precedenti hanno input_method=NULL, etichettate qui
    "n/d" insieme alle operazioni per cui la modalità non si applica — es. i
    report weekly_plan/monthly_plan, generati su comando, non da un input utente
    testo/voce/foto).
    """
    ninety_days_ago = datetime.utcnow() - timedelta(days=90)

    rows = s.query(
        LlmUsageEvent.input_method,
        func.count().label("req_count"),
        func.sum(LlmUsageEvent.total_tokens).label("total_tokens"),
    ).filter(
        LlmUsageEvent.occurred_at >= max(ninety_days_ago, LEDGER_EPOCH)
    ).group_by(LlmUsageEvent.input_method).all()

    by_method: dict[str, dict[str, int]] = {}
    for method, req_count, total_tokens in rows:
        key = method or "n/d"
        by_method[key] = {"requests": req_count, "total_tokens": int(total_tokens or 0)}
    return by_method


def get_tour_funnel(s: Session) -> dict[str, Any]:
    """Skip e step di abbandono del tour guidato webapp (10 step demo).

    Fonte: colonne `tour_status`/`tour_step` su `users`, popolate da POST
    /api/track quando arrivano gli eventi tour_* (solo utenti con sessione
    autenticata — i visitatori anonimi non hanno mai avviato il tour).
    """
    total_started = s.query(User).filter(User.tour_status.isnot(None)).count()
    completed = s.query(User).filter(User.tour_status == "completed").count()
    skipped = s.query(User).filter(User.tour_status == "skipped").count()
    in_progress = s.query(User).filter(User.tour_status == "in_progress").count()

    step_rows = s.query(User.tour_step, func.count()).filter(
        User.tour_status.in_(["skipped", "in_progress"]), User.tour_step.isnot(None)
    ).group_by(User.tour_step).all()
    abandon_by_step = {step: cnt for step, cnt in step_rows}

    return {
        "total_started": total_started,
        "completed": completed,
        "skipped": skipped,
        "in_progress": in_progress,
        "completed_pct": round(100 * completed / total_started, 1) if total_started else 0.0,
        "skipped_pct": round(100 * skipped / total_started, 1) if total_started else 0.0,
        "abandon_by_step": abandon_by_step,
    }


def get_subscription_candidate_funnel(s: Session, days: int = 90) -> dict[str, Any]:
    """Funnel del rilevamento abbonamenti (src/subscription_detector.py).

    `satisfaction_pct` è la metrica di successo della feature: sui candidati per
    cui l'utente ha già preso una decisione (confermato o rifiutato), quanti ne
    ha voluti davvero. Non è un tasso di rilevamento (quello lo direbbe solo
    "candidati creati"), è un segnale di fiducia/precisione — se scende, vuol
    dire che i falsi positivi (bande di tolleranza troppo larghe, categorie
    keyword troppo permissive) stanno costando credibilità, non solo un tap.
    Fonte: subscription_candidates, popolata sia dall'hook live (bot.py) sia dal
    backfill storico (scripts/backfill_subscription_candidates.py) — questa
    metrica non li distingue, riflette lo stato complessivo del sistema.
    """
    since = datetime.utcnow() - timedelta(days=days)
    rows = s.query(
        SubscriptionCandidate.status, func.count()
    ).filter(SubscriptionCandidate.created_at >= since).group_by(
        SubscriptionCandidate.status
    ).all()
    by_status = {status: cnt for status, cnt in rows}

    pending = by_status.get("pending", 0)
    awaiting_confirm = by_status.get("awaiting_confirm", 0)
    confirmed = by_status.get("confirmed", 0)
    dismissed = by_status.get("dismissed", 0)
    decided = confirmed + dismissed

    return {
        "days": days,
        "total_detected": pending + awaiting_confirm + confirmed + dismissed,
        "pending": pending,
        "awaiting_confirm": awaiting_confirm,
        "confirmed": confirmed,
        "dismissed": dismissed,
        "satisfaction_pct": round(100 * confirmed / decided, 1) if decided else None,
    }


def get_expense_label_cluster_stats(s: Session, days: int = 30) -> dict[str, Any]:
    """Osservabilità della normalizzazione voci di spesa (src/expense_label_normalizer.py).

    Sistema fragile per design (ancora fissa + soglia rapidfuzz + guardrail categoria,
    tutto automatico, mai una conferma umana) — questa vista è la rete di sicurezza:
    senza, un peggioramento (soglia scalibrata male, guardrail troppo permissivo) resta
    invisibile finché qualcuno non lo nota per caso in un grafico.

    - `unlabeled_expenses`: spese Postgres senza `label_cluster_id` — dovrebbe tendere
      a zero dopo il backfill (`scripts/backfill_expense_label_clusters.py`); se cresce
      nel tempo, l'hook live in `create_expense` ha smesso di girare.
    - `singleton_clusters` vs `multi_clusters`: quanti cluster non si sono mai uniti a
      nulla. Non è di per sé un problema (può essere genuina varietà di spesa), ma un
      rapporto singleton/totale che cresce nel tempo segnala una soglia troppo rigida.
    - `new_clusters_period` vs `merges_period`: nella finestra, quante spese hanno aperto
      un cluster nuovo contro quante si sono unite a uno esistente — è il tasso di
      "successo" della normalizzazione nel periodo, non solo lo stato cumulativo.
      ATTENZIONE: subito dopo un'esecuzione del backfill storico, questa coppia è
      falsata — il backfill crea molti cluster nuovi (`ExpenseLabelCluster.created_at`
      = adesso) per spese vecchie (`Expense.created_at` = data originale, fuori dalla
      finestra), quindi `new_clusters_period` si gonfia e `merges_period` crolla verso
      zero senza che sia un problema reale. Il segnale torna affidabile una volta che
      la finestra (`days`) supera la data dell'ultimo backfill.
    """
    since = datetime.utcnow() - timedelta(days=days)

    total_clusters = s.query(func.count(ExpenseLabelCluster.id)).scalar() or 0
    unlabeled_expenses = (
        s.query(func.count(Expense.id)).filter(Expense.label_cluster_id.is_(None)).scalar() or 0
    )

    size_by_cluster = dict(
        s.query(Expense.label_cluster_id, func.count(Expense.id))
        .filter(Expense.label_cluster_id.isnot(None))
        .group_by(Expense.label_cluster_id)
        .all()
    )
    labeled_expenses = sum(size_by_cluster.values())
    singleton_clusters = sum(1 for size in size_by_cluster.values() if size == 1)
    multi_clusters = sum(1 for size in size_by_cluster.values() if size > 1)
    # Denominatore = cluster con almeno una spesa (len(size_by_cluster)), non
    # total_clusters: un cluster senza spese (possibile dopo una cancellazione)
    # diluirebbe la media senza motivo.
    populated_clusters = len(size_by_cluster)
    avg_cluster_size = round(labeled_expenses / populated_clusters, 2) if populated_clusters else None

    # Ogni spesa assegnata nel periodo o ha creato il proprio cluster (1 evento = 1
    # cluster nuovo) o si è unita a uno esistente (merge): il conteggio esatto delle
    # unioni è quindi "assegnazioni totali nel periodo" meno "cluster nuovi nel
    # periodo" — non serve un log eventi separato, `Expense.created_at` basta.
    new_clusters_period = (
        s.query(func.count(ExpenseLabelCluster.id))
        .filter(ExpenseLabelCluster.created_at >= since)
        .scalar() or 0
    )
    assignments_period = (
        s.query(func.count(Expense.id))
        .filter(Expense.created_at >= since, Expense.label_cluster_id.isnot(None))
        .scalar() or 0
    )
    merges_period = max(assignments_period - new_clusters_period, 0)

    top_clusters_rows = sorted(size_by_cluster.items(), key=lambda kv: kv[1], reverse=True)[:10]
    top_cluster_ids = [cid for cid, _ in top_clusters_rows]
    anchors = dict(
        s.query(ExpenseLabelCluster.id, ExpenseLabelCluster.anchor_text)
        .filter(ExpenseLabelCluster.id.in_(top_cluster_ids))
        .all()
    ) if top_cluster_ids else {}
    top_clusters = [
        {"anchor_text": anchors.get(cid, "?"), "size": size}
        for cid, size in top_clusters_rows
    ]

    return {
        "days": days,
        "total_clusters": total_clusters,
        "labeled_expenses": labeled_expenses,
        "unlabeled_expenses": unlabeled_expenses,
        "singleton_clusters": singleton_clusters,
        "multi_clusters": multi_clusters,
        "avg_cluster_size": avg_cluster_size,
        "new_clusters_period": new_clusters_period,
        "merges_period": merges_period,
        "top_clusters": top_clusters,
    }


# ---------------------------------------------------------------------------
# 13. Referral: leaderboard, reward, sblocco Lifetime Founder
# ---------------------------------------------------------------------------
def get_referral_metrics(s: Session, top_n: int = 20, recent_n: int = 50) -> dict[str, Any]:
    """Stato del sistema referral: KPI, classifica referrer, invii recenti.

    Le regole (giorni per invito, tetto di inviti premiati per il referrer, sblocco
    Lifetime Founder) sono applicate in `UserStore.create_referral_rewards`; qui si
    aggregano solo i dati già persistiti (tally_leads + referral_rewards), nessuna
    logica di business.
    """
    total_codes_generated = s.query(TallyLead).filter(TallyLead.referral_code.isnot(None)).count()
    total_referred_signups = s.query(TallyLead).filter(TallyLead.referred_by_code.isnot(None)).count()

    reward_rows = (
        s.query(ReferralReward.role, ReferralReward.status, func.count())
        .group_by(ReferralReward.role, ReferralReward.status)
        .all()
    )
    rewards = {"referred": {"pending": 0, "applied": 0}, "referrer": {"pending": 0, "applied": 0}}
    for role, status, cnt in reward_rows:
        if role in rewards and status in rewards[role]:
            rewards[role][status] = cnt

    lifetime_founder_unlocked = (
        s.query(TallyLead).filter(TallyLead.lifetime_founder_guaranteed.is_(True)).count()
    )

    # Classifica referrer: conteggio referred per referral_code, poi risoluzione
    # dell'email del referrer via join manuale (referred_by_code -> referral_code).
    referred_counts = dict(
        s.query(TallyLead.referred_by_code, func.count())
        .filter(TallyLead.referred_by_code.isnot(None))
        .group_by(TallyLead.referred_by_code)
        .all()
    )
    top_referrers: list[dict[str, Any]] = []
    if referred_counts:
        codes = list(referred_counts.keys())
        referrer_leads = (
            s.query(TallyLead)
            .filter(TallyLead.referral_code.in_(codes))
            .all()
        )
        leads_by_code = {lead.referral_code: lead for lead in referrer_leads}
        ranked = sorted(referred_counts.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
        for code, count in ranked:
            lead = leads_by_code.get(code)
            top_referrers.append({
                "referral_code": code,
                "email": lead.email if lead else None,
                "referred_count": count,
                "lifetime_founder_guaranteed": bool(lead and lead.lifetime_founder_guaranteed),
            })

    recent_signups = (
        s.query(TallyLead)
        .filter(TallyLead.referred_by_code.isnot(None))
        .order_by(TallyLead.received_at.desc())
        .limit(recent_n)
        .all()
    )
    referrer_codes = {lead.referred_by_code for lead in recent_signups}
    referrer_emails = {
        lead.referral_code: lead.email
        for lead in s.query(TallyLead).filter(TallyLead.referral_code.in_(referrer_codes)).all()
    } if referrer_codes else {}
    recent = [
        {
            "email": lead.email,
            "received_at": lead.received_at,
            "referrer_email": referrer_emails.get(lead.referred_by_code),
            "beta_account_granted": lead.beta_account_granted,
        }
        for lead in recent_signups
    ]

    return {
        "total_codes_generated": total_codes_generated,
        "total_referred_signups": total_referred_signups,
        "rewards": rewards,
        "lifetime_founder_unlocked": lifetime_founder_unlocked,
        "top_referrers": top_referrers,
        "recent_signups": recent,
    }


# ---------------------------------------------------------------------------
# 14. Drill-down per singolo utente
# ---------------------------------------------------------------------------
def get_user_detail(s: Session, chat_id: str) -> dict[str, Any] | None:
    """Timeline completa del singolo utente per la pagina di drill-down/supporto."""
    user = s.query(User).filter(User.chat_id == chat_id).first()
    if not user:
        return None

    plan = s.query(UserPlan).filter(UserPlan.chat_id == chat_id).first()

    tx = s.query(ChatMessage.created_at).filter(
        ChatMessage.chat_id == chat_id,
        ChatMessage.role == "bot",
        ChatMessage.metadata_json.isnot(None),
    ).order_by(ChatMessage.created_at).all()
    tx_timestamps = [t[0] for t in tx if t[0]]
    first_tx = tx_timestamps[0] if tx_timestamps else None
    tx_count = len(tx_timestamps)

    tokens_total = s.query(
        func.coalesce(func.sum(LlmUsageEvent.total_tokens), 0)
    ).filter(LlmUsageEvent.chat_id == chat_id).scalar() or 0
    cost_total = _f(s.query(
        func.coalesce(func.sum(LlmUsageEvent.estimated_cost_amount), 0.0)
    ).filter(LlmUsageEvent.chat_id == chat_id).scalar(), 6)
    # "Ultima Attività" reale = ultimo messaggio inviato dall'utente (role="user"),
    # non l'ultimo LlmUsageEvent (vedi commento gemello in get_token_usage_per_user).
    last_active = s.query(func.max(ChatMessage.created_at)).filter(
        ChatMessage.chat_id == chat_id,
        ChatMessage.role == "user",
    ).scalar()

    feedback_count = s.query(Feedback).filter(Feedback.chat_id == chat_id).count()

    time_to_first_days = None
    if first_tx and user.created_at:
        time_to_first_days = round((first_tx - user.created_at).total_seconds() / 86400, 2)

    return {
        "chat_id": user.chat_id,
        "username": user.username or user.chat_id,
        "created_at": user.created_at,
        "is_active": user.is_active,
        "storage_backend": user.storage_backend,
        "setup_status": user.setup_status,
        "onboarding_step": user.onboarding_step,
        "onboarding_completed_at": user.onboarding_completed_at,
        "plan_type": plan.plan_type if plan else "free",
        "is_trial": plan.is_trial if plan else False,
        "trial_ends_at": plan.trial_ends_at if plan else None,
        "tokens_reset_at": plan.tokens_reset_at if plan else None,
        "first_tx_at": first_tx,
        "time_to_first_days": time_to_first_days,
        "tx_count": tx_count,
        "last_active": last_active,
        "tokens_total": int(tokens_total),
        "cost_total_usd": cost_total,
        "feedback_count": feedback_count,
    }
