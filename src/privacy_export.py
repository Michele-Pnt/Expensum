"""Costruzione dei dati di export GDPR (Art. 15/20), condivisa tra dashboard Flask e bot Telegram.

Tenuta separata da entrambi i client per evitare di duplicare la logica di
estrazione: chi la chiama (Flask o python-telegram-bot) si occupa solo del
trasporto (HTTP response vs documento Telegram).
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.user_store import User, ChatMessage, LlmUsageEvent
from src.storage.postgres_storage import PostgresStorage

PRIVACY_RIGHTS_NOTICE_IT = (
    "Hai diritto di: accedere ai tuoi dati personali (Art. 15), richiederne la "
    "rettifica (Art. 16), la cancellazione (Art. 17), la limitazione del "
    "trattamento (Art. 18), riceverli in formato portabile (Art. 20) e opporti "
    "al trattamento (Art. 21). Per esercitare questi diritti, oltre agli "
    "strumenti self-service, puoi scrivere a privacy@expensum.it. "
    "Tempo di risposta: standard entro 1 mese, target 24h."
)

NOTION_FINANCIAL_DATA_NOTE = (
    "I tuoi dati finanziari sono salvati nel tuo workspace Notion personale, "
    "di tua proprietà e accessibile direttamente su notion.so. Expensum non "
    "ne detiene una copia."
)

NOTION_CSV_UNAVAILABLE_MESSAGE = (
    "I tuoi dati finanziari sono nel tuo workspace Notion personale: "
    "esportali direttamente da notion.so."
)


def build_export_json(session: Session, user: User) -> dict:
    """Art. 15 GDPR — struttura completa dei dati personali di `user`."""
    chat_id = user.chat_id
    account = {
        "chat_id": user.chat_id,
        "email": user.email,
        "username": user.username,
        "storage_backend": user.storage_backend,
        "is_active": user.is_active,
        "notifications_enabled": user.notifications_enabled,
        "preferred_language": user.preferred_language,
        "currency": user.currency,
        "timezone": user.timezone,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }

    if user.storage_backend == "postgres":
        storage = PostgresStorage(session=session, user_id=chat_id)
        start = user.created_at.date() if user.created_at else date(2020, 1, 1)
        today = date.today()
        financial_data = {
            "expenses": storage.fetch_all_transactions(start, today),
            "incomes": storage.fetch_income(start, today),
            "accounts": storage.fetch_accounts(),
            "subscriptions": storage.fetch_subscriptions(),
            "monthly_balances": storage.fetch_monthly_balances(start, today),
        }
    else:
        financial_data = {"note": NOTION_FINANCIAL_DATA_NOTE}

    chat_history = [
        {
            "source": m.source,
            "role": m.role,
            "text": m.text,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in session.query(ChatMessage).filter(ChatMessage.chat_id == chat_id).all()
    ]

    usage_events = session.query(LlmUsageEvent).filter(LlmUsageEvent.chat_id == chat_id).all()
    usage_data = {
        "total_events": len(usage_events),
        "total_prompt_tokens": sum(e.prompt_tokens for e in usage_events),
        "total_completion_tokens": sum(e.completion_tokens for e in usage_events),
    }

    return {
        "export_metadata": {
            "generated_at": datetime.utcnow().isoformat(),
            "user_id": chat_id,
            "format": "json",
        },
        "account": account,
        "financial_data": financial_data,
        "chat_history": chat_history,
        "usage_data": usage_data,
        "your_rights": PRIVACY_RIGHTS_NOTICE_IT,
    }


def build_csv_rows(session: Session, user: User) -> Optional[list[tuple]]:
    """Art. 20 GDPR — righe (type, date, amount, name, category, account) per CSV.

    Ritorna None se il backend è Notion (i dati non sono detenuti da Expensum,
    vedi NOTION_CSV_UNAVAILABLE_MESSAGE).
    """
    if user.storage_backend != "postgres":
        return None

    chat_id = user.chat_id
    storage = PostgresStorage(session=session, user_id=chat_id)
    start = user.created_at.date() if user.created_at else date(2020, 1, 1)
    today = date.today()
    accounts_by_id = {a["id"]: a["name"] for a in storage.fetch_accounts()}

    rows: list[tuple] = []
    for e in storage.fetch_all_transactions(start, today):
        rows.append(("expense", e["date"], e["amount"], e["name"], e["category"],
                     accounts_by_id.get(e["account_id"], "")))
    for i in storage.fetch_income(start, today):
        rows.append(("income", i["date"], i["amount"], i["name"], i.get("income_type") or "",
                     accounts_by_id.get(i["account_id"], "")))
    for sub in storage.fetch_subscriptions():
        rows.append(("subscription", sub.get("last_billed") or "", sub["amount"], sub["name"], "",
                     accounts_by_id.get(sub.get("account_id"), "")))
    return rows


CSV_HEADER = ["type", "date", "amount", "name", "category", "account"]
