from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from config import Config
from src.llm_usage_tracker import (
    build_request_key,
    estimate_reserved_tokens,
    normalize_usage_metadata,
)
from src.mistral_client import MistralClient
from src.report_builder import MonthlyPlanBuilder, MonthlyPlanData, WeeklyPlanBuilder, WeeklyPlanData
from src.user_store import QuotaExceededError, UserStore

logger = logging.getLogger("financial_agent.plan_actions")


@dataclass
class PlanGenerationResult:
    plan_kind: str
    plan_text: str
    report_type: str
    report_date: Any
    share_token: str | None
    report_url: str | None
    plan_data: WeeklyPlanData | MonthlyPlanData
    notification_text: str


def serialize_weekly_data(data: WeeklyPlanData) -> dict:
    """Serializza WeeklyPlanData in dict JSON-safe per lo storico web."""
    budget_results = {}
    for cat, result in data.budget_results.items():
        budget_results[cat] = {
            "budget_monthly": result.budget_monthly,
            "spent_month": result.spent_month,
            "residuo": result.residuo,
            "overrun": result.overrun,
            "limite_reale": result.limite_reale,
            "soft_cap": result.soft_cap,
            "status": result.status,
        }

    subs = []
    for subscription in data.due_subscriptions:
        subs.append(
            {
                "name": subscription.get("name", ""),
                "amount": float(subscription.get("amount") or 0),
                "due_date": subscription["due_date"].isoformat() if subscription.get("due_date") else None,
            }
        )

    return {
        "type": "weekly",
        "reference_date": data.reference_date.isoformat(),
        "weeks_remaining": data.weeks_remaining,
        "total_spent_month": data.total_spent_month,
        "total_income_month": data.total_income_month,
        "total_accounts": data.total_accounts,
        "subs_total_week": data.subs_total_week,
        "due_subscriptions": subs,
        "budget_results": budget_results,
        "no_budget_cats": data.no_budget_cats,
        "spent_by_cat": data.spent_by_cat,
    }


def serialize_monthly_data(data: MonthlyPlanData) -> dict:
    """Serializza MonthlyPlanData in dict JSON-safe per lo storico web."""
    subs = []
    for subscription in data.subscriptions_month:
        subs.append(
            {
                "name": subscription.get("name", ""),
                "amount": float(subscription.get("amount") or 0),
                "due_date": subscription["due_date"].isoformat() if subscription.get("due_date") else None,
            }
        )

    return {
        "type": "monthly",
        "reference_date": data.reference_date.isoformat(),
        "target_month": data.target_month.isoformat(),
        "suggested_targets": data.suggested_targets,
        "budget_by_cat": data.budget_by_cat,
        "subs_total_month": data.subs_total_month,
        "subscriptions_month": subs,
        "income_forecast": data.income_forecast,
        "savings_goal": data.savings_goal,
        "total_spent_last_month": data.total_spent_last_month,
        "total_accounts": data.total_accounts,
        "spent_by_cat": data.spent_by_cat,
        "monthly_history": data.monthly_history,
    }


def _generate_plan_with_ai(
    *,
    chat_id: str,
    plan_kind: str,
    prompt_text: str,
    prompt_label: str,
    request_suffix: str,
    fallback_text: str,
    user_store: UserStore,
) -> str:
    request_key = build_request_key(chat_id, plan_kind, request_suffix)
    reservation_created = False

    try:
        user_store.reserve_llm_tokens(
            chat_id=chat_id,
            request_key=request_key,
            operation=plan_kind,
            provider="mistral",
            model=Config.MISTRAL_SMALL_MODEL,
            reserved_tokens=estimate_reserved_tokens(plan_kind),
        )
        reservation_created = True
    except QuotaExceededError:
        raise
    except Exception as exc:
        logger.warning("[User %s] Reservation %s non creata: %s", chat_id, plan_kind, exc)

    try:
        mistral = MistralClient()
        generator = mistral.generate_weekly_plan if plan_kind == "weekly_plan" else mistral.generate_monthly_plan
        plan_text, usage = generator(prompt_text, prompt_label)
        usage = normalize_usage_metadata(usage)

        if usage.get("total_tokens", 0) > 0:
            try:
                user_store.finalize_llm_usage(
                    chat_id=chat_id,
                    request_key=request_key,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                    provider=usage.get("provider", "mistral"),
                    model=usage.get("model", Config.MISTRAL_SMALL_MODEL),
                    operation=plan_kind,
                )
            except Exception as exc:
                logger.warning("[User %s] finalize_llm_usage %s fallita: %s", chat_id, plan_kind, exc)
        elif reservation_created:
            try:
                user_store.release_llm_reservation(chat_id, request_key, reason="no_usage_metadata")
            except Exception:
                pass

        return plan_text
    except QuotaExceededError:
        raise
    except Exception as exc:
        logger.warning("[User %s] Generazione %s fallita, uso fallback: %s", chat_id, plan_kind, exc)
        if reservation_created:
            try:
                user_store.release_llm_reservation(chat_id, request_key, reason=str(exc))
            except Exception:
                pass
        return fallback_text


