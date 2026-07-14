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
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from src.user_store import (
    ChatMessage,
    DailyMetrics,
    Feedback,
    JobRun,
    LlmUsageEvent,
    PlanChange,
    TallyLead,
    TxEvent,
    User,
    UserPlan,
)

# Soglia storica del ledger token: coerente con la dashboard esistente, si
# considerano solo gli eventi dal 2026-05-01 in avanti (prima i dati non erano
# affidabili).
LEDGER_EPOCH = datetime(2026, 5, 1)

# Prezzo del piano Pro usato per stimare l'MRR. Non è un dato di prodotto salvato
# a DB: va impostato via env `PRO_PRICE_EUR` e aggiornato se cambia il listino.
PRO_PRICE_EUR = float(os.getenv("PRO_PRICE_EUR", "4.99"))


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


# ---------------------------------------------------------------------------
# 1. KPI di overview + grafico ledger token (estratto da index())
# ---------------------------------------------------------------------------
def get_overview_kpis(s: Session) -> dict[str, Any]:
    """KPI principali della dashboard: utenti, feedback, token, costi, AI metrics.

    Replica la logica storica di `index()` così che la route diventi un semplice
    orchestratore. Ritorna un dict serializzabile per il template.
    """
    now = datetime.utcnow()
    ten_days_ago = now - timedelta(days=10)
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
    rows = s.query(
        func.date(LlmUsageEvent.occurred_at),
        func.sum(LlmUsageEvent.prompt_tokens),
        func.sum(LlmUsageEvent.completion_tokens),
        func.sum(LlmUsageEvent.total_tokens),
    ).filter(
        LlmUsageEvent.occurred_at >= max(ten_days_ago, LEDGER_EPOCH)
    ).group_by(func.date(LlmUsageEvent.occurred_at)).all()

    chart_data: dict[str, dict[str, int]] = {}
    for x in range(10):
        d = (now - timedelta(days=9 - x)).date()
        chart_data[d.isoformat()] = {"prompt": 0, "completion": 0, "total": 0}
    for d_val, pt, ct, tt in rows:
        d_str = str(d_val)
        if d_str in chart_data:
            chart_data[d_str]["prompt"] += int(pt or 0)
            chart_data[d_str]["completion"] += int(ct or 0)
            chart_data[d_str]["total"] += int(tt or 0)

    labels = list(chart_data.keys())
    data_prompt = [v["prompt"] for v in chart_data.values()]
    data_completion = [v["completion"] for v in chart_data.values()]
    data_total = [v["total"] for v in chart_data.values()]

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

    rows = s.query(
        func.date(LlmUsageEvent.occurred_at).label("d"),
        LlmUsageEvent.operation,
        func.coalesce(UserPlan.plan_type, "free").label("plan_type"),
        func.count().label("req_count"),
        func.avg(LlmUsageEvent.total_tokens).label("avg_tokens"),
        func.sum(case((LlmUsageEvent.total_tokens > 0, 1), else_=0)).label("success_count"),
    ).outerjoin(
        UserPlan, LlmUsageEvent.chat_id == UserPlan.chat_id
    ).filter(
        LlmUsageEvent.occurred_at >= max(ninety_days_ago, LEDGER_EPOCH)
    ).group_by(
        func.date(LlmUsageEvent.occurred_at),
        LlmUsageEvent.operation,
        func.coalesce(UserPlan.plan_type, "free"),
    ).all()

    requests_by_op: dict[str, dict[str, dict[str, int]]] = {}
    token_stats: dict[str, dict[str, Any]] = {}
    conversion: dict[str, dict[str, Any]] = {}

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

        conversion[op][plan]["ok"] += int(success_count or 0)
        conversion[op][plan]["tot"] += req_count

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
        func.max(LlmUsageEvent.occurred_at).label("last_seen"),
    ).outerjoin(
        User, User.chat_id == LlmUsageEvent.chat_id
    ).group_by(
        LlmUsageEvent.chat_id, User.username
    ).order_by(func.sum(LlmUsageEvent.total_tokens).desc()).all()

    out = []
    for chat_id, username, req_count, total_tokens, cost, last_seen in rows:
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
def get_monthly_token_usage(s: Session, months: int = 6) -> dict[str, Any]:
    """Consumo token per mese e per utente, con statistiche per tarare le quote.

    Ritorna:
    - `months`: elenco ordinato dei bucket 'YYYY-MM' considerati
    - `per_user`: righe per utente con consumo per mese e totale
    - `monthly_avg`: media token per utente attivo, per mese
    - `current_month_stats`: avg/median/p90/max del mese corrente (per decidere
      il tetto free, oggi 150k)
    """
    now = datetime.utcnow()
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
    """chat_id -> timestamp ultima attività (LLM event; fallback chat_messages)."""
    last: dict[str, datetime] = {}
    for chat_id, ts in s.query(
        LlmUsageEvent.chat_id, func.max(LlmUsageEvent.occurred_at)
    ).group_by(LlmUsageEvent.chat_id).all():
        if ts:
            last[chat_id] = ts
    for chat_id, ts in s.query(
        ChatMessage.chat_id, func.max(ChatMessage.created_at)
    ).group_by(ChatMessage.chat_id).all():
        if ts and (chat_id not in last or ts > last[chat_id]):
            last[chat_id] = ts
    return last