def generate_weekly_plan_action(*, chat_id: str, storage, user_store: UserStore) -> PlanGenerationResult:
    builder = WeeklyPlanBuilder()
    plan_data = builder.build(storage)

    ref = plan_data.reference_date
    monday_this_week = ref - timedelta(days=ref.weekday())
    week_end = monday_this_week + timedelta(days=6)  # domenica della settimana corrente
    week_label = f"{monday_this_week.strftime('%d/%m')} → {week_end.strftime('%d/%m')}"

    # Idempotency: se il piano settimanale per oggi esiste già, skip Mistral
    cached = user_store.get_report_by_date(str(chat_id), "weekly", ref)
    if cached:
        logger.info("[User %s] Piano settimanale già generato per %s, skip Mistral", chat_id, ref)
        return PlanGenerationResult(
            plan_kind="weekly",
            plan_text=cached["text_content"],
            report_type="weekly",
            report_date=ref,
            share_token=cached["share_token"],
            report_url=f"{Config.WEBAPP_BASE_URL}/reports/{cached['share_token']}" if cached["share_token"] else None,
            plan_data=plan_data,
            notification_text="📱 *Webapp* — Ho generato il tuo piano settimanale. Aprilo nei report per i dettagli completi.",
        )

    plan_text = _generate_plan_with_ai(
        chat_id=chat_id,
        plan_kind="weekly_plan",
        prompt_text=plan_data.to_prompt_text(),
        prompt_label=week_label,
        request_suffix=ref.isoformat(),
        fallback_text=builder.build_fallback_text(plan_data),
        user_store=user_store,
    )

    share_token = user_store.save_report(
        user_id=str(chat_id),
        report_type="weekly",
        report_date=plan_data.reference_date,
        text_content=plan_text,
        report_data=serialize_weekly_data(plan_data),
    )
    report_url = f"{Config.WEBAPP_BASE_URL}/reports/{share_token}" if share_token else None

    return PlanGenerationResult(
        plan_kind="weekly",
        plan_text=plan_text,
        report_type="weekly",
        report_date=plan_data.reference_date,
        share_token=share_token,
        report_url=report_url,
        plan_data=plan_data,
        notification_text="📱 *Webapp* — Ho generato il tuo piano settimanale. Aprilo nei report per i dettagli completi.",
    )


def generate_monthly_plan_action(
    *,
    chat_id: str,
    storage,
    user_store: UserStore,
    category_overrides: dict[str, float] | None = None,
) -> PlanGenerationResult:
    builder = MonthlyPlanBuilder()
    plan_data = builder.build(storage, category_overrides=category_overrides)

    target_month = plan_data.target_month
    months_it = [
        "",
        "Gennaio",
        "Febbraio",
        "Marzo",
        "Aprile",
        "Maggio",
        "Giugno",
        "Luglio",
        "Agosto",
        "Settembre",
        "Ottobre",
        "Novembre",
        "Dicembre",
    ]
    month_label = f"{months_it[target_month.month]} {target_month.year}"

    # Idempotency: se il piano mensile per il mese target esiste già, skip Mistral
    cached = user_store.get_report_by_date(str(chat_id), "monthly", target_month)
    if cached:
        logger.info("[User %s] Piano mensile già generato per %s, skip Mistral", chat_id, target_month)
        return PlanGenerationResult(
            plan_kind="monthly",
            plan_text=cached["text_content"],
            report_type="monthly",
            report_date=target_month,
            share_token=cached["share_token"],
            report_url=f"{Config.WEBAPP_BASE_URL}/reports/{cached['share_token']}" if cached["share_token"] else None,
            plan_data=plan_data,
            notification_text=(
                "📱 *Webapp* — Ho generato il tuo piano mensile. Aprilo nei report e poi passa in "
                "*Spazio → Categorie* per rivedere i budget consigliati."
            ),
        )

    plan_text = _generate_plan_with_ai(
        chat_id=chat_id,
        plan_kind="monthly_plan",
        prompt_text=plan_data.to_prompt_text(),
        prompt_label=month_label,
        request_suffix=f"{target_month.year}-{target_month.month:02d}",
        fallback_text=builder.build_fallback_text(plan_data),
        user_store=user_store,
    )

    share_token = user_store.save_report(
        user_id=str(chat_id),
        report_type="monthly",
        report_date=plan_data.target_month,
        text_content=plan_text,
        report_data=serialize_monthly_data(plan_data),
    )
    report_url = f"{Config.WEBAPP_BASE_URL}/reports/{share_token}" if share_token else None

    return PlanGenerationResult(
        plan_kind="monthly",
        plan_text=plan_text,
        report_type="monthly",
        report_date=plan_data.target_month,
        share_token=share_token,
        report_url=report_url,
        plan_data=plan_data,
        notification_text=(
            "📱 *Webapp* — Ho generato il tuo piano mensile. Aprilo nei report e poi passa in "
            "*Spazio → Categorie* per rivedere i budget consigliati."
        ),
    )