def get_retention(s: Session, windows: tuple[int, ...] = (7, 14, 60)) -> dict[str, Any]:
    """Retention di prodotto su 7/14/60 giorni.

    - `rolling_active`: quanti utenti hanno avuto attività negli ultimi N giorni
      (stickiness "usano ancora l'app adesso").
    - `cohort_retention`: tra gli utenti il cui account ha almeno N giorni,
      quanti sono rimasti attivi fino ad almeno N giorni dopo la registrazione.
    """
    now = datetime.utcnow()
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
def get_funnel_revenue(s: Session) -> dict[str, Any]:
    """Metriche di business: distribuzione piani, MRR proxy, churn, unit economics."""
    now = datetime.utcnow()
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
    mrr = round(paying_pro * PRO_PRICE_EUR, 2)

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
def get_engagement_acquisition(s: Session, signup_days: int = 30) -> dict[str, Any]:
    """DAU/WAU/MAU, trend registrazioni, distribuzione backend, waitlist."""
    now = datetime.utcnow()

    def _active_since(days: int) -> int:
        since = now - timedelta(days=days)
        return s.query(func.count(func.distinct(LlmUsageEvent.chat_id))).filter(
            LlmUsageEvent.occurred_at >= since
        ).scalar() or 0

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
# Schedule atteso, mirror di bot.py::_start_scheduler + del scheduled job
# (scheduled job). Serve a rilevare i job attesi ma mai eseguiti oggi ("no-show").
JOB_SCHEDULE: list[dict[str, Any]] = [
    {"job_id": "db_backup", "label": "Backup DB (pg_dump→B2)", "kind": "daily", "hour": 2, "minute": 30},
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
                expected_time = now.replace(
                    hour=spec["hour"], minute=spec["minute"], second=0, microsecond=0
                )

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


def get_tx_success_by_type_method(s: Session, days: int = 30) -> dict[str, Any]:
    """Successi/fallimenti di parsing per tipo transazione x modalità di input.

    Successo = l'utente ha cliccato Conferma e la transazione è stata salvata
    (outcome='confirmed' in tx_events). Aggrega anche cancellati e falliti per
    calcolare il success-rate. Fonte: tx_events, rispecchiata da bot.py/app.py
    accanto agli eventi PostHog esistenti.
    """
    since = datetime.utcnow() - timedelta(days=days)
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
    totals_confirmed = totals_all = 0
    for tx_type in types:
        for method in methods:
            cell = matrix.get(tx_type, {}).get(method)
            if not cell:
                continue
            total = sum(cell.values())
            confirmed = cell.get("confirmed", 0)
            totals_confirmed += confirmed
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

    return {
        "days": days,
        "rows": rows_out,
        "types": types,
        "methods": methods,
        "overall_success_rate_pct": round(100 * totals_confirmed / totals_all, 1) if totals_all else 0.0,
        "overall_total": totals_all,
    }


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


# ---------------------------------------------------------------------------
# 13. Drill-down per singolo utente
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
    last_active = s.query(func.max(LlmUsageEvent.occurred_at)).filter(
        LlmUsageEvent.chat_id == chat_id
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
