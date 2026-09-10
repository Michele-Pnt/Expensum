"""
bot.py — Bot Telegram bidirezionale per l'inserimento spese via testo libero.

L'utente scrive messaggi naturali come:
  "ieri pizza con amici 25€"
  "ho speso 67 euro al supermercato"
  "netflix"

Il bot:
  1. Parsa il messaggio con l'LLM (Ollama o Gemini)
  2. Mostra un riepilogo con bottoni di conferma
  3. Scrive la spesa su Notion alla conferma

Avvio:
  .venv/bin/python3 bot.py                  # Long-polling (sviluppo locale)
  .venv/bin/python3 bot.py --webhook URL    # Webhook (produzione)
"""

import argparse
import asyncio
import csv
import io
import logging
import shutil
import sys
import json
import time
import threading
from datetime import date, datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo
from cachetools import TTLCache
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED
import requests

from src.billing_utils import get_next_billing_date
from src.application.account_matching import resolve_account_hint as _resolve_account_hint
from src.application.structured_logging import log_exception
from src.privacy_export import build_export_json, build_csv_rows, CSV_HEADER
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.constants import ParseMode
from telegram.request import HTTPXRequest
from telegram.error import NetworkError
from google.genai import types
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ConversationHandler,
)

import os
import tempfile

from config import Config, setup_logging
from src.expense_parser import ExpenseParser
from src import category_matcher
from src import subscription_detector
from src.notion_client import NotionFinanceClient
from src.storage.base import FinancialStorage
from src.storage.notion_storage import NotionStorage                                                                                                         
from src.storage.postgres_storage import PostgresStorage
from src.rate_limiter import is_rate_limited
from src.user_store import UserStore, User
from src.ocr_client import OcrClient, OCRError
from src.vertex_ai_client import get_vertex_ai_client
from src.category_sync import refresh_category_averages
from src.budget_alert import evaluate_budget_alert, classify_budget_band, get_category_spent_and_budget
from src.notification_service import create_notification
from src.storage.models import Expense, Notification
from src.llm_usage_tracker import build_request_key, estimate_reserved_tokens, normalize_usage_metadata
from src.report_builder import WeeklyPlanBuilder, WeeklyPlanData, MonthlyPlanBuilder, MonthlyPlanData
from src.report_schema import render_plain_text
from src.mistral_client import MistralClient
from src.report_notify import display_name, notify_webapp_report
from src import analytics
from src import brevo_client
from src.unsubscribe_token import make_unsubscribe_token
from src.gamification import engine as gamification
from src.gamification.notifications import build_messages as build_achievement_messages
from src.trial_lifecycle import (
    compute_days_since_trial_start,
    steps_pending,
    count_user_expenses_since_signup,
    build_drip_message,
    DRIP_TEMPLATES,
    DRIP_STEPS,
    UPGRADE_CTA_STEPS,
)

logger = logging.getLogger("financial_agent.bot")

# ---------------------------------------------------------------------------
# Stati della conversazione
# ---------------------------------------------------------------------------
WAITING_INVITE_CODE, WAITING_API_KEY, WAITING_EXPENSE_DB, WAITING_INCOME_DB, WAITING_CATEGORIES_DB, WAITING_MONTHLY_DB, WAITING_ACCOUNTS_DB = range(7)

LOGOUT_CONFIRM_CB = "logout_confirm"
LOGOUT_CANCEL_CB = "logout_cancel"
REACTIVATE_CB = "reactivate_account"

# Menu /impostazioni — Privacy e dati / Preferenze
IMP_MENU_PRIVACY_CB = "imp_menu_privacy"
IMP_MENU_PREFS_CB = "imp_menu_prefs"
IMP_MENU_BACK_CB = "imp_menu_back"
PRIVACY_EXPORT_CB = "privacy_export"
PRIVACY_DELETE_START_CB = "privacy_delete_start"
PRIVACY_NOTIF_TOGGLE_CB = "privacy_notif_toggle"
PRIVACY_POLICY_CB = "privacy_policy_link"
PRIVACY_TERMS_CB = "privacy_terms_placeholder"
PREFS_EDIT_START_CB = "prefs_edit_start"

# ---------------------------------------------------------------------------
# Stati wizard onboarding — 5 step: age gate → lingua → stile vita →
#                                   notifiche → conferma
# ---------------------------------------------------------------------------
OB_AGE_GATE = 20
OB_LANGUAGE = 10
OB_HOBBIES = 15
OB_NOTIFICATIONS = 17
OB_CONFIRM = 19

# ---------------------------------------------------------------------------
# Stati della inizializzazione del template
# ---------------------------------------------------------------------------
SETUP_STATUS_WAIT_ACCOUNTS = "WAIT_ACCOUNTS"
SETUP_STATUS_DONE = "DONE"


# Cache globali (inizializzate al primo messaggio)
_notion: NotionFinanceClient | None = None
_parser: ExpenseParser | None = None

# Inizializziamo il database utenti (usando l'URL che abbiamo messo in Config)
# pool_size/max_overflow dimensionati per il traffico bot (vedi analisi 2026-07-16:
# max_connections Postgres=30 condiviso con la dashboard, che ha il suo pool separato)
_user_store = UserStore(db_url=Config.DATABASE_URL, pool_size=10, max_overflow=5)

class _StorageClientCache(TTLCache):
    """TTLCache che chiude la sessione SQLAlchemy quando una entry scade o viene sfrattata.

    cachetools non chiama mai `close()` sui valori rimossi: senza questo hook, ogni
    PostgresStorage uscito dalla cache lascia la connessione agganciata al pool finché
    il garbage collector di CPython non la libera (comportamento non deterministico —
    vedi incidente QueuePool del 2026-07-16).

    Servono DUE hook distinti perché cachetools usa due percorsi di rimozione diversi:
    - `expire()` per la scadenza TTL, che internamente chiama `Cache.__delitem__` in modo
      non polimorfico (bypassa un `__delitem__` sovrascritto in questa sottoclasse);
    - `popitem()`/`pop()`/`del` per l'eviction da maxsize o la rimozione esplicita, che
      invece passano da `self.__delitem__` e quindi arrivano già all'override sotto.
    """

    def _close_if_postgres(self, value) -> None:
        if isinstance(value, PostgresStorage):
            value._session.close()

    def expire(self, time=None):
        expired = super().expire(time)
        for _key, value in expired:
            self._close_if_postgres(value)
        return expired

    def __delitem__(self, key):
        value = self.get(key)
        self._close_if_postgres(value)
        super().__delitem__(key)


# Cache client storage: TTL 30 min, max 200 utenti (VPS Hetzner CX23 — 4GB RAM)
_storage_clients: TTLCache = _StorageClientCache(maxsize=200, ttl=1800)


def _track_event(chat_id: str, event: str, properties: dict | None = None) -> None:
    """Wrapper attorno a analytics.track che tagga sempre platform='telegram'.

    Permette di distinguere in PostHog gli eventi originati dal bot da quelli
    della webapp, anche per eventi (es. expense_tracked) emessi da entrambi.
    """
    analytics.track(chat_id, event, {**(properties or {}), "platform": "telegram"})


def _safe_json_load(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else None
    except Exception:
        return None

def _get_storage(chat_id: str) -> FinancialStorage:
      """Ritorna il client di storage specifico per l'utente, creandolo se manca."""                                                                           
      chat_id = str(chat_id)

      if chat_id in _storage_clients:
          cached = _storage_clients[chat_id]
          if isinstance(cached, PostgresStorage):
              # La sessione è riusata cross-richiesta (vedi _StorageClientCache sopra),
              # quindi la identity map di SQLAlchemy può contenere righe caricate PRIMA
              # di una scrittura fatta da un'altra sessione (es. la webapp Flask) sullo
              # stesso record. expire_all() forza un refresh alla prossima lettura: con
              # Postgres in READ COMMITTED la nuova query vede sempre l'ultimo commit,
              # quindi basta questo — non serve una sessione nuova per operazione.
              cached._session.expire_all()
          return cached

      user = _user_store.get_user(chat_id)

      if user.storage_backend == "postgres":                                                                                                                   
          session = _user_store.Session()
          storage = PostgresStorage(session=session, user_id=chat_id)                                                                                          
      else:                                                                                                                                                    
          # Backend Notion — comportamento attuale
          api_key = user.notion_access_token                                                                                                                   
          db_schemas = _user_store.get_database_schemas(chat_id)
          schemas = {}
          for db_key, schema_data in db_schemas.items():
              schemas[db_key] = {
                  "raw": _safe_json_load(schema_data.get("properties")),
                  "mapped": _safe_json_load(schema_data.get("mapped"))
              }
          client = NotionFinanceClient(
              api_key=api_key,                                                                                                                                 
              expense_db_id=user.expense_db_id,
              income_db_id=user.income_db_id,                                                                                                                  
              categories_db_id=user.categories_db_id,
              monthly_balance_db_id=user.monthly_balance_db_id,                                                                                                
              accounts_db_id=user.accounts_db_id,
              subscriptions_db_id=user.subscriptions_db_id,                                                                                                    
              pay_transfer_db_id=user.pay_transfer_db_id,
              db_schemas=schemas,                                                                                                                              
          )       
          storage = NotionStorage(client, store=_user_store, user_id=chat_id)

      _storage_clients[chat_id] = storage
      return storage

def _get_parser(chat_id: str) -> ExpenseParser:
    """Crea un parser con categorie lette da user_categories (DB locale, < 1ms)."""
    chat_id = str(chat_id)
    categories_with_desc = _user_store.get_user_categories_with_descriptions(chat_id)
    categories = [c["name"] for c in categories_with_desc]
    category_descriptions = {
        c["name"]: c["description_summary"] for c in categories_with_desc if c["description_summary"]
    }
    income_categories_with_desc = _user_store.get_user_income_categories_with_descriptions(chat_id)
    income_categories = [category["name"] for category in income_categories_with_desc]
    income_category_descriptions = {
        category["name"]: category["description_summary"]
        for category in income_categories_with_desc if category["description_summary"]
    }
    logger.info(
        "Parser configurato",
        extra={"domain": "usage", "event": "parser_configured", "chat_id": chat_id,
               "meta": {"expense_categories": len(categories), "income_categories": len(income_categories)}},
    )
    return ExpenseParser(
        categories=categories, category_descriptions=category_descriptions,
        income_categories=income_categories,
        income_category_descriptions=income_category_descriptions,
    )


def _get_message_when(update: Update, chat_id: str) -> datetime:
    """Timestamp del messaggio nel fuso orario dell'utente (default Europe/Rome).

    Usato dal parser per l'hint di categoria sensibile all'ora del giorno (es. "coca"
    colazione vs aperitivo) — serve l'ora locale reale, non l'UTC grezzo di Telegram.
    """
    prefs = _user_store.get_user_preferences(chat_id)
    tz = ZoneInfo(prefs.get("timezone") or "Europe/Rome")
    message_date = update.effective_message.date if update.effective_message else None
    when = message_date or datetime.now(tz)
    return when.astimezone(tz)


def _is_authorized(update: Update) -> bool:
    """Verifica che il messaggio arrivi dall'utente autorizzato (presente nel database) e attivo."""
    if not update.effective_chat:
        return False

    chat_id = str(update.effective_chat.id)
    user = _user_store.get_user(chat_id)
    if user is None:
        from src.rate_limiter import track_failed_login

        attempts = track_failed_login(f"unauth:{chat_id}")
        level = logging.WARNING if attempts >= 3 else logging.INFO
        logger.log(
            level,
            "unauthorized_access_attempt",
            extra={
                "domain": "security",
                "event": "unauthorized_access_attempt",
                "chat_id": chat_id,
                "meta": {"attempts": attempts},
            },
        )
        return False
    return True


async def _reply_not_authorized(update: Update) -> None:
    """Risponde con il messaggio appropriato per utenti non autorizzati (sospesi vs mai registrati)."""
    chat_id = str(update.effective_chat.id)
    suspended = _user_store.get_user_any_status(chat_id)
    if suspended:
        await update.message.reply_text(
            "⏸️ *Account sospeso.*\nUsa /accedi per riprendere da dove hai lasciato.",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            "⚠️ *Non sei ancora registrato!*\nUsa /registrati per creare un account, "
            "oppure /accedi se ne hai già uno.",
            parse_mode=ParseMode.MARKDOWN,
        )

async def _check_and_consume_tokens(update: Update, chat_id: str, action_type: str) -> bool:
    """Verifica e consuma token per un'azione. Ritorna False se bloccato, True se OK."""
    costs = {"text": 800, "voice": 1500, "photo": 2000, "rag": 5000}
    cost = costs.get(action_type, 0)
    
    plan = _user_store.get_user_plan(chat_id)
    
    # Blocco funzionalità Premium
    if action_type in ["voice", "photo", "rag"] and plan["plan_type"] == "free":
        await update.message.reply_text(
            "🔒 *Funzione Premium*\n"
            "Questa funzionalità (audio, foto e chat avanzata) è disponibile solo nel piano *PRO*.\n\n"
            "Usa /piano per scoprire come sbloccarla.", 
            parse_mode=ParseMode.MARKDOWN
        )
        return False
        
    # Blocco token esauriti
    if plan["tokens_remaining"] < cost:
        if plan["plan_type"] == "free":
            await update.message.reply_text(
                f"🛑 *Token mensili esauriti*\n"
                f"Hai consumato tutti i tuoi {plan['tokens_total']:,} token mensili.\n\n"
                f"Usa /piano per fare l'upgrade e continuare a usare Expensum, o attendi il reset mensile.", 
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                "🛑 *Limite sistema raggiunto*\n"
                "Hai superato il limite di sicurezza del piano PRO. Contatta l'assistenza.", 
                parse_mode=ParseMode.MARKDOWN
            )
        return False
        
    # Notifiche soft (basate sul piano già letto)
    if plan["alert"] == "warning_90":
        await update.message.reply_text(
            "⚠️ *Attenzione:* hai consumato il 90% del piano mensile. Usa /piano per maggiori info.",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif plan["alert"] == "warning_70":
        await update.message.reply_text(
            "ℹ️ *Info:* hai consumato il 70% del piano mensile.",
            parse_mode=ParseMode.MARKDOWN,
        )

    return True



def _get_dashboard_button() -> InlineKeyboardMarkup:
    """Bottone "Apri Dashboard" verso la webapp, usato nei messaggi drip trial (D7/D14)."""
    return _webapp_button("📊 Apri Dashboard", "/dashboard")


def _webapp_button(label: str, path: str) -> InlineKeyboardMarkup:
    """Bottone link generico verso `{WEBAPP_BASE_URL}/login?next={path}`.

    Bottone `url` normale, non `web_app`: si apre sempre nel browser predefinito
    del dispositivo, mai nel WebView/mini-app interno di Telegram. `/login`
    autentica via sessione browser (email+password) e poi redirige a `path` — la
    stessa route già usata dai link nelle email di lifecycle trial
    (`_safe_next_url`, `src/dashboard/app.py`). Se l'utente ha già una sessione
    valida in quel browser, il passaggio da `/login` è trasparente (redirect
    immediato senza dover reinserire le credenziali).
    """
    next_encoded = quote(path, safe="")
    url = f"{Config.WEBAPP_BASE_URL}/login?next={next_encoded}"
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, url=url)]])




def sanitize_letters_only(text: str) -> str:
    """Rimuove tutto tranne lettere Unicode e spazi, normalizzando gli spazi multipli."""
    cleaned = "".join(char if (char.isalpha() or char.isspace()) else " " for char in text)
    return " ".join(cleaned.split())


def _parse_keyboard_list(raw_text: str) -> list[str]:
    """Parsa una lista separata da virgole e sanitizza ogni voce."""
    items = []
    for raw_item in raw_text.split(","):
        sanitized = sanitize_letters_only(raw_item)
        if sanitized:
            items.append(sanitized)
    return items


def _build_setup_summary(accounts: list[str], categories: list[str], subscriptions: list[str]) -> str:
    accounts_block = "\n".join(f"- {item}" for item in accounts) or "- Nessuno"
    categories_block = "\n".join(f"- {item}" for item in categories) or "- Nessuna"
    subscriptions_block = "\n".join(f"- {item}" for item in subscriptions) or "- Nessuno"

    return (
        "🛠️ *Riepilogo Setup Iniziale*\n\n"
        "🏦 *Accounts*\n"
        f"{accounts_block}\n\n"
        "📂 *Categories*\n"
        f"{categories_block}\n\n"
        "🔁 *Subscriptions*\n"
        f"{subscriptions_block}\n\n"
        "Confermi la creazione su Notion?"
    )


def _build_weekly_report_text(chat_id: str, start_date: date, end_date: date) -> str:
    """Costruisce un report settimanale sintetico per l'utente."""
    storage = _get_storage(chat_id)
    transactions = storage.fetch_all_transactions(start_date=start_date, end_date=end_date)
    incomes = storage.fetch_income(start_date=start_date, end_date=end_date)

    total_spent = sum(float(tx.get("amount", 0.0)) for tx in transactions)
    total_income = sum(float(inc.get("amount", 0.0)) for inc in incomes)

    by_category: dict[str, float] = {}
    for tx in transactions:
        category = str(tx.get("category") or "Altro")
        by_category[category] = by_category.get(category, 0.0) + float(tx.get("amount", 0.0))

    top_categories = sorted(by_category.items(), key=lambda item: item[1], reverse=True)[:5]
    top_lines = "\n".join(
        f"- {name}: *EUR {amount:.2f}*" for name, amount in top_categories
    )
    if not top_lines:
        top_lines = "- Nessuna spesa registrata"

    return (
        f"📅 *Weekly Report* ({start_date.isoformat()} → {end_date.isoformat()})\n"
        f"💸 Spese totali: *EUR {total_spent:.2f}*\n"
        f"💰 Entrate totali: *EUR {total_income:.2f}*\n"
        f"📊 Saldo netto: *EUR {total_income - total_spent:.2f}*\n\n"
        f"🏷️ *Top categorie*\n"
        f"{top_lines}"
    )


def _notify_webapp_report(chat_id: str, report_type: str, period_label: str, share_token: str) -> None:
    """Notifica la chat webapp con un messaggio di saluto e link cliccabile al report."""
    notify_webapp_report(_user_store, chat_id, report_type, period_label, share_token)


def _serialize_weekly_data(data: "WeeklyPlanData") -> dict:
    """Serializza WeeklyPlanData in dict JSON-safe per lo storico web."""
    budget_results = {}
    for cat, r in data.budget_results.items():
        budget_results[cat] = {
            "budget_monthly": r.budget_monthly,
            "spent_month": r.spent_month,
            "residuo": r.residuo,
            "overrun": r.overrun,
            "limite_reale": r.limite_reale,
            "soft_cap": r.soft_cap,
            "status": r.status,
        }
    subs = []
    for s in data.due_subscriptions:
        subs.append({
            "name": s.get("name", ""),
            "amount": float(s.get("amount") or 0),
            "due_date": s["due_date"].isoformat() if s.get("due_date") else None,
        })
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


def _serialize_monthly_data(data: "MonthlyPlanData") -> dict:
    """Serializza MonthlyPlanData in dict JSON-safe per lo storico web."""
    subs = []
    for s in data.subscriptions_month:
        subs.append({
            "name": s.get("name", ""),
            "amount": float(s.get("amount") or 0),
            "due_date": s["due_date"].isoformat() if s.get("due_date") else None,
        })
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


async def _build_and_send_weekly_plan(
    chat_id: str,
    bot=None,
    message=None,
    source: str = "job",
) -> str | None:
    """Costruisce e invia il piano settimanale intelligente per un utente.

    Usata sia dal command handler che dal job APScheduler che dalla webapp
    on-demand. `source` ('telegram'|'webapp'|'job') finisce in `record_report_event`
    per distinguere davvero chi ha generato il report — di default 'job' (lo
    scheduler resta il chiamante più comune). Ritorna lo `share_token` del report
    salvato, o `None` se non è stato possibile generarlo.
    """
    storage = _get_storage(chat_id)
    builder = WeeklyPlanBuilder()

    try:
        plan_data = builder.build(storage)
    except Exception as exc:  # noqa: BLE001 -- il piano mostra un fallback sicuro
        log_exception(logger, level="error", domain="plans", event="weekly_plan_build_failed", exception=exc, chat_id=str(chat_id))
        err_text = "⚠️ Non riesco a raccogliere i dati per il piano settimanale. Riprova tra poco."
        if message:
            await message.reply_text(err_text)
        elif bot:
            await bot.send_message(chat_id=int(chat_id), text=err_text)
        return None

    # Prova con AI (solo narrazione/consigli), fallback su consigli statistici
    ai_narrative = None
    ref = plan_data.reference_date
    week_end = ref + timedelta(days=6)
    week_label = f"{ref.strftime('%d/%m')} → {week_end.strftime('%d/%m')}"

    request_key = build_request_key(chat_id, "weekly_plan", ref.isoformat())
    reservation_created = False
    try:
        _user_store.reserve_llm_tokens(
            chat_id=chat_id,
            request_key=request_key,
            operation="weekly_plan",
            provider="mistral",
            model=Config.MISTRAL_SMALL_MODEL,
            reserved_tokens=estimate_reserved_tokens("weekly_plan"),
        )
        reservation_created = True
    except Exception as e:
        logger.warning("[User %s] Reservation weekly plan non creata: %s", chat_id, e)

    try:
        mistral = MistralClient()
        ai_narrative, usage = mistral.generate_weekly_plan(plan_data.to_prompt_text(), week_label)
        usage = normalize_usage_metadata(usage)
        if usage.get("total_tokens", 0) > 0:
            try:
                _user_store.finalize_llm_usage(
                    chat_id=chat_id,
                    request_key=request_key,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                    provider=usage.get("provider", "mistral"),
                    model=usage.get("model", Config.MISTRAL_SMALL_MODEL),
                    operation="weekly_plan",
                )
            except Exception as e:
                logger.warning("[User %s] finalize_llm_usage weekly_plan fallita: %s", chat_id, e)
        elif reservation_created:
            try:
                _user_store.release_llm_reservation(chat_id, request_key, reason="no_usage_metadata")
            except Exception:
                pass
    except Exception as e:
        log_exception(logger, level="warning", domain="plans", event="weekly_plan_ai_failed", exception=e, chat_id=str(chat_id))
        if reservation_created:
            try:
                _user_store.release_llm_reservation(chat_id, request_key, reason=str(e))
            except Exception:
                pass
        ai_narrative = None

    plan_content = builder.build_content(plan_data, ai_narrative=ai_narrative)

    # Salva report nel DB e notifica la chat webapp
    share_token: str | None = None
    try:
        share_token = storage.save_report(
            user_id=str(chat_id),
            report_type="weekly",
            report_date=plan_data.reference_date,
            text_content=json.dumps(plan_content, ensure_ascii=False),
            report_data=_serialize_weekly_data(plan_data),
        )
        if share_token:
            _notify_webapp_report(chat_id, "weekly", week_label, share_token)
            _user_store.record_report_event(chat_id, share_token, "weekly", "generated", source)
    except Exception as exc:  # noqa: BLE001 -- il piano può essere inviato senza persistenza
        log_exception(logger, level="warning", domain="plans", event="weekly_plan_persist_failed", exception=exc, chat_id=str(chat_id))

    # Teaser + link: il piano completo (testo, tabella budget) si legge in webapp,
    # non più riversato per intero in chat (vedi piano depotenziamento Telegram).
    if share_token:
        teaser_text = f"📊 Il tuo piano settimanale (*{week_label}*) è pronto."
        teaser_parse_mode = ParseMode.MARKDOWN
        keyboard = _webapp_button("📊 Apri in Expensum", f"/reports/{share_token}")
    else:
        # Fallback di emergenza (salvataggio DB fallito, nessun link da mandare):
        # testo semplice SENZA parse_mode. render_plain_text() non aggiunge
        # sintassi Markdown, ma categorie/tips possono contenere '*'/'_'/'`'
        # liberi (input utente o AI) che romperebbero il parsing entità di
        # Telegram in ParseMode.MARKDOWN. Troncato al limite hard di Telegram.
        teaser_text = render_plain_text(plan_content)[:4000]
        teaser_parse_mode = None
        keyboard = None

    try:
        if message:
            await message.reply_text(teaser_text, parse_mode=teaser_parse_mode, reply_markup=keyboard)
        elif bot and not str(chat_id).startswith("web_"):
            await bot.send_message(
                chat_id=int(chat_id),
                text=teaser_text,
                parse_mode=teaser_parse_mode,
                reply_markup=keyboard,
            )
    except Exception as exc:  # noqa: BLE001 -- errore canale Telegram non propagato al job
        log_exception(logger, level="error", domain="plans", event="weekly_plan_send_failed", exception=exc, chat_id=str(chat_id))

    return share_token


async def _build_and_send_monthly_plan(
    chat_id: str,
    bot=None,
    message=None,
    category_overrides: dict[str, float] | None = None,
    source: str = "telegram",
) -> str | None:
    """Costruisce e invia il piano mensile intelligente per un utente.

    Usata dal command handler /monthly_plan. `source` finisce in
    `record_report_event` per distinguere chi ha generato il report — di default
    'telegram' (unico chiamante oggi è il comando; vedi _build_and_send_weekly_plan
    per lo stesso pattern condiviso anche da job/webapp). Ritorna lo `share_token`
    del report salvato, o `None` se non è stato possibile generarlo.
    """
    storage = _get_storage(chat_id)
    builder = MonthlyPlanBuilder()

    try:
        plan_data = builder.build(storage, category_overrides=category_overrides)
    except Exception as exc:  # noqa: BLE001 -- il piano mostra un fallback sicuro
        log_exception(logger, level="error", domain="plans", event="monthly_plan_build_failed", exception=exc, chat_id=str(chat_id))
        err_text = "⚠️ Non riesco a raccogliere i dati per il piano mensile. Riprova tra poco."
        if message:
            await message.reply_text(err_text)
        elif bot:
            await bot.send_message(chat_id=int(chat_id), text=err_text)
        return None

    ai_narrative = None
    tm = plan_data.target_month
    _MONTHS_IT = [
        "", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
        "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
    ]
    month_label = f"{_MONTHS_IT[tm.month]} {tm.year}"

    request_key = build_request_key(chat_id, "monthly_plan", tm.year, tm.month)
    reservation_created = False
    try:
        _user_store.reserve_llm_tokens(
            chat_id=chat_id,
            request_key=request_key,
            operation="monthly_plan",
            provider="mistral",
            model=Config.MISTRAL_SMALL_MODEL,
            reserved_tokens=estimate_reserved_tokens("monthly_plan"),
        )
        reservation_created = True
    except Exception as e:
        logger.warning("[User %s] Reservation monthly plan non creata: %s", chat_id, e)

    try:
        mistral = MistralClient()
        ai_narrative, usage = mistral.generate_monthly_plan(plan_data.to_prompt_text(), month_label)
        usage = normalize_usage_metadata(usage)
        if usage.get("total_tokens", 0) > 0:
            try:
                _user_store.finalize_llm_usage(
                    chat_id=chat_id,
                    request_key=request_key,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                    provider=usage.get("provider", "mistral"),
                    model=usage.get("model", Config.MISTRAL_SMALL_MODEL),
                    operation="monthly_plan",
                )
            except Exception as e:
                logger.warning("[User %s] finalize_llm_usage monthly_plan fallita: %s", chat_id, e)
        elif reservation_created:
            try:
                _user_store.release_llm_reservation(chat_id, request_key, reason="no_usage_metadata")
            except Exception:
                pass
    except Exception as e:
        log_exception(logger, level="warning", domain="plans", event="monthly_plan_ai_failed", exception=e, chat_id=str(chat_id))
        if reservation_created:
            try:
                _user_store.release_llm_reservation(chat_id, request_key, reason=str(e))
            except Exception:
                pass
        ai_narrative = None

    plan_content = builder.build_content(plan_data, ai_narrative=ai_narrative)

    # Salva report nel DB e notifica la chat webapp
    share_token: str | None = None
    try:
        share_token = storage.save_report(
            user_id=str(chat_id),
            report_type="monthly",
            report_date=plan_data.target_month,
            text_content=json.dumps(plan_content, ensure_ascii=False),
            report_data=_serialize_monthly_data(plan_data),
        )
        if share_token:
            _notify_webapp_report(chat_id, "monthly", month_label, share_token)
            _user_store.record_report_event(chat_id, share_token, "monthly", "generated", source)
    except Exception as exc:  # noqa: BLE001 -- il piano può essere inviato senza persistenza
        log_exception(logger, level="warning", domain="plans", event="monthly_plan_persist_failed", exception=exc, chat_id=str(chat_id))

    # Teaser + link: il piano completo si legge in webapp, non più riversato per
    # intero in chat (vedi piano depotenziamento Telegram).
    if share_token:
        teaser_text = f"📊 Il tuo piano mensile (*{month_label}*) è pronto."
        teaser_parse_mode = ParseMode.MARKDOWN
        keyboard = _webapp_button("📊 Apri in Expensum", f"/reports/{share_token}")
    else:
        # Fallback di emergenza (salvataggio DB fallito): testo semplice SENZA
        # parse_mode, vedi commento analogo in _build_and_send_weekly_plan.
        teaser_text = render_plain_text(plan_content)[:4000]
        teaser_parse_mode = None
        keyboard = None

    if teaser_parse_mode is not None:
        try:
            user = _user_store.get_user(chat_id)
            teaser_text += _user_store.get_referral_footer_text(user.email if user else None)
        except Exception as exc:  # noqa: BLE001 -- il footer referral è opzionale
            log_exception(logger, level="warning", domain="plans", event="monthly_plan_referral_footer_failed", exception=exc, chat_id=str(chat_id))

    try:
        if message:
            await message.reply_text(teaser_text, parse_mode=teaser_parse_mode, reply_markup=keyboard)
        elif bot:
            await bot.send_message(
                chat_id=int(chat_id),
                text=teaser_text,
                parse_mode=teaser_parse_mode,
                reply_markup=keyboard,
            )
    except Exception as exc:  # noqa: BLE001 -- errore canale Telegram non propagato al job
        log_exception(logger, level="error", domain="plans", event="monthly_plan_send_failed", exception=exc, chat_id=str(chat_id))

    return share_token


def _has_notion_template_binding(user) -> bool:
    if not user:
        return False
    required_ids = [
        user.expense_db_id,
        user.income_db_id,
        user.categories_db_id,
        user.accounts_db_id,
        user.subscriptions_db_id,
        user.pay_transfer_db_id,
        user.monthly_balance_db_id,
    ]
    return all(required_ids)

async def cmd_modify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Rimanda alla pagina Gestisci della webapp (conti, categorie, budget,
    abbonamenti, entrate, spese, trasferimenti).

    Non apre più il vecchio form di setup iniziale (`/setup`, legacy onboarding
    Notion): la modifica vera vive solo in `/spazio` — il bot fa solo da entry
    point rapido, stesso pattern di cmd_obiettivi/cmd_status.
    """
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    chat_id = str(update.effective_chat.id)
    _track_event(chat_id, "telegram_command_used", {"command": "modify"})
    await update.message.reply_text(
        "⚙️ Gestisci conti, categorie, budget, abbonamenti, entrate e spese:",
        reply_markup=_webapp_button("⚙️ Apri Gestisci", "/spazio"),
    )

# ---------------------------------------------------------------------------
# Dashboard / Status
# ---------------------------------------------------------------------------

def _build_streak_bar(current_streak_days: int, streak_target_days: int, cycle_state: str) -> str:
    """Barra a blocchi emoji dello stato streak."""
    if cycle_state == "reward_active":
        return "🟩" * 14
    filled = max(0, min(current_streak_days, streak_target_days))
    return "🟩" * filled + "⬜" * (streak_target_days - filled)


def _build_streak_section(chat_id: str) -> str:
    """Riga streak per la dashboard: didascalia breve (per capire cosa indica la barra) + barra.

    Nessuna cifra esatta (giorno X/Y) — solo la spiegazione di cosa rappresenta la barra,
    come richiesto: la barra da sola non basta a farla capire all'utente.
    """
    streak = _user_store.get_user_streak(chat_id)
    bar = _build_streak_bar(
        streak["current_streak_days"], streak["streak_target_days"], streak["cycle_state"]
    )
    if streak["cycle_state"] == "reward_active":
        caption = "✨ Premio Pro attivo: streak in pausa fino alla scadenza"
    else:
        caption = "🔥 Streak verso il prossimo premio Pro (2 settimane gratis)"
    return f"{caption}\n{bar}"


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Rimanda alla dashboard finanziaria sulla webapp.

    La dashboard completa (conti, abbonamenti, spese per categoria) resta solo
    webapp — il bot fa solo da entry point rapido, stesso pattern di
    cmd_obiettivi/cmd_piano.
    """
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    chat_id = str(update.effective_chat.id)
    _track_event(chat_id, "telegram_command_used", {"command": "status"})
    await update.message.reply_text(
        "📊 La tua situazione finanziaria è sempre aggiornata qui:",
        reply_markup=_get_dashboard_button(),
    )


def _is_pro_plan(chat_id: str) -> bool:
    """Ritorna True se l'utente ha accesso Premium (piano pro o trial attivo)."""
    return _user_store.get_user_plan(chat_id)["plan_type"] == "pro"


async def _reply_plan_free_gated(update: Update) -> None:
    """Blocca weekly/monthly plan su piano Free, con CTA verso l'upgrade in webapp."""
    await update.message.reply_text(
        "🔒 *Piano riservato a Premium*\n"
        "Sul piano Free il report arriva automaticamente (ogni lunedì il settimanale, "
        "il 1° del mese il mensile). Passa a Premium per generarlo quando vuoi 👇",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_webapp_button("🚀 Passa a Premium", "/abbonamenti"),
    )


async def cmd_piano_settimanale(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Genera il piano settimanale: messaggio "in generazione" poi teaser + link.

    Nessun equivalente webapp per questo piano *previsionale* leggero (a differenza
    del report mensile retrospettivo, generabile anche da `/api/reports/generate`):
    il comando resta un generatore reale — solo l'esito finale è un teaser, mai il
    testo completo in chat (vedi `_build_and_send_weekly_plan`).
    """
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    chat_id = str(update.effective_chat.id)
    _track_event(chat_id, "telegram_command_used", {"command": "piano_settimanale"})

    if not _is_pro_plan(chat_id):
        await _reply_plan_free_gated(update)
        return

    await update.message.chat.send_action("typing")
    await update.message.reply_text("🔄 Sto generando il tuo piano settimanale, un attimo...")
    await _build_and_send_weekly_plan(chat_id=chat_id, message=update.message, source="telegram")


async def cmd_piano_mensile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Genera il report mensile retrospettivo (grafici, forecast, storico): messaggio
    "in generazione" poi teaser + link — stessa pipeline pesante del job automatico
    del 1° del mese (`main.run_agent`), qui invocata on-demand.
    """
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    chat_id = str(update.effective_chat.id)
    _track_event(chat_id, "telegram_command_used", {"command": "piano_mensile"})

    if not _is_pro_plan(chat_id):
        await _reply_plan_free_gated(update)
        return

    plan = _user_store.get_user_plan(chat_id)
    if plan["tokens_remaining"] < 5000:
        await update.message.reply_text(
            "🛑 *Limite sistema raggiunto*\n"
            "Token insufficienti per generare il report. Contatta l'assistenza.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text("🔄 Sto generando il tuo report mensile, un attimo...")

    import main as main_module
    target_year, target_month = main_module._resolve_default_target_month(date.today())
    try:
        await asyncio.wait_for(
            main_module.run_agent(
                target_year, target_month, dry_run=False, chat_id=chat_id,
                shared_store=_user_store, source="telegram",
            ),
            timeout=300,
        )
    except asyncio.TimeoutError:
        logger.error("[User %s] piano_mensile: timeout dopo 300s", chat_id)
        await update.message.reply_text(
            "⏱️ Il report mensile ha impiegato troppo tempo (>5 min). Riprova più tardi: "
            "potrebbe essere un problema temporaneo con Notion o Mistral."
        )
    except Exception as e:
        logger.exception("[User %s] Errore generazione piano_mensile: %s", chat_id, e)
        await update.message.reply_text(
            "⚠️ Errore tecnico nella generazione del report mensile. Riprova più tardi."
        )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def cmd_piano(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Rimanda alla pagina abbonamenti/piano della webapp.

    Dettagli piano, token e upgrade restano solo webapp (dove il checkout è
    integrato) — il bot fa solo da entry point rapido, stesso pattern di
    cmd_obiettivi/cmd_status.
    """
    chat_id = str(update.effective_chat.id)
    if not _is_authorized(update):
        await update.message.reply_text("Devi prima registrarti con /registrati.")
        return

    _track_event(chat_id, "telegram_command_used", {"command": "piano"})
    await update.message.reply_text(
        "📊 Il tuo piano, i token residui e le opzioni di upgrade:",
        reply_markup=_webapp_button("📊 Apri Abbonamenti", "/abbonamenti"),
    )

async def cmd_obiettivi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Rimanda alla gestione degli obiettivi di risparmio sulla webapp.

    CRUD e dashboard restano solo webapp (come budget/conti) — il bot fa solo
    da entry point rapido, coerente con il resto del bot che e' gia' webapp-driven.
    """
    chat_id = str(update.effective_chat.id)
    if not _is_authorized(update):
        await update.message.reply_text("Devi prima registrarti con /registrati.")
        return

    _track_event(chat_id, "telegram_command_used", {"command": "obiettivi"})
    await update.message.reply_text(
        "🎯 Gestisci i tuoi obiettivi di risparmio (creazione, avanzamento, ETA):",
        reply_markup=_webapp_button("🎯 Apri Obiettivi", "/goals"),
    )


async def cmd_scova_abbonamenti(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mostra gli abbonamenti ricorrenti rilevati dalle spese, in attesa di conferma.

    Feature 100% Free. Il rilevamento vero e proprio è incrementale (hook a ogni
    spesa confermata, vedi src/subscription_detector.py); questo comando serve a
    rivedere a piacere i candidati già pronti, inclusi quelli popolati dal
    backfill storico (che non manda notifiche proattive, vedi
    scripts/backfill_subscription_candidates.py).
    """
    chat_id = str(update.effective_chat.id)
    if not _is_authorized(update):
        await update.message.reply_text("Devi prima registrarti con /registrati.")
        return

    _track_event(chat_id, "telegram_command_used", {"command": "scova_abbonamenti"})

    with _user_store.Session() as sub_session:
        candidates = subscription_detector.get_awaiting_confirmation_candidates(sub_session, chat_id)
        # Snapshot dei campi prima di chiudere la sessione: gli oggetti ORM non
        # vanno riusati fuori dal blocco `with`.
        candidates_data = [
            (c.id, c.display_name, float(c.amount), c.category_name, c.cadence)
            for c in candidates
        ]

    if not candidates_data:
        await update.message.reply_text(
            "🔎 Nessun abbonamento ricorrente in attesa di conferma al momento.\n"
            "Continuo a osservare le tue spese: appena riconosco un pattern ricorrente "
            "te lo segnalo qui."
        )
        return

    for candidate_id, display_name, amount, category_name, cadence in candidates_data:
        cadence_label = subscription_detector.cadence_label_it(cadence)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Sì", callback_data=f"subpromote_yes:{candidate_id}"),
            InlineKeyboardButton("❌ No", callback_data=f"subpromote_no:{candidate_id}"),
        ]])
        await update.message.reply_text(
            f"🔎 Ho notato che paghi ricorrentemente *{display_name}* "
            f"(~€{amount:.2f} {cadence_label}) in *{category_name}*, "
            "vuoi che lo aggiunga ai tuoi abbonamenti tracciati?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )


_SOCIAL_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("🌐 Sito", url="https://expensum.it")],
    [
        InlineKeyboardButton("📸 Instagram", url="https://instagram.com/expensum.finance"),
        InlineKeyboardButton("🎵 TikTok", url="https://www.tiktok.com/@expensum"),
    ],
    [
        InlineKeyboardButton("💼 LinkedIn", url="https://www.linkedin.com/company/expensum/"),
        InlineKeyboardButton("👍 Facebook", url="https://acesse.one/ite4lxk"),
    ],
])


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler per /start — messaggio di benvenuto. Gestisce anche il deep link
    `?start=link_<state>` generato dalla webapp per collegare un account web a Telegram."""
    args = context.args
    if args and args[0].startswith("link_"):
        state = args[0][len("link_"):]
        chat_id = str(update.effective_chat.id)
        old_chat_id = _user_store.peek_oauth_session(state)
        if not old_chat_id:
            # Il client Telegram invia talvolta lo stesso /start due volte quando si
            # apre un deep link verso una chat non ancora avviata: se questo chat_id
            # ha gia' un account attivo, il token e' stato consumato pochi istanti fa
            # da un collegamento riuscito, non e' davvero scaduto.
            if _user_store.get_user(chat_id):
                await update.message.reply_text("✅ Il tuo account Telegram è già collegato a Expensum.")
            else:
                await update.message.reply_text(
                    "⚠️ Il link di collegamento è scaduto o non è valido. "
                    "Riprova dalle Impostazioni della webapp."
                )
            return
        # Riassegnazione cross-tenant: arruolata qui (ruolo DML-only), eseguita da
        # scripts/process_reassignment_jobs.py (worker fuori banda, ruolo owner mai
        # esposto a rete). Vedi security design notes § Vulnerabilità residua #2.
        job_id = _user_store.enqueue_chat_id_reassignment(old_chat_id, chat_id)
        status, error_text = _user_store.wait_for_reassignment_job(job_id)
        if status == "failed":
            if error_text and "gia associato" in error_text:
                logger.warning("[User %s] Collegamento Telegram fallito: chat_id già associato", chat_id)
                await update.message.reply_text(
                    "⚠️ Questo account Telegram è già associato a un altro profilo Expensum."
                )
            else:
                logger.warning("[User %s] Collegamento Telegram fallito: %s", chat_id, error_text)
                await update.message.reply_text(
                    "⚠️ Si è verificato un errore durante il collegamento. Riprova tra qualche istante "
                    "riaprendo lo stesso link."
                )
            return
        if status == "pending":
            logger.warning("[User %s] Collegamento Telegram: job %s ancora in coda dopo il timeout", chat_id, job_id)
            await update.message.reply_text(
                "⏳ Il collegamento richiede qualche istante in più. Riprova tra poco riaprendo lo stesso link."
            )
            return
        # Consuma il token solo ora che il collegamento è andato a buon fine: un
        # fallimento sopra lascia lo state valido, cosi' l'utente puo' ritentare
        # con lo stesso link entro la scadenza (15 minuti).
        _user_store.get_and_delete_oauth_session(state)
        logger.info("[User %s] Account web collegato a Telegram", chat_id)
        # Il chat_id qui è già quello definitivo post-riassegnazione.
        gamification.record_event(_user_store, chat_id, "telegram_linked")
        await update.message.reply_text(
            "✅ *Account collegato!*\n\n"
            "Il tuo profilo Expensum è ora sincronizzato con Telegram: puoi registrare spese semplicemente scrivendo, mandando una foto o un audio in chat"
            "da qui in qualsiasi momento.\n\n"
            "Quando registrerai una spesa, scrivimi ad esempio:\n"
            "• _\"pizza con gli amici 18€ oppure mandami un audio\"_",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    first_name = (update.effective_user.first_name or "").strip()
    name_suffix = f" {first_name}" if first_name else ""

    if not _is_authorized(update):
        await update.message.reply_text(
            f"👋 *Benvenuto{name_suffix}!*\n\n"
            "Sono l'assistente AI di Expensum.\n"
            "Le mie risposte sono generate automaticamente con AI. Posso sbagliare: verifica sempre i dati finanziari importanti.\n\n"
            "Digita /registrati per creare un account, o /accedi se ne hai già uno e inizia a migliorare la tua vita "
            "aumentando la consapevolezza delle tue finanze! 🚀\n\n"
            "Se vuoi farti un giro sui nostri social ti ho lasciato i link qui sotto 😉",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_SOCIAL_KEYBOARD,
        )
        return

    chat_id = str(update.effective_chat.id)
    _user_store.update_telegram_identity(chat_id, update.effective_user.first_name, update.effective_user.last_name)

    await update.message.reply_text(
        f"👋 *Bentornato{name_suffix}!* Sono **Moneo** 🐷, assistente AI di Expensum.\n"
        "Le mie risposte sono generate automaticamente con Mistral AI europea. Posso sbagliare: verifica sempre i dati finanziari importanti.\n\n"
        "Dimmi, cosa hai comprato di bello?\n"
        "Scrivimi una spesa in modo naturale:\n"
        "• _\"ieri ho sganciato 25€ per la pizza\"_\n"
        "• _\"spesa al super per 67 euro\"_\n"
        "• _\"netflix 13.99\"_\n\n"
        "Ci penso io a fare i conti e salvarti tutto su Notion! 🚀",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_SOCIAL_KEYBOARD,
    )

async def cmd_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler per /feedback — raccoglie e salva i suggerimenti/problemi dell'utente."""
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    chat_id = str(update.effective_chat.id)
    # Rimuove il comando dal testo
    text = update.message.text.split("/feedback", 1)[-1].strip()
    
    if not text:
        await update.message.reply_text("Esempio di utilizzo:\n`/feedback Il bot ha sbagliato categoria per l'Esselunga`", parse_mode=ParseMode.MARKDOWN)
        return
        
    _user_store.save_feedback(chat_id, text)
    _track_event(chat_id, "feedback_submitted")
    await update.message.reply_text("✅ *Grazie per il tuo feedback!*\n\nIl tuo commento è stato salvato e lo terremo in considerazione per le prossime versioni di Expensum ✨", parse_mode=ParseMode.MARKDOWN)

async def cmd_registra(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Punto d'ingresso per la registrazione.

    Solo Notion si registra direttamente da Telegram (OAuth, nessun account "web"
    intermedio necessario). Il DB interno di Expensum si registra SOLO dalla webapp
    (form → wizard di onboarding → tour → collegamento Telegram come ultimo step,
    vedi TelegramLinkStep/cmd_start ramo `link_<state>`): qui il bottone è un
    semplice link al sito, non genera alcun reg_token legato a questo chat_id —
    Telegram non deve poter creare un account sul DB interno.
    """
    chat_id = str(update.effective_chat.id)

    # Verifica se l'utente esiste già (attivo o sospeso)
    user = _user_store.get_user_any_status(chat_id)
    if user:
        base_url = Config.WEBAPP_BASE_URL
        reg_token = _user_store.create_oauth_session(chat_id)

        login_url = f"{base_url}/auth/telegram-login?state={reg_token}"
        keyboard_buttons = [
            [InlineKeyboardButton("🔑 Fai Login", url=login_url)]
        ]

        if user.storage_backend == "postgres":
            keyboard_buttons.append([InlineKeyboardButton("🔄 Passa a Notion (Riavvia da zero)", callback_data="switch_to_notion")])
        else:
            keyboard_buttons.append([InlineKeyboardButton("🔄 Passa al DB interno (dalla webapp)", url=base_url)])

        current_backend = "DB interno" if user.storage_backend == "postgres" else "Notion"

        await update.message.reply_text(
            "⚠️ *Sei già registrato nel sistema!*\n\n"
            f"Attualmente stai utilizzando *{current_backend}* come fonte dati.\n\n"
            "Scegli un'opzione:\n"
            "• Fai login per continuare\n"
            "• Cambia fonte dati (⚠️ *ATTENZIONE*: eliminerà in modo irreversibile tutti i tuoi dati da Expensum e ti farà ricominciare da zero)",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard_buttons)
        )
        return

    reg_token = _user_store.create_oauth_session(chat_id)
    base_url = Config.WEBAPP_BASE_URL
    notion_url = f"{base_url}/auth/notion?reg_token={reg_token}"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Connetti a Notion", url=notion_url)],
        [InlineKeyboardButton("🌐 Registrati sul DB interno", url=base_url)],
    ])

    await update.message.reply_text(
        "🚀 *Scegli come registrarti*\n\n"
        "🔗 *Notion*: sincronizza le spese nel tuo workspace Notion (autorizzazione OAuth), "
        "puoi farlo direttamente da qui.\n"
        "⚠️ I tuoi dati finanziari saranno conservati sull'infrastruttura di Notion Labs Inc. "
        "(*USA* 🇺🇸), salvo che tu abbia attivato la data residency UE sul tuo account Notion "
        "(solo piani Enterprise).\n\n"
        "🌐 *DB interno*: salva i dati nel database interno di Expensum, su server *UE* 🇪🇺 "
        "(Germania), più veloce e senza rate limit. La registrazione si fa dal sito.\n\n"
        "Puoi cambiare idea più avanti scrivendo al supporto. 🛡️",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )

def _delete_account_confirmation_text_and_keyboard() -> tuple[str, InlineKeyboardMarkup]:
    """Testo e keyboard di conferma cancellazione, condivisi tra /elimina_account e il menu /impostazioni."""
    text = (
        "⚠️ *Sei sicuro di voler eliminare il tuo account?*\n\n"
        "Questa operazione è *irreversibile* e cancellerà:\n"
        "• Tutti i tuoi dati finanziari (spese, entrate, conti, abbonamenti)\n"
        "• Le tue categorie e impostazioni\n"
        "• Il tuo account Expensum\n\n"
        "I dati sul tuo workspace Notion *non* vengono toccati."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💀 Sì, elimina tutto", callback_data="delete_account_confirm")],
        [InlineKeyboardButton("❌ Annulla", callback_data="delete_account_cancel")],
    ])
    return text, keyboard


async def cmd_elimina_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler per /elimina_account — chiede conferma prima di cancellare tutti i dati."""
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    text, keyboard = _delete_account_confirmation_text_and_keyboard()
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


async def process_invite_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fase 1: Verifica il codice e chiede la API Key."""
    text = update.message.text.strip()
    if text != Config.INVITE_CODE:
        await update.message.reply_text("❌ Codice errato! Riprova o scrivi /cancel.")
        return WAITING_INVITE_CODE
        
    await update.message.reply_text("✅ Codice accettato! Ora incolla la tua *Notion API Key*:", parse_mode=ParseMode.MARKDOWN)
    return WAITING_API_KEY

async def process_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fase 2: Riceve la API Key e chiede l'ID database Spese."""
    api_key = update.message.text.strip()
    if not api_key.startswith("ntn_"):
        await update.message.reply_text("⚠️ Chiave non valida. Inserisci la tua *Notion API Key* (inizia con `ntn_`):", parse_mode=ParseMode.MARKDOWN)
        return WAITING_API_KEY
        
    context.user_data["notion_api_key"] = api_key
    await update.message.reply_text("Ottimo! Ora incolla l'*ID del Database Spese* (Expense):")
    return WAITING_EXPENSE_DB

async def process_expense_db(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fase 3: Riceve ID Spese e chiede ID Entrate."""
    context.user_data["expense_db_id"] = update.message.text.strip()
    await update.message.reply_text("Ricevuto! Ora incolla l'*ID del Database Entrate* (Income):", parse_mode=ParseMode.MARKDOWN)
    return WAITING_INCOME_DB

async def process_income_db(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fase 4: Riceve ID Entrate e chiede ID Categorie."""
    context.user_data["income_db_id"] = update.message.text.strip()
    await update.message.reply_text("Ottimo! Ora incolla l'*ID del Database Categorie* (Categories):", parse_mode=ParseMode.MARKDOWN)
    return WAITING_CATEGORIES_DB

async def process_categories_db(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fase 5: Riceve ID Categorie e chiede ID Monthly Balance."""
    context.user_data["categories_db_id"] = update.message.text.strip()
    await update.message.reply_text("Perfetto! Ora incolla l'*ID del Database Bilancio Mensile* (Monthly Balance):", parse_mode=ParseMode.MARKDOWN)
    return WAITING_MONTHLY_DB

async def process_monthly_db(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fase 6: Riceve ID Monthly Balance e chiede ID Accounts."""
    context.user_data["monthly_balance_db_id"] = update.message.text.strip()
    await update.message.reply_text("Quasi fatto! Infine, incolla l'*ID del Database Conti* (Accounts):", parse_mode=ParseMode.MARKDOWN)
    return WAITING_ACCOUNTS_DB

async def process_accounts_db(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fase Finale: Raccoglie ID Accounts e salva tutto nel database utenti."""
    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username

    _user_store.add_user(
        chat_id=chat_id,
        username=username,
        first_name=update.effective_user.first_name,
        last_name=update.effective_user.last_name,
        notion_api_key=context.user_data["notion_api_key"],
        expense_db_id=context.user_data["expense_db_id"],
        income_db_id=context.user_data["income_db_id"],
        categories_db_id=context.user_data["categories_db_id"],
        monthly_balance_db_id=context.user_data["monthly_balance_db_id"],
        accounts_db_id=update.message.text.strip(),
    )

    context.user_data.clear()
    logger.info("notion_onboarding_completed", extra={"domain": "onboarding", "event": "notion_onboarding_completed", "chat_id": chat_id, "meta": {}})
    _track_event(chat_id, "user_signed_up", {"auth_method": "telegram", "storage_backend": "notion"})
    analytics.identify(chat_id, {"auth_method": "telegram", "storage_backend": "notion", "platform": "telegram"})
    await update.message.reply_text(
        "🎊 *Configurazione completata!*\n\n"
        "Ora puoi usare il bot per tracciare le tue finanze. Scrivi una spesa in modo naturale!",
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END

async def cancel_registra(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Annulla la registrazione."""
    context.user_data.clear()
    await update.message.reply_text("❌ Registrazione annullata.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# /accedi — Accesso tramite mini app WebApp
# ---------------------------------------------------------------------------

async def cmd_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Apre il form di login come Telegram WebApp. Per utenti Notion sospesi offre riattivazione diretta."""
    chat_id = str(update.effective_chat.id)
    user = _user_store.get_user(chat_id)

    # Già autenticato e attivo
    if user:
        await update.message.reply_text(
            "✅ Sei già connesso. Usa /logout per sospendere l'account.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Utente sospeso senza email (solo Notion): riattivazione con un click
    suspended = _user_store.get_user_any_status(chat_id)
    if suspended and not suspended.email:
        await update.message.reply_text(
            "👋 *Account trovato!*\n\n"
            "Il tuo account è temporaneamente sospeso. "
            "Clicca il bottone per riprendere da dove avevi lasciato.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("✅ Riattiva account", callback_data=REACTIVATE_CB)]]
            ),
        )
        return

    # Tutti gli altri casi (nuovo utente, utente con email sospeso): apri il form
    state = _user_store.create_oauth_session(chat_id)
    login_url = f"{Config.WEBAPP_BASE_URL}/auth/telegram-login?state={state}"
    await update.message.reply_text(
        "🔑 *Accedi a Expensum*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔑 Accedi", url=login_url)]]
        ),
    )


# ---------------------------------------------------------------------------
# /logout — Sospensione temporanea account
# ---------------------------------------------------------------------------

async def cmd_logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Chiede conferma prima di sospendere temporaneamente l'account."""
    if not _is_authorized(update):
        await update.message.reply_text(
            "⚠️ Non sei registrato. Usa /registrati per creare un account, "
            "oppure /accedi se ne hai già uno.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Sì, esci", callback_data=LOGOUT_CONFIRM_CB),
            InlineKeyboardButton("❌ Annulla", callback_data=LOGOUT_CANCEL_CB),
        ]
    ])
    await update.message.reply_text(
        "👋 *Vuoi sospendere il tuo account?*\n\n"
        "I tuoi dati resteranno al sicuro. Potrai riprendere da dove hai lasciato usando /accedi.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )



def _build_expense_summary(data: dict) -> str:
    """Costruisce il testo di riepilogo per una spesa/entrata in sospeso di conferma."""
    from datetime import datetime
    dt = datetime.fromisoformat(data["date"]) if isinstance(data["date"], str) else data["date"]
    date_str = dt.strftime("%d/%m/%Y")
    if data.get("type") == "income":
        income_type_label = data.get("income_category") or data.get("income_type") or "Non determinato"
        return (
            f"📝 *Nuova Entrata riconosciuta:*\n\n"
            f"📅 Data: *{date_str}*\n"
            f"💰 Importo: *€{data['amount']:.2f}*\n"
            f"🏷️ Categoria entrata: *{income_type_label}*\n"
            f"📝 Descrizione: *{data['name']}*"
        )
    if data.get("type") == "transfer":
        from_name = data.get("from_account_name") or "—"
        to_name = data.get("to_account_name") or "—"
        return (
            f"📝 *Nuovo trasferimento riconosciuto:*\n\n"
            f"📅 Data: *{date_str}*\n"
            f"💰 Importo: *€{data['amount']:.2f}*\n"
            f"🏦 Da: *{from_name}*\n"
            f"🏦 A: *{to_name}*\n"
            f"📝 Descrizione: *{data['name']}*"
        )
    return (
        f"📝 *Nuova spesa riconosciuta:*\n\n"
        f"📅 Data: *{date_str}*\n"
        f"💰 Importo: *€{data['amount']:.2f}*\n"
        f"📂 Categoria: *{data['category'] or 'Non determinata'}*\n"
        f"📝 Descrizione: *{data['name']}*"
    )


def _build_confirm_keyboard(data: dict, tx_id: str | None = None) -> InlineKeyboardMarkup:
    """Costruisce la tastiera di conferma spesa/entrata, con bottone di modifica categoria per le spese.

    Se `tx_id` è fornito, i callback_data sono prefissati con "m" e taggati con l'id
    (es. "mconfirm:3") per instradare bottoni di transazioni multiple presentate in parallelo
    (vedi `pending_expenses` in `context.user_data`), invece della singola `pending_expense`.
    """
    if tx_id is not None:
        rows = []
        if data.get("type") in {"expense", "income"}:
            rows.append([InlineKeyboardButton("✏️ Cambia categoria", callback_data=f"medit_category:{tx_id}")])
        rows.append([
            InlineKeyboardButton("✅ Conferma", callback_data=f"mconfirm:{tx_id}"),
            InlineKeyboardButton("❌ Annulla", callback_data=f"mcancel:{tx_id}"),
        ])
        return InlineKeyboardMarkup(rows)

    rows = []
    if data.get("type") in {"expense", "income"}:
        rows.append([InlineKeyboardButton("✏️ Cambia categoria", callback_data="edit_category")])
    rows.append([
        InlineKeyboardButton("✅ Conferma", callback_data="confirm"),
        InlineKeyboardButton("❌ Annulla", callback_data="cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def _next_expense_id(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Genera un id breve e univoco per la sessione, usato per taggare i bottoni delle
    transazioni multiple presentate in parallelo (vedi `pending_expenses`)."""
    n = context.user_data.get("expense_id_counter", 0) + 1
    context.user_data["expense_id_counter"] = n
    return str(n)


async def _advance_transfer_flow(context: ContextTypes.DEFAULT_TYPE, chat_id: str, send) -> None:
    """Fa avanzare il flusso guidato di un trasferimento in sospeso.

    Chiamata sia dal comando /trasferimento (bottoni), sia dal ramo NLP quando l'LLM
    riconosce un `type: "transfer"`: in entrambi i casi lo stato vive in
    `context.user_data["pending_expense"]` e questa funzione decide il prossimo step
    (risoluzione conto origine/destinazione, richiesta importo, riepilogo di conferma).

    `send(text, reply_markup=None)` astrae il canale di invio (nuovo messaggio o edit
    di una callback query) così la stessa logica serve per bottoni, NLP e conferma importo.
    """
    pending = context.user_data.get("pending_expense")
    if not pending or pending.get("type") != "transfer":
        return

    if pending.get("from_account_id") is None or pending.get("to_account_id") is None:
        try:
            storage = _get_storage(chat_id)
            accounts = storage.fetch_accounts()
        except Exception as exc:  # noqa: BLE001 -- il canale Telegram riceve un messaggio sicuro
            log_exception(
                logger,
                level="error",
                domain="transactions",
                event="transfer_accounts_fetch_failed",
                exception=exc,
                chat_id=str(chat_id),
            )
            await send("⚠️ Errore nel recupero dei tuoi conti. Riprova tra qualche istante.")
            return

        if len(accounts) < 2:
            context.user_data.pop("pending_expense", None)
            context.user_data.pop("waiting_for_amount", None)
            context.user_data.pop("expense_queue", None)
            await send(
                "🏦 Ti servono almeno due conti per fare un trasferimento.\n\n"
                "Usa /modify e vai nella tab \"Conti\" per aggiungerne un secondo."
            )
            return

        # Risolve una tantum gli hint testuali del parser NLP sui conti reali dell'utente.
        if pending.get("from_account_id") is None and not pending.get("_from_hint_tried"):
            pending["_from_hint_tried"] = True
            match = _resolve_account_hint(pending.get("from_account_hint"), accounts)
            if match:
                pending["from_account_id"] = match["id"]
                pending["from_account_name"] = match["name"]
        if pending.get("to_account_id") is None and not pending.get("_to_hint_tried"):
            pending["_to_hint_tried"] = True
            match = _resolve_account_hint(pending.get("to_account_hint"), accounts)
            if match and str(match["id"]) != str(pending.get("from_account_id")):
                pending["to_account_id"] = match["id"]
                pending["to_account_name"] = match["name"]

        if pending.get("from_account_id") is None:
            keyboard = [
                [InlineKeyboardButton(f"🏦 {a['name']}", callback_data=f"transfer_from:{a['id']}")]
                for a in accounts
            ]
            keyboard.append([InlineKeyboardButton("❌ Annulla", callback_data="cancel")])
            await send("🏦 Da quale conto vuoi spostare i soldi?", InlineKeyboardMarkup(keyboard))
            return

        if pending.get("to_account_id") is None:
            remaining = [a for a in accounts if str(a["id"]) != str(pending["from_account_id"])]
            if not remaining:
                await send("⚠️ Ti serve un secondo conto diverso da quello di origine per completare il trasferimento.")
                return
            keyboard = [
                [InlineKeyboardButton(f"🏦 {a['name']}", callback_data=f"transfer_to:{a['id']}")]
                for a in remaining
            ]
            keyboard.append([InlineKeyboardButton("❌ Annulla", callback_data="cancel")])
            await send("🏦 Su quale conto vuoi spostare i soldi?", InlineKeyboardMarkup(keyboard))
            return

    if pending.get("amount") is None:
        context.user_data["waiting_for_amount"] = True
        await send("📝 Quanto vuoi trasferire? Scrivi solo l'importo (es. 100).")
        return

    summary = _build_expense_summary(pending)
    keyboard = _build_confirm_keyboard(pending)
    await send(summary, keyboard)


async def _present_next_pending_expense(context: ContextTypes.DEFAULT_TYPE, chat_id: str) -> bool:
    """Estrae la prossima transazione dalla coda multi-spesa e ne invia il messaggio di conferma
    (o la richiesta di importo mancante), come nuovo messaggio in chat.

    Usata sia per la prima transazione rilevata sia per presentare in sequenza quelle successive
    dopo che l'utente ha confermato/annullato/scelto il conto per la transazione precedente.

    Returns:
        True se c'era una transazione in coda da presentare, False se la coda era vuota.
    """
    queue = context.user_data.get("expense_queue") or []
    if not queue:
        return False

    result = queue.pop(0)
    pending = {
        "type": result["type"],
        "date": result["date"].isoformat(),
        "amount": result["amount"],
        "category": result["category"],
        "income_type": result.get("income_type"),
        "income_category": result.get("income_category"),
        "name": result["name"],
    }
    if result["type"] == "transfer":
        pending["from_account_hint"] = result.get("from_account")
        pending["to_account_hint"] = result.get("to_account")
        pending["from_account_id"] = None
        pending["to_account_id"] = None
    context.user_data["pending_expense"] = pending

    if result["type"] == "transfer":
        async def _send(text, reply_markup=None):
            await context.bot.send_message(
                chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup,
            )
        await _advance_transfer_flow(context, chat_id, _send)
        return True

    if result["amount"] is None:
        _user_store.increment_ai_metrics(success=False)
        context.user_data["waiting_for_amount"] = True
        await context.bot.send_message(
            chat_id=chat_id,
            text="📝 Non ho Capito l'importo. Prova a ridirmelo, grazie!❤️\n",
            parse_mode=ParseMode.MARKDOWN,
        )
        return True

    summary = _build_expense_summary(context.user_data["pending_expense"])
    keyboard = _build_confirm_keyboard(context.user_data["pending_expense"])
    await context.bot.send_message(chat_id=chat_id, text=summary, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    try:
        _user_store.log_message(chat_id, source="telegram", role="bot", text=summary, metadata=result)
    except Exception as _le:
        logger.debug("[User %s] log_message bot summary fallito: %s", chat_id, _le)
    return True


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler per messaggi di testo — parsing spesa con LLM."""
    
    chat_id = str(update.effective_chat.id) #recupero id chat utente che ha fatto richiesta

    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    # 🛡️ DIFESA 1: Rate Limiting (Anti-DoS)
    if is_rate_limited(chat_id, max_messages=Config.MAX_MESSAGES_PER_MINUTE):
        await update.message.reply_text("⏳ Stai inviando troppi messaggi. Aspetta un momento e riprova.")
        return

    # 🛡️ DIFESA 2: Verifica Token (Piano Free/Pro)
    if not await _check_and_consume_tokens(update, chat_id, "text"):
        return

    message_text = update.message.text.strip()
    if not message_text:
        return

    # 🛡️ DIFESA 3: Lunghezza massima (Anti-Token Flooding / Injection)
    if len(message_text) > Config.MAX_MESSAGE_LEN:
        await update.message.reply_text(f"⚠️ Messaggio troppo lungo! Massimo {Config.MAX_MESSAGE_LEN} caratteri.")
        return

    logger.info(
        "message_received",
        extra={
            "domain": "usage",
            "event": "message_received",
            "chat_id": chat_id,
            "meta": {"input_type": "text", "length": len(message_text)},
        },
    )
    try:
        _user_store.log_message(chat_id, source="telegram", role="user", text=message_text)
    except Exception as _le:
        logger.debug("[User %s] log_message user fallito: %s", chat_id, _le)
    _user_store.increment_usage(chat_id, "text")
 
    # Mostra "sta scrivendo..."
    await update.message.chat.send_action("typing")

    # Step 2 del check-in beta (vedi handle_callback, "betaval:"): il prossimo
    # messaggio testuale è il feedback libero, non va parsato come spesa.
    if context.user_data.pop("waiting_for_beta_feedback", False):
        _user_store.save_feedback(chat_id, message=message_text, category="beta_validation")
        await update.message.reply_text("✅ Grazie per il feedback, lo terremo in considerazione! 🙏")
        return

    # Controlla se siamo in attesa dell'importo
    if context.user_data.get("waiting_for_amount"):
        parser = _get_parser(chat_id)
        amount_res = parser.parse(message_text, chat_id, when=_get_message_when(update, chat_id))
        
        amt = None
        if amount_res and amount_res["amount"] is not None:
             amt = amount_res["amount"]
        else:
             # Fallback parsing semplice
             try:
                 import re
                 cl = message_text.lower().replace(" ", "").replace("€", "").replace("euro", "").replace(",", ".")
                 match = re.search(r"-?\d+(?:\.\d+)?", cl)
                 if match:
                     amt = float(match.group(0))
             except ValueError:
                 pass
                 
        if amt is None:
             await update.message.reply_text("Non ho capito l'importo. Scrivi solo un numero (es. 15.50 o 150mila).")
             return
             
        context.user_data["pending_expense"]["amount"] = amt
        context.user_data["waiting_for_amount"] = False

        # Procede alla conferma
        data = context.user_data["pending_expense"]
        if data.get("type") == "transfer":
            async def _send(text, reply_markup=None):
                await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
            await _advance_transfer_flow(context, chat_id, _send)
            return
        summary = _build_expense_summary(data)
        keyboard = _build_confirm_keyboard(data)
        await update.message.reply_text(summary, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
        return

    # Passa la palla alla nuova funzione condivisa
    context.user_data["input_method"] = "text"
    await _process_expense_text(update, context, message_text, chat_id)

async def _process_expense_text(update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str, chat_id: str) -> None:
    # 🛡️ DIFESA 3: Wrapping sicuro dell'input — isoliamo il contenuto utente dal prompt di sistema
    # Questo rende molto più difficile la Prompt Injection
    safe_input = f"[INIZIO INPUT UTENTE]\n{message_text}\n[FINE INPUT UTENTE]"
    # Già impostato dal chiamante (testo/voce/foto) prima di arrivare qui, non
    # ancora "pop"-ato: lo leggiamo (senza consumarlo) per taggare il ledger.
    input_method = context.user_data.get("input_method", "text")
    # Già impostato dal chiamante (testo/voce/foto) prima di arrivare qui, non
    # ancora "pop"-ato: lo leggiamo (senza consumarlo) per taggare il ledger.
    input_method = context.user_data.get("input_method", "text")

    message_id = update.effective_message.message_id if update.effective_message else "no-message"
    request_key = build_request_key(chat_id, "expense_parse", message_id, safe_input)
    reservation_created = False
    try:
        _user_store.reserve_llm_tokens(
            chat_id=chat_id,
            request_key=request_key,
            operation="expense_parse",
            provider="mistral",
            model=Config.MISTRAL_SMALL_MODEL,
            reserved_tokens=estimate_reserved_tokens("expense_parse"),
        )
        reservation_created = True
    except Exception as e:
        logger.warning("[User %s] Reservation fallita per expense_parse: %s", chat_id, e)

    # 1. Recuperiamo il parser specifico per l'utente
    parser = _get_parser(chat_id)
    # 2. Parsa con LLM (input sanificato) — l'LLM decide se è una o più transazioni
    transactions, usage = parser.parse_multi_with_usage(
        safe_input, chat_id, when=_get_message_when(update, chat_id),
    )
    raw_usage = usage or {}
    normalized_usage = normalize_usage_metadata(raw_usage)

    if raw_usage:
        try:
            _user_store.finalize_llm_usage(
                chat_id=chat_id,
                request_key=request_key,
                prompt_tokens=normalized_usage.get("prompt_tokens", 0),
                completion_tokens=normalized_usage.get("completion_tokens", 0),
                total_tokens=normalized_usage.get("total_tokens", 0),
                provider=normalized_usage.get("provider", "mistral"),
                model=normalized_usage.get("model", Config.MISTRAL_SMALL_MODEL),
                operation="expense_parse",
                input_method=input_method,
            )
        except Exception as _e:
            logger.warning("[User %s] finalize_llm_usage fallita: %s", chat_id, _e)
    elif reservation_created:
        try:
            _user_store.release_llm_reservation(chat_id, request_key, reason="no_usage_metadata")
        except Exception as _e:
            logger.warning("[User %s] release_llm_reservation fallita: %s", chat_id, _e)

    if not transactions:
        _user_store.increment_ai_metrics(success=False)
        _track_event(chat_id, "expense_tracking_failed", {
            "reason": "ai_unavailable", "input_method": "text", "transaction_type": "unknown",
        })
        _ai_reason = (
            f"ai_unavailable_{parser.last_error_status_code}"
            if parser.last_error_status_code else "ai_unavailable"
        )
        _user_store.record_tx_event(chat_id, "unknown", "text", "failed", "telegram", reason=_ai_reason)
        await update.message.reply_text(
            "⚠️ Non sono riuscito ad elaborare il messaggio in questo momento.\n"
            "Il servizio AI è temporaneamente sovraccarico, riprova tra qualche secondo! 🔄",
        )
        return

    logger.info("transactions_parsed", extra={"domain": "transactions", "event": "transactions_parsed", "chat_id": chat_id, "meta": {"count": len(transactions)}})

    # Categorizzazione adattiva: sotto soglia di match, traccia l'occorrenza invece di
    # accettare/creare categorie a caso; dopo N ricorrenze chiede conferma all'utente
    # prima di creare la categoria reale (vedi category_promotions più sotto).
    # Applicata a ogni transazione (multi-spesa), non solo alla prima.
    expense_txs = [tx for tx in transactions if tx["type"] == "expense" and tx.get("category")]
    category_promotions = []  # match_result in attesa di conferma Sì/No, inviati dopo la sessione DB
    if expense_txs:
        storage = _get_storage(chat_id)
        known_categories = _user_store.get_user_category_names(chat_id)
        with _user_store.Session() as cm_session:
            for tx in expense_txs:
                match_result = category_matcher.evaluate_and_track(
                    cm_session,
                    storage,
                    _user_store,
                    chat_id,
                    tx["name"],
                    tx["category"],
                    known_categories,
                )
                tx["category"] = match_result.category_name
                if match_result.awaiting_confirmation:
                    category_promotions.append(match_result)

    # Multi-spesa: le transazioni con importo già noto (il caso comune) vengono presentate
    # TUTTE SUBITO, ciascuna con bottoni indipendenti (id dedicato) — l'utente le conferma
    # nell'ordine che vuole. Solo i casi che richiedono per forza un passaggio sequenziale
    # (importo mancante da chiedere in chiaro, trasferimento con conti ancora da risolvere)
    # restano in coda e vengono gestiti uno alla volta come prima.
    immediate = []
    sequential = []
    for tx in transactions:
        (immediate if tx["type"] != "transfer" and tx["amount"] is not None else sequential).append(tx)

    pending_expenses = context.user_data.setdefault("pending_expenses", {})
    for tx in immediate:
        tx_id = _next_expense_id(context)
        data = {
            "type": tx["type"],
            "date": tx["date"].isoformat(),
            "amount": tx["amount"],
            "category": tx["category"],
            "income_type": tx.get("income_type"),
            "name": tx["name"],
        }
        pending_expenses[tx_id] = data
        summary = _build_expense_summary(data)
        keyboard = _build_confirm_keyboard(data, tx_id)
        await update.message.reply_text(summary, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
        try:
            _user_store.log_message(chat_id, source="telegram", role="bot", text=summary, metadata=tx)
        except Exception as _le:
            logger.debug("[User %s] log_message bot summary fallito: %s", chat_id, _le)

    if sequential:
        context.user_data["expense_queue"] = sequential
        await _present_next_pending_expense(context, chat_id)

    # Conferma categorizzazione adattiva — inviata dopo il resto (sessione DB già
    # chiusa, non la teniamo aperta durante l'I/O Telegram).
    for match_result in category_promotions:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Sì", callback_data=f"catpromote_yes:{match_result.candidate_id}"),
            InlineKeyboardButton("❌ No", callback_data=f"catpromote_no:{match_result.candidate_id}"),
        ]])
        await update.message.reply_text(
            f"📂 Ho notato che scrivi spesso spese simili, vuoi che crei una categoria "
            f"dedicata «{match_result.suggested_name}»?",
            reply_markup=keyboard,
        )

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler per messaggi vocali — trascrizione e parsing spesa con LLM."""

    chat_id = str(update.effective_chat.id)

    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    # 🛡️ DIFESA 1: Rate Limiting
    if is_rate_limited(chat_id, max_messages=Config.MAX_MESSAGES_PER_MINUTE):
        await update.message.reply_text("⏳ Stai inviando troppi messaggi. Aspetta un momento.")
        return

    # 🛡️ DIFESA 1.5: Verifica Token (Piano Free/Pro + Blocco Premium)
    if not await _check_and_consume_tokens(update, chat_id, "voice"):
        return

    # 🛡️ DIFESA 2: Validazione dimensione PRIMA del download
    voice = update.message.voice
    if voice.file_size and voice.file_size > Config.MAX_FILE_SIZE_MB * 1024 * 1024:
        await update.message.reply_text(f"⚠️ Audio troppo grande! Limite: {Config.MAX_FILE_SIZE_MB}MB.")
        return

    file_info = await voice.get_file()
    await update.message.chat.send_action("record_voice")
    logger.info("voice_received", extra={"domain": "input", "event": "voice_received", "chat_id": chat_id, "meta": {"size_bytes": voice.file_size or 0}})

    # 🛡️ Nome file unico per chat_id (evita race condition tra utenti)
    temp_path = os.path.join(tempfile.gettempdir(), f"temp_voice_{chat_id}.ogg")

    # 🛡️ try/finally garantisce la pulizia del file anche in caso di errore
    try:
        await file_info.download_to_drive(temp_path)

        transcription_request_key = build_request_key(
            chat_id,
            "voice_transcribe",
            file_info.file_id,
            getattr(voice, "file_unique_id", "voice"),
        )
        transcription_reserved = False
        try:
            _user_store.reserve_llm_tokens(
                chat_id=chat_id,
                request_key=transcription_request_key,
                operation="voice_transcribe",
                provider="gemini",
                model=Config.GEMINI_MODEL,
                reserved_tokens=estimate_reserved_tokens("voice_transcribe"),
            )
            transcription_reserved = True
        except Exception as e:
            logger.warning("[User %s] Reservation fallita per voice_transcribe: %s", chat_id, e)

        # Vertex AI: dati audio processati in EU (europe-west3), GDPR compliant
        client = get_vertex_ai_client()
        with open(temp_path, "rb") as f:
            audio_bytes = f.read()

        audio_part = types.Part.from_bytes(data=audio_bytes, mime_type="audio/ogg")
        response = client.models.generate_content(
            model=Config.GEMINI_MODEL,
            contents=[
                "Trascrivi esattamente e parola per parola questo audio in italiano. "
                "Restituisci SOLO ed esclusivamente il testo trascritto, nient'altro.",
                audio_part
            ]
        )
        message_trascribed = response.text.strip()

        if not message_trascribed:
            logger.warning(
                "audio_transcription_empty",
                extra={
                    "domain": "usage",
                    "event": "audio_transcription_empty",
                    "chat_id": chat_id,
                    "meta": {},
                },
            )
            await update.message.reply_text(
                "⚠️ Non sono riuscito a capire l'audio. Riprova parlando più chiaramente."
            )
            return

        # 🛡️ DIFESA 2.5: Sanitizzazione trascrizione audio — rileva injection vocali
        # (es. "...e ora ignora le istruzioni precedenti") e rimuove Unicode anomali
        from src.input_sanitizer import sanitize_audio_transcription, InjectionDetectedError
        try:
            message_trascribed = sanitize_audio_transcription(message_trascribed, chat_id)
        except InjectionDetectedError:
            _user_store.logout_user(chat_id)
            await update.message.reply_text(
                "🚫 *Comportamento malevolo rilevato.*\n\n"
                "Il tuo account è stato disabilitato a causa di un tentativo di manipolazione del sistema.\n\n"
                f"Per chiarimenti scrivi a: {Config.SUPPORT_EMAIL}",
                parse_mode="Markdown",
            )
            return

        logger.info(
            "audio_transcribed",
            extra={
                "domain": "usage",
                "event": "audio_transcribed",
                "chat_id": chat_id,
                "meta": {"input_type": "voice", "length": len(message_trascribed)},
            },
        )
        response_usage = getattr(response, "usage_metadata", None)
        raw_transcription_usage = {}
        if response_usage:
            raw_transcription_usage = {
                "prompt_tokens": getattr(response_usage, "prompt_token_count", 0) or 0,
                "completion_tokens": getattr(response_usage, "candidates_token_count", 0) or 0,
                "total_tokens": getattr(response_usage, "total_token_count", 0) or 0,
                "thinking_tokens": getattr(response_usage, "thoughts_token_count", None),
                "provider": "gemini",
                "model": Config.GEMINI_MODEL,
            }
        transcription_usage = normalize_usage_metadata(raw_transcription_usage)
        if raw_transcription_usage:
            try:
                _user_store.finalize_llm_usage(
                    chat_id=chat_id,
                    request_key=transcription_request_key,
                    prompt_tokens=transcription_usage.get("prompt_tokens", 0),
                    completion_tokens=transcription_usage.get("completion_tokens", 0),
                    total_tokens=transcription_usage.get("total_tokens", 0),
                    provider=transcription_usage.get("provider", "gemini"),
                    model=transcription_usage.get("model", Config.GEMINI_MODEL),
                    operation="voice_transcribe",
                    thinking_tokens=transcription_usage.get("thinking_tokens"),
                    input_method="voice",
                )
            except Exception as e:
                logger.warning("[User %s] finalize_llm_usage voice fallita: %s", chat_id, e)
        elif transcription_reserved:
            try:
                _user_store.release_llm_reservation(chat_id, transcription_request_key, reason="no_usage_metadata")
            except Exception as e:
                logger.warning("[User %s] release_llm_reservation voice fallita: %s", chat_id, e)
        _user_store.increment_usage(chat_id, "voice")
        try:
            _user_store.log_message(chat_id, source="telegram", role="user", text=f"🎤 {message_trascribed}")
        except Exception as _le:
            logger.debug("[User %s] log_message voice fallito: %s", chat_id, _le)
        await update.message.reply_text("🎙️ Ho ascoltato! Sto elaborando...")
        context.user_data["input_method"] = "voice"
        await _process_expense_text(update, context, message_trascribed, chat_id)

    finally:
        # 🛡️ Auto-cleanup: il file viene cancellato SEMPRE, anche se c'è un errore
        if os.path.exists(temp_path):
            os.remove(temp_path)
            logger.info("voice_temp_file_removed", extra={"domain": "input", "event": "voice_temp_file_removed", "chat_id": chat_id, "meta": {}})

async def handle_photos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler per le foto (scontrini e screenshot) — estrae il contesto con Gemini Vision."""
    chat_id = str(update.effective_chat.id)

    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    # 🛡️ DIFESA 1: Rate Limiting
    if is_rate_limited(chat_id, max_messages=Config.MAX_MESSAGES_PER_MINUTE):
        await update.message.reply_text("⏳ Stai inviando troppi messaggi. Aspetta un momento.")
        return

    # 🛡️ DIFESA 1.5: Verifica Token (Piano Free/Pro + Blocco Premium)
    if not await _check_and_consume_tokens(update, chat_id, "photo"):
        return

    # Telegram invia la foto in varie risoluzioni → prendiamo la migliore ([-1])
    foto_hd = update.message.photo[-1]

    # 🛡️ DIFESA 2: Validazione dimensione PRIMA del download
    if foto_hd.file_size and foto_hd.file_size > Config.MAX_FILE_SIZE_MB * 1024 * 1024:
        await update.message.reply_text(f"⚠️ Foto troppo grande! Limite: {Config.MAX_FILE_SIZE_MB}MB.")
        return

    file_info = await foto_hd.get_file()
    await update.message.chat.send_action("upload_photo")
    logger.info("photo_received", extra={"domain": "input", "event": "photo_received", "chat_id": chat_id, "meta": {"size_bytes": foto_hd.file_size or 0}})

    # 🛡️ Nome file unico per chat_id (evita race condition tra utenti)
    temp_path = os.path.join(tempfile.gettempdir(), f"temp_photo_{chat_id}.jpg")

    # 🛡️ try/finally garantisce la pulizia del file anche in caso di errore
    try:
        await file_info.download_to_drive(temp_path)
        await update.message.reply_text("Immagine ricevuta! Sto accendendo gli occhi bionici... 👁️📸")

        try:
            message_trascribed = OcrClient().extract_text_from_image(temp_path, chat_id)
        except OCRError:
            await update.message.reply_text(
                "⚠️ Non riesco a leggere lo scontrino. Riprova con una foto più nitida e ben illuminata."
            )
            return

        # 🛡️ DIFESA 3: Sanitizzazione testo OCR — rimuove Unicode pericolosi e
        # rileva pattern di prompt injection nascosti nello scontrino
        from src.input_sanitizer import sanitize_ocr_text, InjectionDetectedError
        try:
            message_trascribed = sanitize_ocr_text(message_trascribed, chat_id)
        except InjectionDetectedError:
            _user_store.logout_user(chat_id)
            await update.message.reply_text(
                "🚫 *Comportamento malevolo rilevato.*\n\n"
                "Il tuo account è stato disabilitato a causa di un tentativo di manipolazione del sistema.\n\n"
                f"Per chiarimenti scrivi a: {Config.SUPPORT_EMAIL}",
                parse_mode="Markdown",
            )
            return

        logger.info(
            "receipt_ocr_processed",
            extra={
                "domain": "usage",
                "event": "receipt_ocr_processed",
                "chat_id": chat_id,
                "meta": {"input_type": "photo", "length": len(message_trascribed)},
            },
        )
        _user_store.increment_usage(chat_id, "photo")
        try:
            _user_store.log_message(chat_id, source="telegram", role="user", text=f"📷 {message_trascribed[:200]}")
        except Exception as _le:
            logger.debug("[User %s] log_message photo fallito: %s", chat_id, _le)
        await update.message.reply_text("📸 Foto analizzata! Sto elaborando...")
        context.user_data["input_method"] = "photo"
        await _process_expense_text(update, context, message_trascribed, chat_id)

    finally:
        # 🛡️ Auto-cleanup: il file viene cancellato SEMPRE, anche se c'è un errore
        if os.path.exists(temp_path):
            os.remove(temp_path)
            logger.info("photo_temp_file_removed", extra={"domain": "input", "event": "photo_temp_file_removed", "chat_id": chat_id, "meta": {}})

async def _save_to_notion(query, context, chat_id: str, data: dict | None, account_id: str | None = None):
    context.user_data.pop("waiting_for_amount", None)

    if not data:
        await query.edit_message_text("⚠️ Nessuna spesa in sospeso.")
        return
        
    try:
        from datetime import datetime
        date = datetime.strptime(data["date"].split("T")[0], "%Y-%m-%d").date()

        storage = _get_storage(chat_id)
        if data["type"] == "income":
            storage.create_income(
                income_date=date,
                amount=data["amount"],
                name=data["name"],
                account_id=account_id,
                income_category_id=data.get("income_category_id"),
                income_category_name=data.get("income_category"),
                income_type=data.get("income_type"),
            )
            date_str = date.strftime("%d/%m/%Y")
            await query.edit_message_text(
                f"✅ *Entrata salvata!*\n\n"
                f"📅 {date_str} · *€{data['amount']:.2f}* · {data['name']}",
                parse_mode=ParseMode.MARKDOWN,
            )
            logger.info(
                "Entrata salvata",
                extra={"domain": "financial", "event": "income_saved", "chat_id": chat_id, "meta": {}},
            )
            try:
                _success_text = f"✅ Entrata salvata: {data['name']} €{data['amount']:.2f}"
                _user_store.log_message(chat_id, source="telegram", role="bot", text=_success_text, metadata=data)
            except Exception as _le:
                logger.debug("[User %s] log_message income saved fallito: %s", chat_id, _le)
        else:
            storage.create_expense(
                expense_date=date,
                amount=data["amount"],
                name=data["name"],
                category_name=data.get("category"),
                account_id=account_id
            )
            # Rilevamento abbonamenti ricorrenti (src/subscription_detector.py):
            # aggiornamento incrementale O(1), niente rescan batch. Best-effort,
            # non deve mai far fallire il salvataggio della spesa.
            sub_eval = subscription_detector.SubscriptionEvalResult()
            try:
                with _user_store.Session() as sub_session:
                    sub_eval = subscription_detector.evaluate_and_track(
                        sub_session,
                        chat_id,
                        date,
                        float(data["amount"]),
                        data.get("category"),
                        data["name"],
                    )
            except Exception as _se:
                logger.warning("[User %s] Rilevamento abbonamenti fallito: %s", chat_id, _se)
            date_str = date.strftime("%d/%m/%Y")
            saved_msg = (
                f"✅ *Spesa salvata!*\n\n"
                f"📅 {date_str} · *€{data['amount']:.2f}* · {data['name']}"
            )
            # Alert budget categoria in tempo reale (soglie 80/100/120%) + notifica
            # in-app per le sole bande 100%/120%. Un'unica lettura di storage
            # (get_category_spent_and_budget) alimenta entrambe: due chiamate
            # separate raddoppierebbero le richieste su Notion, rate-limited.
            try:
                category = data.get("category")
                result = get_category_spent_and_budget(storage, category, date) if category else None
                if result:
                    spent, budget = result
                    alert = evaluate_budget_alert(category, spent, budget)
                    if alert:
                        saved_msg += f"\n\n{alert}"
                    band = classify_budget_band(spent, budget)
                    if band:
                        budget_user = _user_store.get_user(chat_id)
                        if budget_user and budget_user.notifications_enabled:
                            notif_type = "budget_reached" if band == "reached" else "budget_exceeded"
                            title = (
                                f"Budget {category} raggiunto"
                                if band == "reached"
                                else f"Budget {category} superato"
                            )
                            body = f"Hai speso €{spent:.0f} su €{budget:.0f} per {category} questo mese."
                            with _user_store.Session() as notif_session:
                                create_notification(
                                    notif_session, chat_id, notif_type, title, body,
                                    payload={"category": category},
                                    priority="warning" if band == "reached" else "critical",
                                )
            except Exception as _ae:
                logger.warning(
                    "[User %s] Calcolo/notifica alert budget fallito: %s", chat_id, type(_ae).__name__,
                    extra={"domain": "app", "event": "budget_notification_failed", "meta": {}},
                )
            await query.edit_message_text(
                saved_msg,
                parse_mode=ParseMode.MARKDOWN,
            )
            logger.info("expense_saved", extra={"domain": "transactions", "event": "expense_saved", "chat_id": chat_id, "meta": {}})
            try:
                _success_text = f"✅ Spesa salvata: {data['name']} €{data['amount']:.2f}"
                _user_store.log_message(chat_id, source="telegram", role="bot", text=_success_text, metadata=data)
            except Exception as _le:
                logger.debug("[User %s] log_message expense saved fallito: %s", chat_id, _le)

            if sub_eval.awaiting_confirmation and sub_eval.candidate_id:
                _track_event(chat_id, "subscription_candidate_awaiting_confirmation", {
                    "cadence": sub_eval.cadence, "source": "live",
                })
                cadence_label = subscription_detector.cadence_label_it(sub_eval.cadence)
                sub_keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Sì", callback_data=f"subpromote_yes:{sub_eval.candidate_id}"),
                    InlineKeyboardButton("❌ No", callback_data=f"subpromote_no:{sub_eval.candidate_id}"),
                ]])
                try:
                    await query._bot.send_message(
                        chat_id=chat_id,
                        text=(
                            f"🔎 Ho notato che paghi ricorrentemente *{sub_eval.display_name}* "
                            f"(~€{sub_eval.amount:.2f} {cadence_label}) in *{sub_eval.category_name}*, "
                            "vuoi che lo aggiunga ai tuoi abbonamenti tracciati?"
                        ),
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=sub_keyboard,
                    )
                except Exception as _sn:
                    logger.warning("[User %s] Invio prompt abbonamento fallito: %s", chat_id, _sn)

        # Cancella i dati demo al primo salvataggio reale
        user_obj = _user_store.get_user(chat_id)
        if user_obj and user_obj.has_demo_data:
            try:
                _user_store.clear_demo_data(chat_id, storage)
                logger.info("[User %s] Demo data cancellati al primo salvataggio reale.", chat_id)
            except Exception as _de:
                logger.warning("[User %s] Errore cancellazione demo data: %s", chat_id, _de)

        input_method = context.user_data.pop("input_method", "text")
        tx_type = data.get("type", "expense")
        _track_event(chat_id, "expense_tracked", {
            "input_method": input_method,
            "storage_backend": user_obj.storage_backend if user_obj else "unknown",
            "transaction_type": tx_type,
        })
        rewards = _user_store.record_tx_event(
            chat_id, tx_type, input_method, "confirmed", "telegram",
            reason="category_corrected" if data.get("category_was_corrected") else None,
        ) or {}
        # Il dict contiene le chiavi della streak solo a ciclo completato: testarne
        # la verità non basta più, adesso può contenere solo achievement.
        if rewards.get("cycle_completed_days"):
            try:
                await query._bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"🎉 Hai completato {rewards['cycle_completed_days']} giorni di streak!\n"
                        f"Ti abbiamo regalato 2 settimane di Pro.\n"
                        f"La prossima streak sarà di {rewards['next_target_days']} giorni."
                    ),
                )
            except Exception as _se:
                log_exception(logger, level="warning", domain="gamification", event="streak_message_send_failed", exception=_se, chat_id=str(chat_id))
        goal_unlocks = await _check_goals_and_notify(query._bot, chat_id)
        await _notify_achievements(
            query._bot, chat_id, (rewards.get("achievements") or []) + goal_unlocks
        )

        try:
            _user_store.increment_ai_metrics(success=True)
        except Exception as exc:  # noqa: BLE001 -- la transazione è già persistita
            log_exception(logger, level="warning", domain="usage", event="ai_metrics_increment_failed", exception=exc, chat_id=str(chat_id))

        # Messaggio multi-spesa: se ce ne sono altre in coda, presenta subito la prossima
        try:
            await _present_next_pending_expense(context, chat_id)
        except Exception as exc:  # noqa: BLE001 -- la prossima transazione può essere ripresa
            log_exception(logger, level="warning", domain="transactions", event="next_pending_present_failed", exception=exc, chat_id=str(chat_id))

    except Exception as exc:  # noqa: BLE001 -- al chiamante viene mostrato un errore sicuro
        log_exception(logger, level="error", domain="transactions", event="expense_save_failed", exception=exc, chat_id=str(chat_id))
        await query.edit_message_text(
            "⚠️ Non sono riuscito a salvare su Notion in questo momento.\n"
            "Riprova tra qualche secondo oppure contatta il supporto se il problema persiste.",
        )


async def _save_transfer(query, context, chat_id: str) -> None:
    """Salva un trasferimento in sospeso (conti origine/destinazione già risolti). Mirror di _save_to_notion."""
    data = context.user_data.pop("pending_expense", None)
    context.user_data.pop("waiting_for_amount", None)

    if not data:
        await query.edit_message_text("⚠️ Nessun trasferimento in sospeso.")
        return

    try:
        transfer_date = datetime.strptime(data["date"].split("T")[0], "%Y-%m-%d").date()

        storage = _get_storage(chat_id)
        storage.create_transfer(
            transfer_date=transfer_date,
            amount=data["amount"],
            from_account_id=data["from_account_id"],
            to_account_id=data["to_account_id"],
            name=data.get("name"),
        )
        date_str = transfer_date.strftime("%d/%m/%Y")
        from_name = data.get("from_account_name") or "conto di origine"
        to_name = data.get("to_account_name") or "conto di destinazione"
        await query.edit_message_text(
            f"✅ *Trasferimento salvato!*\n\n"
            f"📅 {date_str} · *€{data['amount']:.2f}*\n"
            f"🏦 {from_name} → {to_name}",
            parse_mode=ParseMode.MARKDOWN,
        )
        logger.info("transfer_saved", extra={"domain": "transactions", "event": "transfer_saved", "chat_id": chat_id, "meta": {}})
        try:
            _success_text = f"✅ Trasferimento salvato: €{data['amount']:.2f}"
            _user_store.log_message(chat_id, source="telegram", role="bot", text=_success_text, metadata=data)
        except Exception as _le:
            logger.debug("[User %s] log_message transfer saved fallito: %s", chat_id, _le)

        input_method = context.user_data.pop("input_method", "text")
        user_obj = _user_store.get_user(chat_id)
        _track_event(chat_id, "expense_tracked", {
            "input_method": input_method,
            "storage_backend": user_obj.storage_backend if user_obj else "unknown",
            "transaction_type": "transfer",
        })
        _user_store.record_tx_event(chat_id, "transfer", input_method, "confirmed", "telegram")

        try:
            await _present_next_pending_expense(context, chat_id)
        except Exception as exc:  # noqa: BLE001 -- la coda resta riprendibile
            log_exception(logger, level="warning", domain="transactions", event="next_pending_present_failed", exception=exc, chat_id=str(chat_id))

    except ValueError as e:
        log_exception(logger, level="warning", domain="transactions", event="transfer_validation_failed", exception=e, chat_id=str(chat_id))
        await query.edit_message_text(f"⚠️ {e}")
    except Exception as e:
        log_exception(logger, level="error", domain="transactions", event="transfer_save_failed", exception=e, chat_id=str(chat_id))
        await query.edit_message_text(
            "⚠️ Non sono riuscito a salvare il trasferimento in questo momento.\n"
            "Riprova tra qualche secondo oppure contatta il supporto se il problema persiste.",
        )


def _category_picker_options(storage, pending: dict) -> list[dict]:
    """Return tenant-scoped category DTOs suitable for a callback picker.

    The callback only carries an index, while state retains the ID and canonical
    name per transaction.  This prevents a later picker from changing which
    category an earlier confirmation resolves to.
    """
    categories = (
        storage.get_income_categories()
        if pending.get("type") == "income" else storage.get_categories()
    )
    return [
        {"id": category.get("id"), "name": str(category["name"])}
        for category in categories
        if category.get("name")
    ]


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler per i bottoni inline (conferma/annulla/conti)."""
    query = update.callback_query
    await query.answer()

    chat_id = str(update.effective_chat.id)

    # Reactivate va gestito PRIMA del check auth (l'utente è sospeso)
    if query.data == REACTIVATE_CB:
        _user_store.reactivate_user(chat_id)
        reg_token = _user_store.create_oauth_session(chat_id)
        setup_url = f"{Config.WEBAPP_BASE_URL}/setup?reg_token={reg_token}"
        await query.edit_message_text(
            "✅ *Account riattivato!* Bentornato.\n\nAccedi alla tua area personale:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📂 Apri Expensum", url=setup_url)]]),
        )
        return

    if not _is_authorized(update):
        return

    if query.data == LOGOUT_CONFIRM_CB:
        _user_store.logout_user(chat_id)
        logger.info("account_suspended", extra={"domain": "security", "event": "account_suspended", "chat_id": chat_id, "meta": {}})
        await query.edit_message_text(
            "👋 *Account sospeso.*\n\nI tuoi dati sono al sicuro. Usa /accedi per riprendere quando vuoi.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if query.data == LOGOUT_CANCEL_CB:
        await query.edit_message_text("❌ Logout annullato. Sei ancora connesso.")
        return

    if query.data == "delete_account_confirm":
        # Audit log PRIMA della cancellazione (Art. 17 GDPR, accountability Art. 30)
        _user_store.write_audit_log(
            chat_id, actor="user", action="delete_account",
            user_agent="telegram-bot",
        )
        backend = _user_store.delete_user_completely(chat_id)
        logger.info("account_deleted", extra={"domain": "privacy", "event": "account_deleted", "chat_id": chat_id, "meta": {"storage_backend": backend}})
        farewell_name = (update.effective_user.first_name or "").strip()
        farewell = f"Ciao {farewell_name}! 👋" if farewell_name else "Ciao! 👋"
        await query.edit_message_text(
            f"✅ Account eliminato. Tutti i tuoi dati sono stati cancellati.\n\n{farewell}"
        )
        return

    if query.data == "switch_to_notion":
        # Elimina tutti i dati dell'account (passaggio da DB interno a Notion, resta
        # su Telegram: Notion si registra direttamente via OAuth da qui).
        _user_store.delete_user_completely(chat_id)
        logger.info("account_deleted_for_storage_switch", extra={"domain": "privacy", "event": "account_deleted_for_storage_switch", "chat_id": chat_id, "meta": {}})

        reg_token = _user_store.create_oauth_session(chat_id)
        base_url = Config.WEBAPP_BASE_URL
        notion_url = f"{base_url}/auth/notion?reg_token={reg_token}"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Connetti a Notion", url=notion_url)],
        ])

        await query.edit_message_text(
            "✅ *Dati precedenti eliminati con successo!*\n\n"
            "Ora puoi procedere alla registrazione con Notion:\n\n"
            "⚠️ Dati conservati su infrastruttura USA 🇺🇸 (salvo data residency UE su piani "
            "Enterprise Notion).",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
        return

    if query.data == "delete_account_cancel":
        await query.edit_message_text("❌ Eliminazione annullata. Il tuo account è al sicuro.")
        return

    # ------------------------------------------------------------------
    # Check-in beta (vedi _beta_feature_validation_job): step 1 reazione a una
    # feature, poi step 2 facoltativo di feedback libero (mai un wall).
    # ------------------------------------------------------------------

    if query.data.startswith("betaval:"):
        _, feature_code, reaction = query.data.split(":", 2)
        feature_label = next(
            (label for code, label in BETA_VALIDATION_FEATURES if code == feature_code), feature_code
        )
        reaction_label = BETA_VALIDATION_REACTIONS.get(reaction, reaction)
        _user_store.save_feedback(
            chat_id,
            message=f"[Beta validation] {feature_label}: {reaction_label}",
            category="beta_validation",
            rating=reaction,
        )
        context.user_data["waiting_for_beta_feedback"] = True
        await query.edit_message_text(
            f"{reaction_label}, grazie: la tua opinione conta! 🙏\n\n"
            "Vuoi lasciarci anche due righe di feedback libero? Scrivi pure qui sotto e premi invio 👇",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Salta", callback_data="betaval_skip_feedback"),
            ]]),
        )
        return

    if query.data == "betaval_skip_feedback":
        context.user_data.pop("waiting_for_beta_feedback", None)
        await query.edit_message_text("Va bene, grazie lo stesso per il check-in! 🙏")
        return

    # ------------------------------------------------------------------
    # Transazioni multiple presentate in parallelo (vedi _process_expense_text):
    # ognuna vive in context.user_data["pending_expenses"][tx_id], indipendente
    # dalle altre — annullarne/confermarne una non tocca le altre in sospeso.
    # ------------------------------------------------------------------

    if query.data.startswith("mcancel:"):
        tx_id = query.data.split(":", 1)[1]
        pending_expenses = context.user_data.get("pending_expenses", {})
        cancelled_data = pending_expenses.pop(tx_id, None)
        if cancelled_data is None:
            await query.edit_message_text("⚠️ Nessuna spesa in sospeso.")
            return
        _track_event(chat_id, "expense_tracking_failed", {
            "reason": "user_cancelled", "input_method": "text",
            "transaction_type": cancelled_data.get("type", "expense"),
        })
        _user_store.record_tx_event(
            chat_id, cancelled_data.get("type", "expense"), "text", "cancelled", "telegram",
            reason="user_cancelled",
        )
        await query.edit_message_text("❌ Operazione annullata.")
        return

    if query.data.startswith("medit_category:") or query.data.startswith("medit_category_back:"):
        is_back = query.data.startswith("medit_category_back:")
        tx_id = query.data.split(":", 1)[1]
        pending = context.user_data.get("pending_expenses", {}).get(tx_id)
        if not pending:
            await query.edit_message_text("⚠️ Nessuna spesa in sospeso.")
            return

        if is_back:
            summary = _build_expense_summary(pending)
            keyboard = _build_confirm_keyboard(pending, tx_id)
            await query.edit_message_text(summary, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
            return

        try:
            storage = _get_storage(chat_id)
            category_options = _category_picker_options(storage, pending)
        except Exception as exc:  # noqa: BLE001 -- il picker mostra un messaggio sicuro
            log_exception(logger, level="error", domain="transactions", event="categories_fetch_failed", exception=exc, chat_id=str(chat_id))
            await query.edit_message_text("⚠️ Errore nel recupero delle categorie. Riprova tra qualche istante.")
            return

        if not category_options:
            await query.edit_message_text("⚠️ Non hai ancora nessuna categoria configurata. Usa /modify per crearne una.")
            return

        options_by_tx = context.user_data.setdefault("category_options_by_tx", {})
        options_by_tx[tx_id] = category_options
        keyboard = [
            [InlineKeyboardButton(option["name"], callback_data=f"msetcat:{tx_id}:{idx}")]
            for idx, option in enumerate(category_options)
        ]
        keyboard.append([InlineKeyboardButton("🔙 Indietro", callback_data=f"medit_category_back:{tx_id}")])
        await query.edit_message_text(
            "📂 Scegli la categoria giusta:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if query.data.startswith("msetcat:"):
        _, tx_id, idx_str = query.data.split(":", 2)
        pending = context.user_data.get("pending_expenses", {}).get(tx_id)
        category_options = context.user_data.get("category_options_by_tx", {}).get(tx_id)
        if not pending or not category_options:
            await query.edit_message_text("⚠️ Nessuna spesa in sospeso.")
            return
        try:
            selected_option = category_options[int(idx_str)]
        except (ValueError, IndexError):
            await query.edit_message_text("⚠️ Categoria non valida. Riprova.")
            return

        if pending.get("type") == "income":
            pending["income_category_id"] = selected_option["id"]
            pending["income_category"] = selected_option["name"]
            pending["income_type"] = selected_option["name"]
        else:
            pending["category"] = selected_option["name"]
        pending["category_was_corrected"] = True
        summary = _build_expense_summary(pending)
        keyboard = _build_confirm_keyboard(pending, tx_id)
        await query.edit_message_text(summary, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
        return

    if query.data.startswith("mconfirm:"):
        tx_id = query.data.split(":", 1)[1]
        data = context.user_data.get("pending_expenses", {}).get(tx_id)
        if not data:
            await query.edit_message_text("⚠️ Nessuna spesa in sospeso.")
            return

        try:
            storage = _get_storage(chat_id)
            accounts = storage.fetch_accounts()
        except Exception as exc:  # noqa: BLE001 -- il picker mostra un messaggio sicuro
            log_exception(logger, level="error", domain="transactions", event="accounts_fetch_failed", exception=exc, chat_id=str(chat_id))
            await query.edit_message_text("⚠️ Errore nel recupero dei tuoi conti. Riprova tra qualche istante.")
            return

        if not accounts:
            # Nessun conto configurato: blocca solo questa transazione (le altre in parallelo
            # restano in sospeso, l'utente potrà confermarle appena avrà creato un conto).
            context.user_data.get("pending_expenses", {}).pop(tx_id, None)
            _track_event(chat_id, "expense_tracking_failed", {
                "reason": "no_account", "input_method": "text",
                "transaction_type": data.get("type", "expense"),
            })
            _user_store.record_tx_event(
                chat_id, data.get("type", "expense"), "text", "failed", "telegram", reason="no_account",
            )
            await query.edit_message_text(
                "🏦 Non hai ancora nessun conto su Expensum, quindi non posso registrare la spesa.\n\n"
                "Usa /modify e vai nella tab \"Conti\" per aggiungerne uno, poi rimanda il messaggio della spesa."
            )
            return

        keyboard = []
        for acc in accounts:
            bal = acc.get('current_balance', 0.0)
            keyboard.append([InlineKeyboardButton(f"🏦 {acc['name']} (€{bal:.2f})", callback_data=f"maccount:{tx_id}:{acc['id']}")])
        keyboard.append([InlineKeyboardButton("❌ Annulla", callback_data=f"mcancel:{tx_id}")])

        question = "🏦 Su quale conto è arrivata l'entrata?" if data.get("type") == "income" else "🏦 Da quale conto hai pagato?"
        await query.edit_message_text(question, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if query.data.startswith("maccount:"):
        _, tx_id, account_id = query.data.split(":", 2)
        data = context.user_data.get("pending_expenses", {}).pop(tx_id, None)
        if not data:
            await query.edit_message_text("⚠️ Nessuna spesa in sospeso.")
            return
        await _save_to_notion(query, context, chat_id, data, account_id=account_id)
        return

    if query.data == "edit_category":
        pending = context.user_data.get("pending_expense")
        if not pending:
            await query.edit_message_text("⚠️ Nessuna spesa in sospeso.")
            return
        try:
            storage = _get_storage(chat_id)
            category_options = _category_picker_options(storage, pending)
        except Exception as exc:  # noqa: BLE001 -- il picker mostra un messaggio sicuro
            log_exception(logger, level="error", domain="transactions", event="categories_fetch_failed", exception=exc, chat_id=str(chat_id))
            await query.edit_message_text("⚠️ Errore nel recupero delle categorie. Riprova tra qualche istante.")
            return

        if not category_options:
            await query.edit_message_text("⚠️ Non hai ancora nessuna categoria configurata. Usa /modify per crearne una.")
            return

        # Le categorie vanno in user_data (non nel callback_data) per non rischiare
        # di superare il limite di 64 byte di Telegram con nomi lunghi o emoji.
        context.user_data.setdefault("category_options_by_tx", {})["single"] = category_options
        keyboard = [
            [InlineKeyboardButton(option["name"], callback_data=f"setcat:{idx}")]
            for idx, option in enumerate(category_options)
        ]
        keyboard.append([InlineKeyboardButton("🔙 Indietro", callback_data="edit_category_back")])
        await query.edit_message_text(
            "📂 Scegli la categoria giusta:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if query.data == "edit_category_back":
        pending = context.user_data.get("pending_expense")
        if not pending:
            await query.edit_message_text("⚠️ Nessuna spesa in sospeso.")
            return
        summary = _build_expense_summary(pending)
        keyboard = _build_confirm_keyboard(pending)
        await query.edit_message_text(summary, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
        return

    if query.data.startswith("setcat:"):
        pending = context.user_data.get("pending_expense")
        category_options = context.user_data.get("category_options_by_tx", {}).get("single")
        if not pending or not category_options:
            await query.edit_message_text("⚠️ Nessuna spesa in sospeso.")
            return
        try:
            idx = int(query.data.split(":", 1)[1])
            selected_option = category_options[idx]
        except (ValueError, IndexError):
            await query.edit_message_text("⚠️ Categoria non valida. Riprova.")
            return

        if pending.get("type") == "income":
            pending["income_category_id"] = selected_option["id"]
            pending["income_category"] = selected_option["name"]
            pending["income_type"] = selected_option["name"]
        else:
            pending["category"] = selected_option["name"]
        pending["category_was_corrected"] = True
        summary = _build_expense_summary(pending)
        keyboard = _build_confirm_keyboard(pending)
        await query.edit_message_text(summary, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
        return

    if query.data == "cancel":
        input_method = context.user_data.pop("input_method", "text")
        cancelled_data = context.user_data.pop("pending_expense", None)
        context.user_data.pop("waiting_for_amount", None)
        _track_event(chat_id, "expense_tracking_failed", {
            "reason": "user_cancelled", "input_method": input_method,
            "transaction_type": (cancelled_data or {}).get("type", "expense"),
        })
        _user_store.record_tx_event(
            chat_id, (cancelled_data or {}).get("type", "expense"), input_method, "cancelled", "telegram",
            reason="user_cancelled",
        )
        await query.edit_message_text("❌ Operazione annullata.")
        # Messaggio multi-spesa: annullare una transazione non annulla le altre in coda
        try:
            await _present_next_pending_expense(context, chat_id)
        except Exception as exc:  # noqa: BLE001 -- la coda resta riprendibile
            log_exception(logger, level="warning", domain="transactions", event="next_pending_present_failed", exception=exc, chat_id=str(chat_id))
        return

    if query.data == "confirm":
        data = context.user_data.get("pending_expense")
        if not data:
            await query.edit_message_text("⚠️ Nessuna spesa in sospeso.")
            return

        if data.get("type") == "transfer":
            # I conti origine/destinazione sono già stati risolti prima della conferma
            # (picker a bottoni o match NLP): niente step "quale conto" da fare qui.
            await _save_transfer(query, context, chat_id)
            return

        # Recupera accounts da Notion per far selezionare il conto
        try:
            storage = _get_storage(chat_id)
            accounts = storage.fetch_accounts()
        except Exception as exc:  # noqa: BLE001 -- il picker mostra un messaggio sicuro
            log_exception(logger, level="error", domain="transactions", event="accounts_fetch_failed", exception=exc, chat_id=str(chat_id))
            await query.edit_message_text(
                "⚠️ Errore nel recupero dei tuoi conti. Riprova tra qualche istante."
            )
            return

        if not accounts:
            # Nessun conto configurato: non si può salvare senza sapere su quale conto
            # accreditare/scalare la transazione. Blocca e indirizza l'utente a crearne uno.
            # Svuota anche l'eventuale coda multi-spesa: nessuna delle transazioni rilevate
            # sarebbe comunque salvabile finché non esiste un conto.
            input_method = context.user_data.pop("input_method", "text")
            tx_type_for_failure = data.get("type", "expense")
            context.user_data.pop("pending_expense", None)
            context.user_data.pop("waiting_for_amount", None)
            context.user_data.pop("expense_queue", None)
            _track_event(chat_id, "expense_tracking_failed", {
                "reason": "no_account", "input_method": input_method,
                "transaction_type": tx_type_for_failure,
            })
            _user_store.record_tx_event(
                chat_id, tx_type_for_failure, input_method, "failed", "telegram", reason="no_account",
            )
            await query.edit_message_text(
                "🏦 Non hai ancora nessun conto su Expensum, quindi non posso registrare la spesa.\n\n"
                "Usa /modify e vai nella tab \"Conti\" per aggiungerne uno, poi rimanda il messaggio della spesa."
            )
            return

        # Disegna bottoni
        keyboard = []
        for acc in accounts:
            bal = acc.get('current_balance', 0.0)
            keyboard.append([InlineKeyboardButton(f"🏦 {acc['name']} (€{bal:.2f})", callback_data=f"account:{acc['id']}")])
        keyboard.append([InlineKeyboardButton("❌ Annulla", callback_data="cancel")])
        
        pending = context.user_data.get("pending_expense", {})
        question = "🏦 Su quale conto è arrivata l'entrata?" if pending.get("type") == "income" else "🏦 Da quale conto hai pagato?"
        await query.edit_message_text(question, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if query.data.startswith("account:"):
        account_id = query.data.split(":", 1)[1]
        data = context.user_data.pop("pending_expense", None)
        await _save_to_notion(query, context, chat_id, data, account_id=account_id)
        return

    if query.data.startswith("transfer_from:") or query.data.startswith("transfer_to:"):
        side, account_id = query.data.split(":", 1)
        pending = context.user_data.get("pending_expense")
        if not pending or pending.get("type") != "transfer":
            await query.edit_message_text("⚠️ Nessun trasferimento in sospeso.")
            return

        if side == "transfer_to" and account_id == str(pending.get("from_account_id")):
            await query.edit_message_text(
                "⚠️ Il conto di destinazione deve essere diverso da quello di origine."
            )
            return

        try:
            storage = _get_storage(chat_id)
            accounts = storage.fetch_accounts()
        except Exception as exc:  # noqa: BLE001 -- il picker mostra un messaggio sicuro
            log_exception(logger, level="error", domain="transactions", event="accounts_fetch_failed", exception=exc, chat_id=str(chat_id))
            await query.edit_message_text("⚠️ Errore nel recupero dei tuoi conti. Riprova tra qualche istante.")
            return

        acc = next((a for a in accounts if str(a["id"]) == account_id), None)
        if side == "transfer_from":
            pending["from_account_id"] = account_id
            pending["from_account_name"] = acc["name"] if acc else None
        else:
            pending["to_account_id"] = account_id
            pending["to_account_name"] = acc["name"] if acc else None

        async def _send(text, reply_markup=None):
            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        await _advance_transfer_flow(context, chat_id, _send)
        return

    if query.data.startswith("catpromote_yes:") or query.data.startswith("catpromote_no:"):
        decision_yes = query.data.startswith("catpromote_yes:")
        candidate_id = int(query.data.split(":", 1)[1])

        if decision_yes:
            storage = _get_storage(chat_id)
            with _user_store.Session() as cm_session:
                match_result = category_matcher.confirm_promotion(cm_session, storage, _user_store, candidate_id)
            if match_result.promoted:
                await query.edit_message_text(
                    f"✅ Categoria «{match_result.promoted_category_name}» creata! Le prossime spese simili "
                    "verranno categorizzate automaticamente."
                )
            else:
                await query.edit_message_text(
                    "⚠️ Non sono riuscito a creare la categoria in questo momento (problema temporaneo col "
                    "tuo storage). Riproverò automaticamente alla prossima spesa simile."
                )
        else:
            with _user_store.Session() as cm_session:
                category_matcher.decline_promotion(cm_session, candidate_id)
            await query.edit_message_text("👍 Nessun problema, non creo la categoria.")
        return

    if query.data.startswith("subpromote_yes:") or query.data.startswith("subpromote_no:"):
        decision_yes = query.data.startswith("subpromote_yes:")
        candidate_id = int(query.data.split(":", 1)[1])

        if decision_yes:
            storage = _get_storage(chat_id)
            try:
                with _user_store.Session() as sub_session:
                    candidate = subscription_detector.confirm_candidate(sub_session, storage, candidate_id)
                if candidate is None:
                    await query.edit_message_text("⚠️ Candidato non trovato (forse già gestito altrove).")
                else:
                    _track_event(chat_id, "subscription_candidate_confirmed", {"cadence": candidate.cadence})
                    await query.edit_message_text(
                        f"✅ Abbonamento «{candidate.display_name}» aggiunto! Lo trovi tra i tuoi "
                        "abbonamenti tracciati."
                    )
            except Exception as e:
                logger.error("[User %s] Conferma abbonamento fallita: %s", chat_id, e)
                await query.edit_message_text(
                    "⚠️ Non sono riuscito ad aggiungere l'abbonamento in questo momento (problema "
                    "temporaneo col tuo storage). Riprova con /scova_abbonamenti."
                )
        else:
            with _user_store.Session() as sub_session:
                subscription_detector.dismiss_candidate(sub_session, candidate_id)
            _track_event(chat_id, "subscription_candidate_dismissed", {})
            await query.edit_message_text("👍 Nessun problema, non lo aggiungo.")
        return


# ---------------------------------------------------------------------------
# Error handler globale
# ---------------------------------------------------------------------------

async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler globale per le eccezioni non gestite nel bot.

    Logga l'errore con contesto (update_id, chat_id) senza dati sensibili
    e notifica l'utente con un messaggio generico.
    """
    log_level = logging.WARNING if isinstance(context.error, NetworkError) else logging.ERROR
    logger.log(
        log_level,
        "Eccezione durante la gestione di un update",
        exc_info=context.error,
        extra={
            "update_id": update.update_id if hasattr(update, "update_id") else "N/A",
        },
    )

    # Notifica l'utente solo se l'update ha un messaggio o una callback
    if isinstance(update, Update):
        chat_id = update.effective_chat.id if update.effective_chat else None
        if chat_id:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Si è verificato un errore inaspettato. Riprova tra qualche istante.",
                )
            except Exception:
                pass  # Ignora errori nell'invio del messaggio di errore


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _notify_category_reassignments(
    app: Application,
    loop: asyncio.AbstractEventLoop,
    notifications: list,
) -> None:
    """Notifica agli utenti le categorie rimosse da Notion con record spostati su «Altro».

    `notifications` è una lista di (chat_id, ReconcileReport). Best-effort: un errore
    su un singolo invio non blocca gli altri.
    """
    async def _send():
        bot = app.bot
        for chat_id, report in notifications:
            try:
                lines = ["ℹ️ Ho allineato le categorie al tuo Notion."]
                for r in report.reassignments:
                    parti = []
                    if r.moved_expenses:
                        parti.append(f"{r.moved_expenses} spese")
                    if r.moved_subscriptions:
                        parti.append(f"{r.moved_subscriptions} abbonamenti")
                    dettaglio = " e ".join(parti) if parti else "i record collegati"
                    lines.append(
                        f"• «{r.category_name}» è stata rimossa: {dettaglio} "
                        f"spostati su «Altro»."
                    )
                await bot.send_message(chat_id=int(chat_id), text="\n".join(lines))
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.error("[NightlySync] Notifica riassegnazioni fallita per %s: %s", chat_id, e)

    future = asyncio.run_coroutine_threadsafe(_send(), loop)
    try:
        future.result(timeout=120)
    except Exception as e:
        logger.error("[NightlySync] Errore invio notifiche riassegnazioni: %s", e)


def _nightly_category_sync(app: Application, loop: asyncio.AbstractEventLoop) -> None:
    """Job APScheduler alle 03:00 — aggiorna medie categorie per tutti gli utenti attivi.

    Sequenziale con 200ms di sleep tra utenti per non saturare CPU/rete su Hetzner CX23.
    Ogni utente Notion usa il proprio OAuth token → bucket rate limit separato.

    Per gli utenti Notion la sync è anche riconciliante: rimuove dalla cache le
    categorie non più presenti su Notion. Se categorie con spese/abbonamenti
    dipendenti vengono rimosse, i record sono spostati su «Altro» e l'utente viene
    notificato.
    """
    logger.info("[NightlySync] Avvio sincronizzazione notturna categorie.")

    # (chat_id, ReconcileReport) da notificare a fine giro Notion.
    pending_notifications: list = []

    # --- Utenti Notion ---
    try:
        notion_users = _user_store.get_active_notion_users()
        logger.info("[NightlySync] Utenti Notion: %d", len(notion_users))
        for user in notion_users:
            try:
                notion_client = NotionFinanceClient(
                    api_key=user.notion_access_token,
                    categories_db_id=user.categories_db_id,
                    income_db_id=user.income_db_id,
                )
                NotionStorage(
                    notion_client, store=_user_store, user_id=user.chat_id,
                ).retry_pending_income_category_syncs()
                report = refresh_category_averages(
                    user.chat_id, _user_store, notion_client=notion_client
                )
                if report is not None and report.has_reassignments:
                    pending_notifications.append((user.chat_id, report))
            except Exception as e:
                logger.error("[NightlySync] Errore Notion per %s: %s", user.chat_id, e)
            time.sleep(0.2)
    except Exception as e:
        logger.error("[NightlySync] Errore fetch utenti Notion: %s", e)

    if pending_notifications:
        _notify_category_reassignments(app, loop, pending_notifications)

    # --- Utenti Postgres ---
    try:
        pg_users = _user_store.get_active_postgres_users()
        logger.info("[NightlySync] Utenti Postgres: %d", len(pg_users))
        for user in pg_users:
            session = None
            try:
                session = _user_store.Session()
                refresh_category_averages(user.chat_id, _user_store, session=session)
            except Exception as e:
                logger.error("[NightlySync] Errore Postgres per %s: %s", user.chat_id, e)
            finally:
                if session:
                    session.close()
            time.sleep(0.2)
    except Exception as e:
        logger.error("[NightlySync] Errore fetch utenti Postgres: %s", e)

    logger.info("[NightlySync] Sincronizzazione notturna completata.")


def _weekly_plan_job(app: Application, loop: asyncio.AbstractEventLoop) -> None:
    """Job APScheduler ogni lunedì alle 08:00 — invia il piano settimanale a tutti gli utenti attivi."""
    logger.info("[WeeklyPlan] Avvio invio piani settimanali.")

    async def _send_plans():
        bot = app.bot
        # Esclude chi ha disattivato le notifiche (Art. 21 GDPR)
        notion_users = _user_store.get_active_notion_users()
        pg_users = _user_store.get_active_postgres_users()
        all_users = [u for u in list(notion_users) + list(pg_users) if u.notifications_enabled]

        sent = 0
        for user in all_users:
            chat_id = user.chat_id
            try:
                await _build_and_send_weekly_plan(chat_id=chat_id, bot=bot)
                _track_event(chat_id, "notification_sent", {"notification_type": "weekly_plan"})
                sent += 1
                logger.info("weekly_plan_sent", extra={"domain": "jobs", "event": "weekly_plan_sent", "chat_id": str(chat_id), "meta": {}})
            except Exception as exc:
                log_exception(logger, level="error", domain="jobs", event="weekly_plan_user_failed", exception=exc, chat_id=str(chat_id))
            await asyncio.sleep(0.5)

        logger.info("weekly_plan_completed", extra={"domain": "jobs", "event": "weekly_plan_completed", "meta": {"sent": sent, "eligible": len(all_users)}})

    future = asyncio.run_coroutine_threadsafe(_send_plans(), loop)
    try:
        future.result(timeout=300)
    except Exception as exc:
        log_exception(logger, level="error", domain="jobs", event="weekly_plan_job_failed", exception=exc)
        raise


# Rotazione feature del check-in beta: una a settimana (indicizzata su isocalendar
# week), non tutte insieme — evita di affaticare i beta tester con più domande.
BETA_VALIDATION_FEATURES: list[tuple[str, str]] = [
    ("budget_categories_webapp", "📊 Il budget suggerito per categoria nella web app"),
    ("savings_goals", "🎯 Gli obiettivi di risparmio"),
    ("subscription_detection", "🔁 Il rilevamento automatico degli abbonamenti"),
    ("weekly_report", "📈 Il report settimanale delle spese"),
    ("monthly_report", "🗓️ Il report mensile delle spese"),
    ("daily_summary", "🌅 Il messaggio riassuntivo giornaliero"),
    ("analytics_webapp", "🧭 La scheda analytics nella web app"),
    ("text_parsing", "✍️ Il riconoscimento delle spese scritte a testo"),
    ("voice_parsing", "🎙️ Il riconoscimento delle spese a voce"),
    ("photo_parsing", "📸 Il riconoscimento delle spese da foto scontrino"),
    ("spending_calendar_webapp", "📅 Il calendario di spesa nella web app"),
]

BETA_VALIDATION_REACTIONS: dict[str, str] = {
    "up": "👍 Mi piace",
    "down": "👎 Non mi piace",
    "skip": "🤷 Non l'ho usata",
}


def _beta_feature_validation_job(app: Application, loop: asyncio.AbstractEventLoop) -> None:
    """Job APScheduler ogni martedì — check-in ai beta tester per validare una feature
    a rotazione (👍/👎/non usata) e raccogliere un feedback libero. Mai un wall: chi
    ignora il messaggio non perde nulla, è solo un check-in facoltativo."""
    logger.info("[BetaValidation] Avvio check-in beta.")
    feature_code, feature_label = BETA_VALIDATION_FEATURES[
        date.today().isocalendar()[1] % len(BETA_VALIDATION_FEATURES)
    ]

    async def _send_checkins():
        bot = app.bot
        chat_ids = _user_store.get_beta_default_users()

        sent = 0
        for chat_id in chat_ids:
            if _user_store.has_recent_beta_validation_feedback(chat_id):
                continue
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(BETA_VALIDATION_REACTIONS["up"], callback_data=f"betaval:{feature_code}:up"),
                InlineKeyboardButton(BETA_VALIDATION_REACTIONS["down"], callback_data=f"betaval:{feature_code}:down"),
                InlineKeyboardButton(BETA_VALIDATION_REACTIONS["skip"], callback_data=f"betaval:{feature_code}:skip"),
            ]])
            try:
                await bot.send_message(
                    chat_id=int(chat_id),
                    text=(
                        "🧪 *Check-in beta*\n\n"
                        "Ci stai aiutando a validare Expensum: questa settimana vorremmo un tuo parere su\n"
                        f"{feature_label}.\n\n"
                        "Che ne pensi?"
                    ),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard,
                )
                _track_event(chat_id, "notification_sent", {"notification_type": "beta_validation"})
                sent += 1
                logger.info("beta_validation_sent", extra={"domain": "jobs", "event": "beta_validation_sent", "chat_id": str(chat_id), "meta": {}})
            except Exception as exc:
                log_exception(logger, level="error", domain="jobs", event="beta_validation_user_failed", exception=exc, chat_id=str(chat_id))
            await asyncio.sleep(0.5)

        logger.info("beta_validation_completed", extra={"domain": "jobs", "event": "beta_validation_completed", "meta": {"sent": sent, "eligible": len(chat_ids)}})

    future = asyncio.run_coroutine_threadsafe(_send_checkins(), loop)
    try:
        future.result(timeout=300)
    except Exception as exc:
        log_exception(logger, level="error", domain="jobs", event="beta_validation_job_failed", exception=exc)
        raise


def _monthly_plan_job(app: Application, loop: asyncio.AbstractEventLoop) -> None:
    """Job APScheduler il 1° di ogni mese alle 08:00 — invia a tutti gli utenti attivi
    l'analisi retrospettiva del mese appena concluso (stessa pipeline di /monthly_report)."""
    logger.info("[MonthlyReport] Avvio invio report mensili.")

    async def _send_reports():
        import main as main_module
        target_year, target_month = main_module._resolve_default_target_month(date.today())

        # Esclude chi ha disattivato le notifiche (Art. 21 GDPR)
        notion_users = _user_store.get_active_notion_users()
        pg_users = _user_store.get_active_postgres_users()
        all_users = [u for u in list(notion_users) + list(pg_users) if u.notifications_enabled]

        sent = 0
        for user in all_users:
            chat_id = user.chat_id
            plan = _user_store.get_user_plan(chat_id)
            if plan["tokens_remaining"] < 5000:
                logger.info("monthly_report_skipped_quota", extra={"domain": "jobs", "event": "monthly_report_skipped_quota", "chat_id": str(chat_id), "meta": {}})
                continue
            try:
                await asyncio.wait_for(
                    main_module.run_agent(
                        target_year, target_month, dry_run=False, chat_id=chat_id, shared_store=_user_store,
                    ),
                    timeout=300,
                )
                _track_event(chat_id, "notification_sent", {"notification_type": "monthly_report"})
                sent += 1
                logger.info("monthly_report_sent", extra={"domain": "jobs", "event": "monthly_report_sent", "chat_id": str(chat_id), "meta": {}})
            except asyncio.TimeoutError:
                logger.error("monthly_report_timeout", extra={"domain": "jobs", "event": "monthly_report_timeout", "chat_id": str(chat_id), "meta": {}})
            except Exception as exc:
                log_exception(logger, level="error", domain="jobs", event="monthly_report_user_failed", exception=exc, chat_id=str(chat_id))
            await asyncio.sleep(0.5)

        logger.info("monthly_report_completed", extra={"domain": "jobs", "event": "monthly_report_completed", "meta": {"sent": sent, "eligible": len(all_users)}})

    future = asyncio.run_coroutine_threadsafe(_send_reports(), loop)
    try:
        future.result(timeout=1800)
    except Exception as exc:
        log_exception(logger, level="error", domain="jobs", event="monthly_report_job_failed", exception=exc)
        raise


def _savings_goals_monthly_job(app: Application, loop: asyncio.AbstractEventLoop) -> None:
    """Job APScheduler il 1° di ogni mese alle 07:30 (prima del report delle 8:00) —
    calcola voto mensile + ETA per ogni obiettivo attivo degli utenti Pro/postgres,
    salva `savings_goal_evaluations`, aggiorna `current_snapshot`/`status` e notifica
    via Telegram i goal appena completati (testo semplice, mai un badge/reward).
    """
    from src.savings_goals_service import compute_goal_progress, compute_monthly_score, explain_score
    from src.storage.postgres_storage import PostgresStorage

    logger.info("[SavingsGoals] Avvio valutazione mensile obiettivi.")
    today = date.today()
    period_month = date(today.year, today.month, 1)

    completed_notifications: list[tuple[str, dict, dict]] = []  # (chat_id, goal, score)
    evaluated = 0

    pro_pg_users = [u for u in _user_store.get_pro_users() if u.storage_backend == "postgres"]
    for user in pro_pg_users:
        chat_id = user.chat_id
        try:
            storage = _get_storage(chat_id)
            if not isinstance(storage, PostgresStorage):
                continue
            goals = storage.fetch_savings_goals(status="active")
            for goal in goals:
                progress = compute_goal_progress(storage, goal)
                score = compute_monthly_score(storage, goal, progress)
                storage.save_savings_goal_evaluation(
                    goal_id=goal["id"],
                    period_month=period_month,
                    progress_pct=progress["progress_pct"],
                    score_label=score["score_label"],
                    eta_date=progress["eta_date"],
                )
                update_fields = {
                    "current_snapshot": progress["current"],
                    "last_evaluated_at": datetime.utcnow(),
                }
                if progress["evaluable"] and progress["progress_pct"] >= 100 and goal["goal_type"] != "savings_rate":
                    update_fields["status"] = "completed"
                    update_fields["completed_at"] = datetime.utcnow()
                    completed_notifications.append((chat_id, goal, score))
                    # Rete di sicurezza: il rilevamento in tempo reale copre già la
                    # maggior parte dei casi, ma non `category_spending_reduction`,
                    # che si può dire riuscito solo a mese finito. `record_event` è
                    # idempotente sul dedup_key, quindi un doppio passaggio non
                    # assegna due volte l'achievement.
                    mark_goal_reached(chat_id, goal)
                storage.update_savings_goal(goal["id"], **update_fields)
                evaluated += 1
        except Exception as exc:
            log_exception(logger, level="error", domain="jobs", event="savings_goal_evaluation_failed", exception=exc, chat_id=str(chat_id))

    logger.info("savings_goals_evaluated", extra={"domain": "jobs", "event": "savings_goals_evaluated", "meta": {"evaluated": evaluated, "eligible": len(pro_pg_users)}})

    if not completed_notifications:
        return

    async def _notify_completed():
        bot = app.bot
        sent = 0
        for chat_id, goal, score in completed_notifications:
            user = _user_store.get_user(chat_id)
            if not user or not user.notifications_enabled:
                continue
            try:
                text = (
                    f"🎉 Obiettivo raggiunto: *{goal['name']}*!\n"
                    f"{explain_score(goal, score, markdown=True)}"
                )
                await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN)
                _track_event(chat_id, "notification_sent", {"notification_type": "savings_goal_completed"})
                sent += 1
            except Exception as exc:
                log_exception(logger, level="error", domain="jobs", event="savings_goal_notification_failed", exception=exc, chat_id=str(chat_id))
            await asyncio.sleep(0.5)
        return sent

    future = asyncio.run_coroutine_threadsafe(_notify_completed(), loop)
    try:
        sent = future.result(timeout=300)
        logger.info("savings_goal_notifications_completed", extra={"domain": "jobs", "event": "savings_goal_notifications_completed", "meta": {"sent": sent, "eligible": len(completed_notifications)}})
    except Exception as exc:
        log_exception(logger, level="error", domain="jobs", event="savings_goal_notifications_job_failed", exception=exc)


def _loan_monthly_charge_job(app: Application, loop: asyncio.AbstractEventLoop) -> None:
    """Job APScheduler il 1° di ogni mese alle 07:00 (prima degli obiettivi, 07:30) —
    registra per ogni loan attivo degli utenti Pro/postgres la spesa "Interessi"
    (+ "Costi mutuo/finanziamento" se c'è una spesa incasso rata) del mese appena
    iniziato. Idempotente su `loan_monthly_charges` (vedi PostgresStorage): un rerun
    dopo un crash non duplica gli addebiti.
    """
    logger.info("[LoanCharges] Avvio addebito mensile mutui/finanziamenti.")
    today = date.today()
    period_month = date(today.year, today.month, 1)

    charged = 0
    pro_pg_users = [u for u in _user_store.get_pro_users() if u.storage_backend == "postgres"]
    for user in pro_pg_users:
        chat_id = user.chat_id
        try:
            storage = _get_storage(chat_id)
            if not isinstance(storage, PostgresStorage):
                continue
            for loan in storage.fetch_loans(status="active"):
                result = storage.record_loan_monthly_charge(loan["id"], period_month)
                if result:
                    charged += 1
        except Exception as exc:
            log_exception(logger, level="error", domain="jobs", event="loan_charge_failed", exception=exc, chat_id=str(chat_id))

    logger.info("loan_charges_completed", extra={"domain": "jobs", "event": "loan_charges_completed", "meta": {"charged": charged, "eligible": len(pro_pg_users)}})


def _mortgage_rate_review_job(app: Application, loop: asyncio.AbstractEventLoop) -> None:
    """Job APScheduler giornaliero — email di notifica per i loan variabili con
    `next_review_date` di oggi. Unica eccezione ai "niente promemoria proattivi":
    l'Euribor si aggiorna manualmente (nessuna licenza dati EMMI in v1), quindi
    l'utente va avvisato quando è il momento di controllare/aggiornare il tasso.
    """
    logger.info("[MortgageRateReview] Avvio controllo revisioni tasso variabile.")
    today = date.today()

    sent = 0
    pro_pg_users = [u for u in _user_store.get_pro_users() if u.storage_backend == "postgres"]
    for user in pro_pg_users:
        chat_id = user.chat_id
        if not user.email:
            continue
        try:
            storage = _get_storage(chat_id)
            if not isinstance(storage, PostgresStorage):
                continue
            due_loans = [
                loan for loan in storage.fetch_loans(status="active")
                if loan["rate_type"] == "variabile" and loan["next_review_date"] == today.isoformat()
            ]
            for loan in due_loans:
                name = display_name(_user_store, chat_id)
                subject = f"Il tasso del tuo mutuo/finanziamento \"{loan['name']}\" è da verificare"
                mutuo_url = f"{Config.WEBAPP_BASE_URL}/login?next=/mutuo"
                html = (
                    f"<p>Ciao{f' {name}' if name != '👋' else ''},</p>"
                    f"<p>Oggi è la data di revisione del tasso variabile per "
                    f"<strong>{loan['name']}</strong>. Controlla il nuovo Euribor comunicato "
                    f"dalla tua banca e aggiornalo in Expensum per tenere allineata la rata.</p>"
                    f'<p style="margin-top:24px"><a href="{mutuo_url}" '
                    'style="display:inline-block;padding:12px 24px;background:#5f55ee;color:#ffffff;'
                    'text-decoration:none;border-radius:8px;font-weight:600">Aggiorna il tasso</a></p>'
                )
                brevo_client.send_transactional_email(user.email, subject, html)
                _track_event(chat_id, "notification_sent", {"notification_type": "mortgage_rate_review"})
                sent += 1
        except Exception as exc:
            log_exception(logger, level="error", domain="jobs", event="mortgage_rate_review_failed", exception=exc, chat_id=str(chat_id))

    logger.info("mortgage_rate_reviews_completed", extra={"domain": "jobs", "event": "mortgage_rate_reviews_completed", "meta": {"sent": sent, "eligible": len(pro_pg_users)}})


def _trial_expiry_job(app: Application, loop: asyncio.AbstractEventLoop) -> None:
    """Job APScheduler alle 04:00 — downgrade automatico a Free per trial scaduti.

    Spento durante la beta (Config.TRIAL_AUTOMATION_ENABLED=False): il trial è concesso
    solo manualmente via scripts/grant_trial.py e nessun downgrade automatico deve
    scattare finché il prodotto non è pubblico.
    """
    if not Config.TRIAL_AUTOMATION_ENABLED:
        logger.info(
            "[TrialExpiry] Automazione disabilitata (beta mode), skip.",
            extra={"domain": "app", "event": "trial_automation_disabled_beta_mode"},
        )
        return

    logger.info("[TrialExpiry] Avvio controllo trial scaduti.")
    expired = _user_store.get_expired_trials(datetime.utcnow())
    downgraded = 0
    for user in expired:
        try:
            # `set_user_plan` applica da sé gli eventuali giorni di Pro in credito
            # (referral/streak maturati mentre l'utente era già Pro): se ce n'erano,
            # l'utente resta Pro e non è un churn da contare.
            _user_store.set_user_plan(user.chat_id, "free", payment_reference="trial_expired")
            if _user_store.get_user_plan(user.chat_id)["plan_type"] == "pro":
                logger.info(
                    "[TrialExpiry] %s resta Pro: applicati giorni in credito.", user.chat_id,
                )
                continue
            _track_event(user.chat_id, "trial_expired", {})
            downgraded += 1
        except Exception as exc:
            log_exception(logger, level="error", domain="jobs", event="trial_downgrade_failed", exception=exc, chat_id=str(user.chat_id))

    logger.info("trial_expiry_completed", extra={"domain": "jobs", "event": "trial_expiry_completed", "meta": {"downgraded": downgraded, "eligible": len(expired)}})


def _build_drip_context(chat_id: str, step: str, trial_started_at: datetime, days: int) -> dict:
    """Costruisce i placeholder per il messaggio drip dello step richiesto.

    `reports_url` (D7/D14) e `piani_url` (D25/D29) sono sempre presenti, usati dal
    bottone CTA nelle email: entrambi passano dal login web con redirect alla pagina
    autenticata giusta dopo l'autenticazione (src/dashboard/app.py::web_login).
    """
    name = display_name(_user_store, chat_id)
    context = {
        "reports_url": f"{Config.WEBAPP_BASE_URL}/login?next=/reports",
        "piani_url": f"{Config.WEBAPP_BASE_URL}/login?next=/abbonamenti",
        "name": f" {name}" if name != "👋" else "",
    }
    if step == "d7":
        storage = _get_storage(chat_id)
        context["expense_count"] = count_user_expenses_since_signup(storage, trial_started_at)
    elif step == "d25":
        context["days_left"] = max(0, DRIP_STEPS["d29"] - days)
    elif step == "d29":
        context["discount_code"] = Config.TRIAL_DISCOUNT_CODE or "PRO30"
    return context


def _trial_lifecycle_job(app: Application, loop: asyncio.AbstractEventLoop) -> None:
    """Job APScheduler alle 09:00 — drip trial→Pro D7/D14/D25/D29 via Telegram + email.

    Spento durante la beta (Config.TRIAL_AUTOMATION_ENABLED=False): la logica è completa
    e testata, ma nessun invio deve partire finché il prodotto non è pubblico.
    """
    if not Config.TRIAL_AUTOMATION_ENABLED:
        logger.info(
            "[TrialLifecycle] Automazione disabilitata (beta mode), skip.",
            extra={"domain": "app", "event": "trial_automation_disabled_beta_mode"},
        )
        return

    logger.info("[TrialLifecycle] Avvio drip lifecycle trial.")

    async def _send_drip():
        bot = app.bot
        candidates = [u for u in _user_store.get_active_trial_users() if u.notifications_enabled]

        sent_telegram = 0
        sent_email = 0
        for user in candidates:
            chat_id = user.chat_id
            plan = _user_store.get_user_plan(chat_id)
            trial_started_at = plan["trial_started_at"]
            if not trial_started_at:
                continue
            days = compute_days_since_trial_start(trial_started_at)

            already_tg = _user_store.get_lifecycle_sent_steps(chat_id, "telegram")
            for step in steps_pending(days, already_tg):
                try:
                    context = _build_drip_context(chat_id, step, trial_started_at, days)
                    text = build_drip_message(step, "telegram", context)
                    # D25/D29: nessun bottone webapp, il testo rimanda al comando /piano
                    # (già esistente, gestito da cmd_piano) — più coerente col resto del bot.
                    markup = None if step in UPGRADE_CTA_STEPS else _get_dashboard_button()
                    await bot.send_message(
                        chat_id=int(chat_id), text=text, parse_mode=ParseMode.MARKDOWN,
                        reply_markup=markup,
                    )
                    _user_store.record_lifecycle_event(chat_id, step, "telegram")
                    _track_event(chat_id, "trial_drip_sent", {"step": step, "channel": "telegram"})
                    sent_telegram += 1
                except Exception as exc:
                    log_exception(logger, level="error", domain="jobs", event="trial_lifecycle_telegram_failed", exception=exc, chat_id=str(chat_id), meta={"step": step})
                await asyncio.sleep(0.5)

            if user.email:
                already_email = _user_store.get_lifecycle_sent_steps(chat_id, "email")
                for step in steps_pending(days, already_email):
                    try:
                        context = _build_drip_context(chat_id, step, trial_started_at, days)
                        subject = DRIP_TEMPLATES[step]["email_subject"].format(**context)
                        html = build_drip_message(step, "email", context)
                        unsub_token = make_unsubscribe_token(chat_id, Config.FLASK_SECRET_KEY)
                        unsub_url = f"{Config.WEBAPP_BASE_URL}/unsubscribe?chat_id={chat_id}&token={unsub_token}"
                        email_headers = {
                            "List-Unsubscribe": f"<{unsub_url}>",
                            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                        }
                        brevo_client.send_transactional_email(user.email, subject, html, headers=email_headers)
                        _user_store.record_lifecycle_event(chat_id, step, "email")
                        _track_event(chat_id, "trial_drip_sent", {"step": step, "channel": "email"})
                        sent_email += 1
                    except Exception as exc:
                        log_exception(logger, level="error", domain="jobs", event="trial_lifecycle_email_failed", exception=exc, chat_id=str(chat_id), meta={"step": step})
                    await asyncio.sleep(0.5)

        logger.info("trial_lifecycle_completed", extra={"domain": "jobs", "event": "trial_lifecycle_completed", "meta": {"telegram_sent": sent_telegram, "email_sent": sent_email}})

    future = asyncio.run_coroutine_threadsafe(_send_drip(), loop)
    try:
        future.result(timeout=300)
    except Exception as exc:
        log_exception(logger, level="error", domain="jobs", event="trial_lifecycle_job_failed", exception=exc)
        raise


def _nightly_subscription_job(app: Application, loop: asyncio.AbstractEventLoop) -> None:
    """Job APScheduler alle 03:00 — processa abbonamenti automatici per utenti Pro."""
    from datetime import date as _date

    logger.info("[NightlySubs] Avvio processing abbonamenti automatici.")

    async def _process_subs():
        today = _date.today()
        # Recupera tutti gli utenti PRO attivi
        pro_users = _user_store.get_pro_users()
        logger.info("[NightlySubs] Utenti Pro da controllare: %d", len(pro_users))
        
        for user in pro_users:
            chat_id = user.chat_id
            try:
                storage = _get_storage(chat_id)
                subs = storage.fetch_subscriptions()
                
                for sub in subs:
                    sub_name = sub.get("name", "Abbonamento")
                    amount = float(sub.get("amount") or 0)
                    last_billed = sub.get("last_billed")
                    sub_type = sub.get("sub_type")
                    account_id = sub.get("account_id")
                    
                    if not amount:
                        continue
                        
                    next_date = get_next_billing_date(last_billed, sub_type)
                    
                    # Se oggi è il giorno del rinnovo (o è passato)
                    if next_date and next_date <= today:
                        logger.info("subscription_charge_due", extra={"domain": "jobs", "event": "subscription_charge_due", "chat_id": str(chat_id), "meta": {}})
                        
                        # 1. Risolvi Monthly Balance
                        mb_id = storage.get_or_create_monthly_balance(today)

                        # 2. Crea la spesa
                        storage.create_expense(
                            expense_date=today,
                            amount=amount,
                            name=f"Rinnovo automatico: {sub_name}",
                            category_name="Abbonamenti",
                            monthly_balance_id=mb_id,
                            account_id=str(account_id) if account_id else None
                        )
                        
                        # 3. Aggiorna l'abbonamento con la nuova data
                        storage.update_subscription(sub.get("id"), last_billed=today)
                        
                        # 3. Notifica l'utente
                        new_next = get_next_billing_date(today, sub_type)
                        next_str = new_next.strftime('%d/%m/%Y') if new_next else "N/D"
                        try:
                            await app.bot.send_message(
                                chat_id=int(chat_id),
                                text=f"✅ *Rinnovo automatico effettuato!*\n\n"
                                     f"Ho registrato la spesa per *{sub_name}* (€{amount:,.2f}).\n"
                                     f"Prossimo rinnovo previsto: {next_str}",
                                parse_mode=ParseMode.MARKDOWN
                            )
                        except Exception as exc:
                            log_exception(logger, level="error", domain="jobs", event="subscription_notification_failed", exception=exc, chat_id=str(chat_id))

                        if user.notifications_enabled:
                            try:
                                with _user_store.Session() as notif_session:
                                    create_notification(
                                        notif_session, chat_id, "recurring_charge",
                                        title=f"Rinnovo automatico: {sub_name}",
                                        body=(
                                            f"Ho registrato la spesa per {sub_name} (€{amount:,.2f}). "
                                            f"Prossimo rinnovo previsto: {next_str}."
                                        ),
                                        payload={"subscription_id": sub.get("id")},
                                    )
                            except Exception as notif_err:
                                log_exception(
                                    logger,
                                    level="error",
                                    domain="jobs",
                                    event="recurring_notification_failed",
                                    exception=notif_err,
                                    chat_id=str(chat_id),
                                )

            except Exception as exc:
                log_exception(logger, level="error", domain="jobs", event="subscription_processing_failed", exception=exc, chat_id=str(chat_id))
            
            await asyncio.sleep(0.5)

    future = asyncio.run_coroutine_threadsafe(_process_subs(), loop)
    try:
        future.result(timeout=600)
    except Exception as exc:
        log_exception(logger, level="error", domain="jobs", event="subscription_job_failed", exception=exc)
        raise


def _nightly_inactivity_job() -> None:
    """Job APScheduler alle 05:00 — notifica in-app agli utenti Postgres senza
    spese registrate da almeno 7 giorni (re-engagement).

    Solo utenti Postgres: per Notion servirebbe una chiamata API per utente,
    troppo costosa e soggetta a rate limit per un controllo nightly su tutta la
    base utenti (vedi the Notion API limits).

    `expenses` ha la Row-Level Security abilitata (vedi `UserStore._user_session`):
    una query aggregata su una sessione non bindata al tenant non vede nessuna
    riga sul ruolo runtime, quindi il giro è per-utente con `_user_session`, non
    un'unica query cross-tenant.

    Dedup: non rinotifica ogni notte lo stesso periodo di inattività — controlla
    se esiste già una notifica `inactivity` creata dopo l'ultima spesa dell'utente;
    appena l'utente torna a registrare, `last_date` avanza e riabilita l'invio.
    """
    from sqlalchemy import func as _sql_func

    threshold = date.today() - timedelta(days=7)
    notified = 0
    try:
        pg_users = _user_store.get_active_postgres_users()
    except Exception as exc:
        log_exception(logger, level="error", domain="jobs", event="inactivity_users_fetch_failed", exception=exc)
        return

    for user in pg_users:
        if not user.notifications_enabled:
            continue
        chat_id = user.chat_id
        try:
            with _user_store._user_session(chat_id) as session:
                last_date = (
                    session.query(_sql_func.max(Expense.expense_date))
                    .filter(Expense.user_id == chat_id)
                    .scalar()
                )
                if last_date is None or last_date >= threshold:
                    continue
                since = datetime.combine(last_date, datetime.min.time())
                already_notified = (
                    session.query(Notification)
                    .filter(
                        Notification.user_id == chat_id,
                        Notification.type == "inactivity",
                        Notification.created_at > since,
                    )
                    .first()
                )
                if already_notified:
                    continue
                days_inactive = (date.today() - last_date).days
                body = (
                    f"Non registri una spesa da {days_inactive} giorni. "
                    "Torna a tenere traccia delle tue finanze!"
                )
                create_notification(
                    session, chat_id, "inactivity",
                    title="Non registri spese da un po'",
                    body=body,
                    payload={"days_inactive": days_inactive},
                )
                notified += 1
        except Exception as exc:
            log_exception(logger, level="error", domain="jobs", event="inactivity_user_processing_failed", exception=exc, chat_id=str(chat_id))
    logger.info("inactivity_notifications_completed", extra={"domain": "jobs", "event": "inactivity_notifications_completed", "meta": {"sent": notified}})


def _nightly_retention_cleanup() -> None:
    """Job APScheduler alle 03:10 — rimuove OAuth session scadute e chat_messages oltre 90gg.

    Applica le retention policy dichiarate (Art. 5.1(e) GDPR) che altrimenti
    restano solo teoriche: i due metodi esistevano già ma nessun job li invocava.
    """
    try:
        deleted_oauth = _user_store.cleanup_expired_oauth_sessions()
        deleted_chats = _user_store.cleanup_old_chat_messages(days=90)
        deleted_jobs = _user_store.cleanup_old_job_runs(days=90)
        deleted_candidates = _user_store.cleanup_stale_category_candidates(days=90)
        deleted_sub_candidates = _user_store.cleanup_stale_subscription_candidates(days=120)
        deleted_notifications = _user_store.cleanup_old_notifications(days=90)
        logger.info(
            "[NightlyRetention] OAuth sessions rimosse: %d, chat_messages rimossi: %d, "
            "job_runs rimossi: %d, category_candidates rimossi: %d, subscription_candidates rimossi: %d, "
            "notifications rimosse: %d",
            deleted_oauth, deleted_chats, deleted_jobs, deleted_candidates, deleted_sub_candidates,
            deleted_notifications,
        )
    except Exception as exc:
        log_exception(logger, level="error", domain="jobs", event="retention_job_failed", exception=exc)


def _streak_break_message(lost_streak_days: int) -> str:
    """Testo scherzoso per l'alert di streak interrotta, variante se era solo 1 giorno."""
    tail = (
        " Ricorda che segnare le tue finanze è fondamentale per trovare le "
        "inefficienze delle tue abitudini finanziarie!"
    )
    if lost_streak_days <= 1:
        return (
            "😅 Ops! Ieri ti sei dimenticato di segnare le spese e la streak è già "
            "andata in fumo... ripartiamo da zero, dai!" + tail
        )
    return (
        f"😅 Ops! Ieri ti sei dimenticato di segnare le spese e la streak di "
        f"*{lost_streak_days} giorni* è andata in fumo... si riparte da zero, dai!" + tail
    )


def mark_goal_reached(chat_id: str, goal: dict) -> list[dict]:
    """Registra il raggiungimento di un obiettivo nel motore achievement.

    Idempotente sul `dedup_key`: chiamarla sia dal rilevamento in tempo reale sia
    dal job mensile non assegna due volte lo stesso badge.
    """
    return [
        u.as_dict() for u in gamification.record_event(
            _user_store, chat_id, "savings_goal_completed",
            dedup_key=f"goal:{goal['id']}",
        )
    ]


def complete_reached_goals(chat_id: str, storage) -> tuple[list[dict], list[dict]]:
    """Chiude gli obiettivi già raggiunti e registra i relativi achievement.

    Usa `is_goal_reached`, che calcola solo il valore corrente senza ricostruire le
    serie mensili necessarie all'ETA: il costo resta una manciata di aggregati, non
    una scansione di tutto lo storico. È quindi chiamabile subito dopo una
    transazione confermata, senza aspettare il job del 1° del mese — che resta
    comunque la rete di sicurezza e continua a produrre voti e storico per il
    report, invariato.

    Non solleva mai: un errore qui non deve far fallire il salvataggio della spesa.

    Returns:
        `(obiettivi_chiusi, achievement_sbloccati)`.
    """
    try:
        from src.savings_goals_service import detect_completed_goals

        goals, unlocks = [], []
        for goal in detect_completed_goals(storage):
            storage.update_savings_goal(
                goal["id"], status="completed", completed_at=datetime.utcnow(),
            )
            goals.append(goal)
            unlocks += mark_goal_reached(chat_id, goal)
        return goals, unlocks
    except Exception as exc:  # noqa: BLE001 — la gamification non deve mai propagare
        logger.warning(
            "[SavingsGoals] Rilevamento in tempo reale fallito per %s: %s", chat_id, exc,
            extra={"domain": "gamification", "event": "goal_realtime_check_failed",
                   "meta": {"chat_id": str(chat_id)}},
        )
        return [], []


async def _check_goals_and_notify(bot, chat_id: str) -> list[dict]:
    """Chiude gli obiettivi raggiunti e manda il messaggio celebrativo su Telegram.

    Il testo è lo stesso del job mensile: raggiungere un obiettivo si festeggia
    allo stesso modo, che lo si scopra subito o il 1° del mese.

    **Non solleva mai.** Viene chiamata dentro il blocco che, in caso di eccezione,
    dice all'utente «non sono riuscito a salvare»: un errore qui — anche solo un
    `_get_storage` che fallisce per un token scaduto — farebbe comparire quel
    messaggio su una spesa già salvata, e l'utente la reinserirebbe.

    Returns:
        Gli achievement sbloccati, da notificare insieme agli altri.
    """
    try:
        storage = _get_storage(chat_id)
        if not isinstance(storage, PostgresStorage):
            return []

        goals, unlocks = complete_reached_goals(chat_id, storage)
        if not goals:
            return unlocks

        user = _user_store.get_user(chat_id)
        if user is not None and not user.notifications_enabled:
            return unlocks

        for goal in goals:
            try:
                await bot.send_message(
                    chat_id=int(chat_id),
                    text=f"🎉 Obiettivo raggiunto: *{goal['name']}*!",
                    parse_mode=ParseMode.MARKDOWN,
                )
                _track_event(chat_id, "notification_sent",
                             {"notification_type": "savings_goal_completed"})
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[SavingsGoals] Notifica obiettivo fallita per %s: %s", chat_id, exc,
                )
        return unlocks
    except Exception as exc:  # noqa: BLE001 — la spesa è già salvata, non ribaltarne l'esito
        logger.warning(
            "[SavingsGoals] Controllo obiettivi fallito per %s: %s", chat_id, exc,
            extra={"domain": "gamification", "event": "goal_check_failed",
                   "meta": {"chat_id": str(chat_id)}},
        )
        return []


async def _notify_achievements(bot, chat_id: str, unlocks: list[dict]) -> int:
    """Notifica su Telegram gli achievement appena sbloccati.

    Rispetta `notifications_enabled` (GDPR Art. 21) e marca gli sblocchi come già
    notificati, così un eventuale ricalcolo notturno non li rimanda. Non solleva
    mai: una notifica mancata non deve far fallire il flusso chiamante.

    Returns:
        Il numero di messaggi effettivamente inviati.
    """
    if not unlocks:
        return 0
    try:
        user = _user_store.get_user(chat_id)
        if user is not None and not user.notifications_enabled:
            return 0

        sent = 0
        for text in build_achievement_messages(unlocks):
            await bot.send_message(chat_id=int(chat_id), text=text, parse_mode="Markdown")
            sent += 1
            await asyncio.sleep(0.3)

        gamification.mark_notified(_user_store, chat_id, [u["code"] for u in unlocks])
        for unlock in unlocks:
            _track_event(chat_id, "achievement_unlocked", {
                "code": unlock["code"], "family": unlock["family"], "tier": unlock["tier"],
            })
        return sent
    except Exception as exc:  # noqa: BLE001 — la gamification non deve mai propagare
        logger.warning(
            "[Achievement] Notifica fallita per %s: %s", chat_id, exc,
            extra={"domain": "gamification", "event": "notify_failed",
                   "meta": {"chat_id": str(chat_id)}},
        )
        return 0


def _gamification_clean_month_job(app: Application, loop: asyncio.AbstractEventLoop) -> None:
    """Job APScheduler il 1° del mese alle 06:30 — valuta il mese appena chiuso.

    Un mese conta come "pulito" se non contiene nemmeno una spesa nella categoria di
    fallback e ne contiene almeno `CLEAN_MONTH_MIN_EXPENSES`: senza quella soglia
    basterebbe non registrare nulla per collezionare la serie.

    Un mese sporco azzera il contatore ma non revoca nulla: gli achievement già
    sbloccati restano.
    """
    from src.gamification.backfill import _previous_month, evaluate_month

    logger.info("[Gamification] Avvio valutazione cicli mensili.")
    year, month = _previous_month(date.today())
    evaluated = 0
    unlocks_by_chat: dict[str, list[dict]] = {}

    for user in _user_store.get_all_active_users():
        if user.storage_backend != "postgres":
            continue  # Notion non espone le categorie in modo affidabile: skip silenzioso
        chat_id = user.chat_id
        try:
            storage = _get_storage(chat_id)
            if not isinstance(storage, PostgresStorage):
                continue
            unlocks = evaluate_month(_user_store, chat_id, storage, year, month)
            evaluated += 1
            if unlocks:
                unlocks_by_chat[chat_id] = [u.as_dict() for u in unlocks]
        except Exception as exc:
            log_exception(logger, level="error", domain="gamification", event="monthly_cycle_failed", exception=exc, chat_id=str(chat_id))

    logger.info(
        "[Gamification] Cicli mensili: %d utenti valutati, %d con sblocchi.",
        evaluated, len(unlocks_by_chat),
        extra={"domain": "gamification", "event": "cycle_month_job_done",
               "meta": {"evaluated": evaluated, "unlocked": len(unlocks_by_chat)}},
    )
    _dispatch_achievement_notifications(app, loop, unlocks_by_chat)


def _gamification_reconcile_job(app: Application, loop: asyncio.AbstractEventLoop) -> None:
    """Job APScheduler alle 03:25 — riallinea i contatori e recupera gli sblocchi persi.

    I contatori sono materializzati: senza questa passata un evento perso resterebbe
    perso per sempre. Gira dopo il reset streak delle 03:15 così legge lo stato
    definitivo della giornata.
    """
    from src.gamification import backfill

    logger.info("[Gamification] Avvio riconciliazione contatori.")
    reconciled = 0
    unlocks_by_chat: dict[str, list[dict]] = {}

    for user in _user_store.get_all_active_users():
        chat_id = user.chat_id
        try:
            storage = None
            if user.storage_backend == "postgres":
                candidate = _get_storage(chat_id)
                storage = candidate if isinstance(candidate, PostgresStorage) else None
            counters = backfill.recompute_metrics(_user_store, chat_id, storage)
            # `notified=False`: questi sono sblocchi legittimi sfuggiti agli hook,
            # vanno festeggiati. Il silenzio è solo per il backfill iniziale.
            unlocks = gamification.evaluate(
                _user_store, chat_id, counters=counters, source="reconcile",
            )
            if unlocks:
                unlocks_by_chat[chat_id] = [u.as_dict() for u in unlocks]
            reconciled += 1
        except Exception as exc:
            log_exception(logger, level="error", domain="gamification", event="reconcile_failed", exception=exc, chat_id=str(chat_id))

    logger.info(
        "[Gamification] Riconciliazione completata: %d utenti, %d con sblocchi recuperati.",
        reconciled, len(unlocks_by_chat),
        extra={"domain": "gamification", "event": "reconcile_job_done",
               "meta": {"users": reconciled, "recovered": len(unlocks_by_chat)}},
    )
    _dispatch_achievement_notifications(app, loop, unlocks_by_chat)


def _dispatch_achievement_notifications(
    app: Application, loop: asyncio.AbstractEventLoop, unlocks_by_chat: dict[str, list[dict]],
) -> None:
    """Invia le notifiche di sblocco accumulate da un job (thread dello scheduler)."""
    if not unlocks_by_chat:
        return

    async def _run() -> int:
        sent = 0
        for chat_id, unlocks in unlocks_by_chat.items():
            sent += await _notify_achievements(app.bot, chat_id, unlocks)
            await asyncio.sleep(0.5)
        return sent

    future = asyncio.run_coroutine_threadsafe(_run(), loop)
    try:
        sent = future.result(timeout=300)
        logger.info("[Gamification] Notifiche di sblocco inviate: %d.", sent)
    except Exception as exc:
        log_exception(logger, level="error", domain="gamification", event="achievement_notifications_failed", exception=exc)


def _nightly_streak_reset_job(app: Application, loop: asyncio.AbstractEventLoop) -> None:
    """Job APScheduler alle 03:15 — azzera le streak interrotte da un giorno saltato
    e avvisa scherzosamente l'utente via Telegram.

    Safety net: senza una transazione futura non c'è altro modo di accorgersi che un
    utente ha smesso di registrare durante un ciclo di conteggio.
    """
    async def _notify_reset_users(reset_users: list[tuple[str, int]]) -> int:
        bot = app.bot
        sent = 0
        for chat_id, lost_streak_days in reset_users:
            user = _user_store.get_user(chat_id)
            if not user or not user.notifications_enabled:
                continue
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=_streak_break_message(lost_streak_days),
                    parse_mode="Markdown",
                )
                _track_event(chat_id, "notification_sent", {"notification_type": "streak_break"})
                sent += 1
            except Exception as exc:
                log_exception(logger, level="error", domain="jobs", event="streak_reset_notification_failed", exception=exc, chat_id=str(chat_id))
            await asyncio.sleep(0.5)
        return sent

    try:
        reset_users = _user_store.reset_stale_streaks()
        logger.info("[NightlyStreakReset] Streak azzerate: %d", len(reset_users))
        if reset_users:
            future = asyncio.run_coroutine_threadsafe(_notify_reset_users(reset_users), loop)
            sent = future.result(timeout=300)
            logger.info("streak_reset_notifications_completed", extra={"domain": "jobs", "event": "streak_reset_notifications_completed", "meta": {"sent": sent, "eligible": len(reset_users)}})
    except Exception as exc:
        log_exception(logger, level="error", domain="jobs", event="streak_reset_job_failed", exception=exc)


def _health_check_job() -> None:
    """Job periodico — verifica che DB e Mistral siano raggiungibili.

    Non blocca nulla: serve solo a far comparire un ERROR in error.jsonl/
    app.jsonl se una dipendenza critica smette di rispondere, prima che
    se ne accorga un utente.
    """
    from sqlalchemy import text as _sql_text

    db_ok = True
    try:
        with _user_store.engine.connect() as conn:
            conn.execute(_sql_text("SELECT 1"))
    except Exception as e:
        db_ok = False
        logger.error(
            "healthcheck_db_failed",
            extra={"event": "healthcheck_db_failed", "meta": {"error_type": type(e).__name__}},
        )

    mistral_ok = True
    try:
        if Config.MISTRAL_API_KEY:
            resp = requests.get(
                "https://api.mistral.ai/v1/models",
                headers={"Authorization": f"Bearer {Config.MISTRAL_API_KEY}"},
                timeout=10,
            )
            mistral_ok = resp.ok
    except Exception as e:
        mistral_ok = False
        logger.error(
            "healthcheck_mistral_failed",
            extra={"event": "healthcheck_mistral_failed", "meta": {"error_type": type(e).__name__}},
        )

    if db_ok and mistral_ok:
        logger.info("healthcheck_ok", extra={"event": "healthcheck_ok", "meta": {}})


def _disk_space_check_job(warning_mb: int = 1024, critical_mb: int = 500) -> None:
    """Job periodico — verifica lo spazio libero sul disco che ospita logs/.

    Il VPS ha risorse limitate (4GB RAM/disco): un disco pieno bloccherebbe
    silenziosamente scrittura log e DB. Soglie in MB, valori ragionevoli
    per un VPS Lite — regolabili se in futuro cambia la dimensione del disco.
    """
    usage = shutil.disk_usage(Config.LOG_DIR)
    free_mb = usage.free // (1024 * 1024)
    meta = {"free_mb": free_mb}
    if free_mb < critical_mb:
        logger.critical("disk_space_critical", extra={"event": "disk_space_critical", "meta": meta})
    elif free_mb < warning_mb:
        logger.warning("disk_space_low", extra={"event": "disk_space_low", "meta": meta})
    else:
        logger.info("disk_space_ok", extra={"event": "disk_space_ok", "meta": meta})


def _record_scheduler_event(event) -> None:
    """Listener APScheduler: persiste ogni esecuzione in `job_runs`.

    Consente alla dashboard admin di sapere se i job di oggi sono girati e con
    che esito. Gira nel thread dello scheduler; è best-effort (record_job_run
    non solleva). `error_text` contiene solo tipo/messaggio eccezione, mai dati
    liberi utente.
    """
    code = getattr(event, "code", None)
    exc = getattr(event, "exception", None)
    if exc is not None:
        status, error_text = "error", f"{type(exc).__name__}: {exc}"
    elif code == EVENT_JOB_MISSED:
        status, error_text = "missed", None
    else:
        status, error_text = "success", None
    _user_store.record_job_run(
        getattr(event, "job_id", "unknown"),
        status,
        trigger_type="scheduler",
        scheduled_at=getattr(event, "scheduled_run_time", None),
        error_text=error_text,
    )


async def _start_scheduler(app: Application) -> None:
    """Hook post_init PTB: cattura il loop PTB e avvia APScheduler con il loop corretto."""
    # Registra i comandi via API Telegram (setMyCommands) a ogni avvio: sostituisce
    # la registrazione manuale su BotFather, che andrebbe rifatta a mano ogni volta
    # che si aggiunge/rimuove un comando.
    # Depotenziamento Telegram: cattura (testo/voce/foto, /modify, categorizzazione)
    # + notifica con link, la lettura/gestione vive in webapp. Nessun alias/doppione:
    # ogni comando qui ha un solo nome e una sola destinazione. /trasferimento è
    # stato rimosso — l'AI riconosce già i trasferimenti da testo libero.
    await app.bot.set_my_commands([
        BotCommand("start", "Avvia o riavvia il bot"),
        BotCommand("registrati", "Registra un nuovo account"),
        BotCommand("accedi", "Accedi a un account esistente"),
        BotCommand("logout", "Esci dall'account corrente"),
        BotCommand("impostazioni", "Menu impostazioni account"),
        BotCommand("modify", "Gestisci conti, categorie e abbonamenti"),
        BotCommand("status", "Apri la tua dashboard"),
        BotCommand("piano", "Il tuo piano e i token residui"),
        BotCommand("piano_settimanale", "Genera il piano settimanale"),
        BotCommand("piano_mensile", "Genera il report mensile"),
        BotCommand("obiettivi", "I tuoi obiettivi di risparmio"),
        BotCommand("scova_abbonamenti", "Abbonamenti ricorrenti rilevati dalle spese"),
        BotCommand("privacy", "Link alla privacy policy"),
        BotCommand("export", "Esporta i tuoi dati (Art. 15/20 GDPR)"),
        BotCommand("elimina_account", "Cancella definitivamente l'account (Art. 17 GDPR)"),
        BotCommand("feedback", "Invia un feedback"),
    ])

    loop = asyncio.get_running_loop()
    # Timezone esplicita (non affidarsi al fuso locale del sistema): gli orari sotto
    # sono pensati in ora italiana e admin_metrics.SCHEDULER_TZ deve restare allineato
    # per il calcolo "atteso oggi"/no-show nella dashboard.
    scheduler = BackgroundScheduler(daemon=True, timezone="Europe/Rome")
    # id espliciti: sono la chiave con cui il listener registra gli esiti in
    # job_runs e con cui la dashboard confronta lo schedule atteso (no-show).
    scheduler.add_job(_nightly_category_sync, 'cron', hour=3, minute=0, args=[app, loop], id='nightly_category_sync')
    scheduler.add_job(_nightly_subscription_job, 'cron', hour=3, minute=5, args=[app, loop], id='nightly_subscription_job')
    scheduler.add_job(_nightly_retention_cleanup, 'cron', hour=3, minute=10, id='nightly_retention_cleanup')
    scheduler.add_job(_nightly_inactivity_job, 'cron', hour=5, minute=0, id='nightly_inactivity_job')
    scheduler.add_job(_nightly_streak_reset_job, 'cron', hour=3, minute=15, args=[app, loop], id='nightly_streak_reset_job')
    scheduler.add_job(_gamification_reconcile_job, 'cron', hour=3, minute=25, args=[app, loop], id='gamification_reconcile_job')
    # Il 1° del mese alle 06:30, prima degli obiettivi (07:30) e del report (08:00):
    # il mese appena chiuso deve essere già contabilizzato quando quelli girano.
    scheduler.add_job(_gamification_clean_month_job, 'cron', day=1, hour=6, minute=30, args=[app, loop], id='gamification_clean_month_job')
    scheduler.add_job(_trial_expiry_job, 'cron', hour=4, minute=0, args=[app, loop], id='trial_expiry_job')
    scheduler.add_job(_weekly_plan_job, 'cron', day_of_week='mon', hour=8, minute=5, args=[app, loop], id='weekly_plan_job')
    scheduler.add_job(_beta_feature_validation_job, 'cron', day_of_week='tue', hour=10, minute=0, args=[app, loop], id='beta_feature_validation_job')
    # 07:00, prima degli obiettivi (07:30): il mese va addebitato prima che
    # savings_goals_monthly_job valuti i saldi che dipendono da quelle spese.
    scheduler.add_job(_loan_monthly_charge_job, 'cron', day=1, hour=7, minute=0, args=[app, loop], id='loan_monthly_charge_job')
    scheduler.add_job(_mortgage_rate_review_job, 'cron', hour=7, minute=45, args=[app, loop], id='mortgage_rate_review_job')
    scheduler.add_job(_savings_goals_monthly_job, 'cron', day=1, hour=7, minute=30, args=[app, loop], id='savings_goals_monthly_job')
    scheduler.add_job(_monthly_plan_job, 'cron', day=1, hour=8, minute=0, args=[app, loop], id='monthly_plan_job')
    scheduler.add_job(_trial_lifecycle_job, 'cron', hour=9, minute=0, args=[app, loop], id='trial_lifecycle_job')
    scheduler.add_job(_health_check_job, 'interval', hours=4, id='health_check_job')
    scheduler.add_job(_disk_space_check_job, 'interval', hours=6, id='disk_space_check_job')
    scheduler.add_listener(
        _record_scheduler_event,
        EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED,
    )
    scheduler.start()
    logger.info(
        "⏰ Scheduler avviato (sync 03:00, subs 03:05, retention cleanup 03:10, "
        "trial expiry 04:00, daily 08:00, weekly plan lun 08:05, monthly plan 1° 08:00, "
        "trial drip 09:00, health-check ogni 4h, disk-check ogni 6h)."
    )


# ---------------------------------------------------------------------------
# Wizard onboarding — /impostazioni
# ---------------------------------------------------------------------------

def _ob_keyboard(options: list[tuple[str, str]], *, skip: bool = False, back: bool = True) -> InlineKeyboardMarkup:
    """Costruisce la tastiera inline per uno step del wizard."""
    rows = [[InlineKeyboardButton(label, callback_data=cb)] for label, cb in options]
    nav: list[InlineKeyboardButton] = []
    if back:
        nav.append(InlineKeyboardButton("↩ Indietro", callback_data="ob_back"))
    if skip:
        nav.append(InlineKeyboardButton("⏭ Salta", callback_data="ob_skip"))
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(rows)


_HOBBY_LABELS: dict[str, str] = {
    "palestra":  "💪 Palestra",
    "streaming": "📺 Streaming",
    "viaggi":    "✈️ Viaggi",
    "cultura":   "🎭 Cultura",
    "tech":      "💻 Tech",
    "animali":   "🐾 Animali",
    "cucina":    "🍳 Cucina",
    "famiglia":  "👶 Famiglia",
    "moda":      "👗 Moda",
}


def _ob_hobbies_keyboard(selected: list[str]) -> InlineKeyboardMarkup:
    """Griglia toggle per la selezione stile di vita (9 tag)."""
    keys = list(_HOBBY_LABELS.keys())
    rows = []
    for i in range(0, len(keys), 2):
        row = []
        for k in keys[i:i + 2]:
            icon = "✅ " if k in selected else ""
            row.append(InlineKeyboardButton(f"{icon}{_HOBBY_LABELS[k]}", callback_data=f"ob_hob_{k}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("✅ Avanti →", callback_data="ob_hob_done")])
    rows.append([
        InlineKeyboardButton("↩ Indietro", callback_data="ob_back"),
        InlineKeyboardButton("⏭ Salta", callback_data="ob_skip"),
    ])
    return InlineKeyboardMarkup(rows)


def _ob_progress(step: int, total: int = 5) -> str:
    filled = round((step / total) * 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"[{bar}] Step {step}/{total}\n\n"


async def cmd_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Avvia il wizard preferenze (age gate → lingua → stile vita → notifiche → conferma)."""
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return ConversationHandler.END
    context.user_data.clear()
    context.user_data["hobbies"] = []
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Sì, ho 18 anni o più", callback_data="ob_age_yes")],
        [InlineKeyboardButton("❌ Sono minorenne", callback_data="ob_age_no")],
    ])
    msg = (
        "🔞 <b>Verifica età</b>\n\n"
        "Expensum è riservato a utenti maggiorenni (18+).\n"
        "<i>D.Lgs. 101/2018, capacità contrattuale</i>"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    elif update.message:
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    return OB_AGE_GATE


async def ob_handle_age_gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gestisce la verifica età 18+. Se confermata, auto-rileva valuta/timezone e procede."""
    query = update.callback_query
    await query.answer()
    if query.data == "ob_age_no":
        await query.edit_message_text(
            "⚠️ <b>Servizio riservato ai maggiorenni</b>\n\n"
            "Expensum è disponibile solo per utenti con 18 anni o più.\n"
            "Per ulteriori informazioni consulta la nostra Privacy Policy.",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END
    chat_id = str(query.from_user.id)
    _user_store.set_age_attestation(chat_id, ip_address=None, platform="telegram")
    # Auto-rileva valuta e timezone dal language_code Telegram
    lc = (query.from_user.language_code or "it").lower()
    if lc.startswith("en-us") or lc == "en_us":
        currency, tz = "USD", "America/New_York"
    elif lc.startswith("en-gb") or lc == "en_gb":
        currency, tz = "GBP", "Europe/London"
    elif lc.startswith("en"):
        currency, tz = "GBP", "Europe/London"
    else:
        currency, tz = "EUR", "Europe/Rome"
    _user_store.save_onboarding_progress(chat_id, "currency", {"currency": currency})
    _user_store.save_onboarding_progress(chat_id, "timezone", {"timezone": tz})
    keyboard = _ob_keyboard([("🇮🇹 Italiano", "ob_lang_it"), ("🇬🇧 English", "ob_lang_en")], back=False)
    await query.edit_message_text(
        f"{_ob_progress(1)}🌍 <b>Che lingua preferisci?</b>",
        parse_mode=ParseMode.HTML, reply_markup=keyboard,
    )
    return OB_LANGUAGE


async def ob_handle_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    lang = "it" if query.data == "ob_lang_it" else "en"
    context.user_data["language"] = lang
    _user_store.save_onboarding_progress(str(query.from_user.id), "language", {"language": lang})
    await query.edit_message_text(
        f"{_ob_progress(2)}🎯 <b>Stile di vita</b>\n"
        "<i>Seleziona le aree che ti riguardano (opzionale). Tocca più volte per aggiungere o rimuovere.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=_ob_hobbies_keyboard([]),
    )
    return OB_HOBBIES


async def ob_handle_hobbies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Toggle multi-selezione stile di vita (9 tag). Back → lingua, Done/Skip → notifiche."""
    query = update.callback_query
    await query.answer()
    hobbies: list[str] = context.user_data.setdefault("hobbies", [])

    if query.data == "ob_back":
        keyboard = _ob_keyboard([("🇮🇹 Italiano", "ob_lang_it"), ("🇬🇧 English", "ob_lang_en")], back=False)
        await query.edit_message_text(
            f"{_ob_progress(1)}🌍 <b>Che lingua preferisci?</b>",
            parse_mode=ParseMode.HTML, reply_markup=keyboard,
        )
        return OB_LANGUAGE

    if query.data in ("ob_hob_done", "ob_skip"):
        _user_store.save_onboarding_progress(str(query.from_user.id), "hobbies", {"hobbies": hobbies})
        keyboard = _ob_keyboard([
            ("🔔 Sì, alle 08:00", "ob_notif_08:00"),
            ("🔕 No grazie", "ob_notif_off"),
        ], skip=True)
        await query.edit_message_text(
            f"{_ob_progress(4)}🔔 <b>Vuoi un riepilogo giornaliero?</b>",
            parse_mode=ParseMode.HTML, reply_markup=keyboard,
        )
        return OB_NOTIFICATIONS

    # Toggle tag
    tag = query.data.replace("ob_hob_", "")
    if tag in _HOBBY_LABELS:
        if tag in hobbies:
            hobbies.remove(tag)
        else:
            hobbies.append(tag)
        context.user_data["hobbies"] = hobbies

    selected_str = ", ".join(_HOBBY_LABELS[h] for h in hobbies) if hobbies else "nessuno"
    await query.edit_message_text(
        f"{_ob_progress(2)}🎯 <b>Stile di vita</b>\n"
        f"<i>Selezionati: {selected_str}</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=_ob_hobbies_keyboard(hobbies),
    )
    return OB_HOBBIES


async def ob_handle_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gestisce la preferenza riepilogo giornaliero. Back → hobbies, next → confirm."""
    query = update.callback_query
    await query.answer()
    if query.data == "ob_back":
        hobbies: list[str] = context.user_data.get("hobbies", [])
        selected_str = ", ".join(_HOBBY_LABELS[h] for h in hobbies) if hobbies else "nessuno"
        await query.edit_message_text(
            f"{_ob_progress(2)}🎯 <b>Stile di vita</b>\n"
            f"<i>Selezionati: {selected_str}</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=_ob_hobbies_keyboard(hobbies),
        )
        return OB_HOBBIES
    if query.data != "ob_skip" and query.data != "ob_notif_off":
        notif_time = query.data.replace("ob_notif_", "")
        _user_store.save_onboarding_progress(str(query.from_user.id), "notifications", {
            "notifications_enabled": True,
            "notification_time": notif_time,
        })
    elif query.data == "ob_notif_off":
        _user_store.save_onboarding_progress(str(query.from_user.id), "notifications", {
            "notifications_enabled": False,
        })

    # Mostra step 5/5 — riepilogo e conferma
    chat_id = str(query.from_user.id)
    prefs = _user_store.get_user_preferences(chat_id)
    hobbies = context.user_data.get("hobbies", [])
    hobby_labels = ", ".join(_HOBBY_LABELS.get(h, h) for h in hobbies) or "nessuno"
    summary = (
        f"{_ob_progress(5)}🎉 <b>Tutto pronto!</b>\n\n"
        f"🌍 Lingua: {prefs.get('preferred_language', 'it').upper()}\n"
        f"💱 Valuta: {prefs.get('currency', 'EUR')} <i>(rilevata automaticamente)</i>\n"
        f"🕐 Timezone: {prefs.get('timezone', 'Europe/Rome')} <i>(rilevata automaticamente)</i>\n"
        f"🎯 Interessi: {hobby_labels}\n\n"
        "Confermi e inizia a usare Expensum?"
    )
    await query.edit_message_text(
        summary,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Inizia!", callback_data="ob_confirm_yes")],
            [InlineKeyboardButton("↩ Indietro", callback_data="ob_back")],
        ]),
    )
    return OB_CONFIRM


async def ob_handle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 5/5 — conferma finale. Crea categorie via lookup table e completa onboarding."""
    query = update.callback_query
    await query.answer()

    if query.data == "ob_back":
        keyboard = _ob_keyboard([
            ("🔔 Sì, alle 08:00", "ob_notif_08:00"),
            ("🔕 No grazie", "ob_notif_off"),
        ], skip=True)
        await query.edit_message_text(
            f"{_ob_progress(4)}🔔 <b>Vuoi un riepilogo giornaliero?</b>",
            parse_mode=ParseMode.HTML, reply_markup=keyboard,
        )
        return OB_NOTIFICATIONS

    chat_id = str(query.from_user.id)
    hobbies: list[str] = context.user_data.get("hobbies", [])

    await query.edit_message_text("⏳ Creo le categorie e finalizzo…", parse_mode=ParseMode.HTML)

    try:
        from src.workspace_bootstrapper import bootstrap_lifestyle_categories, categories_from_hobbies
        categories = categories_from_hobbies(hobbies)
        storage = _get_storage(chat_id)
        bootstrap_lifestyle_categories(storage, categories)
    except Exception as e:
        logger.warning("Errore bootstrap categorie onboarding Telegram: %s", e)

    _user_store.complete_onboarding(chat_id)
    _track_event(chat_id, "onboarding_completed", {"platform": "telegram", "hobbies": hobbies})

    # Carica dati demo automaticamente per il tour nella web app
    demo_count = 0
    try:
        from src.demo_data import load_demo_data
        storage = _get_storage(chat_id)
        demo_count = load_demo_data(storage)
        _user_store.set_has_demo_data(chat_id, True)
        _track_event(chat_id, "demo_data_loaded", {"expense_count": demo_count, "platform": "telegram"})
    except Exception as e:
        logger.warning("[User %s] Errore caricamento demo data post-onboarding: %s", chat_id, e)

    keyboard = _webapp_button("✨ Scopri Expensum", "/chat?tour=1&demo=1")
    await query.edit_message_text(
        "🎉 <b>Tutto pronto!</b>\n\n"
        "Ho preparato <b>30 giorni di dati di esempio</b> così puoi vedere subito "
        "come funzionano analytics, report e tutto il resto.\n\n"
        "Apri la web app: ti guiderò in un tour rapido, poi puliamo i dati demo "
        "e sei pronto a iniziare davvero. 👇",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Menu /impostazioni — Privacy e dati / Preferenze
# ---------------------------------------------------------------------------

def _impostazioni_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔒 Privacy e dati", callback_data=IMP_MENU_PRIVACY_CB)],
        [InlineKeyboardButton("⚙️ Preferenze", callback_data=IMP_MENU_PREFS_CB)],
    ])


async def cmd_impostazioni_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler per /impostazioni — menu principale: Privacy e dati / Preferenze."""
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return
    text = "⚙️ <b>Impostazioni</b>\n\nCosa vuoi gestire?"
    if update.message:
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=_impostazioni_menu_keyboard()
        )


async def _cancel_wizard_show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fallback del wizard preferenze: se /impostazioni viene digitato a metà wizard,
    interrompe la conversazione e mostra il nuovo menu."""
    await cmd_impostazioni_menu(update, context)
    return ConversationHandler.END


def _privacy_menu_keyboard(notifications_enabled: bool) -> InlineKeyboardMarkup:
    notif_label = "🔕 Disattiva notifiche" if notifications_enabled else "🔔 Attiva notifiche"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Export dati", callback_data=PRIVACY_EXPORT_CB)],
        [InlineKeyboardButton("❌ Cancella account", callback_data=PRIVACY_DELETE_START_CB)],
        [InlineKeyboardButton(notif_label, callback_data=PRIVACY_NOTIF_TOGGLE_CB)],
        [InlineKeyboardButton("📄 Privacy Policy", callback_data=PRIVACY_POLICY_CB)],
        [InlineKeyboardButton("📄 Termini", callback_data=PRIVACY_TERMS_CB)],
        [InlineKeyboardButton("⬅️ Torna al menu", callback_data=IMP_MENU_BACK_CB)],
    ])


async def _show_privacy_menu(query, chat_id: str) -> None:
    user = _user_store.get_user(chat_id)
    notifications_enabled = bool(user.notifications_enabled) if user else True
    await query.edit_message_text(
        "🔒 <b>Privacy e dati</b>\n\n"
        "Qui puoi esercitare i tuoi diritti GDPR: accedere ai tuoi dati (Art. 15), "
        "ottenerli in formato portabile (Art. 20), opporti a un trattamento (Art. 21) "
        "o cancellare il tuo account (Art. 17).\nTempo di risposta standard: 1 mese, target 24h.",
        parse_mode=ParseMode.HTML,
        reply_markup=_privacy_menu_keyboard(notifications_enabled),
    )


def _preferences_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Modifica preferenze", callback_data=PREFS_EDIT_START_CB)],
        [InlineKeyboardButton("⬅️ Torna al menu", callback_data=IMP_MENU_BACK_CB)],
    ])


async def _show_preferences_menu(query, chat_id: str) -> None:
    prefs = _user_store.get_user_preferences(chat_id)
    notif = "attive" if prefs.get("notifications_enabled", True) else "disattivate"
    text = (
        "⚙️ <b>Preferenze</b>\n\n"
        f"🌍 Lingua: {(prefs.get('preferred_language') or 'it').upper()}\n"
        f"💱 Valuta: {prefs.get('currency') or 'EUR'}\n"
        f"🕐 Timezone: {prefs.get('timezone') or 'Europe/Rome'}\n"
        f"💰 Budget mensile: {prefs.get('monthly_budget') or 'non impostato'}\n"
        f"🔔 Notifiche: {notif}\n\n"
        "Per modificarle, riparti dal wizard guidato."
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=_preferences_menu_keyboard())


async def _send_privacy_export(context: ContextTypes.DEFAULT_TYPE, chat_id: str) -> bool:
    """Genera e invia l'export dati (Art. 15/20 GDPR), condiviso tra /export e il bottone /impostazioni.

    Ritorna False se l'utente non esiste (nessun documento inviato), True altrimenti.
    """
    with _user_store.Session() as s:
        user = s.query(User).filter_by(chat_id=chat_id).first()
        if not user:
            return False
        export_data = build_export_json(s, user)
        csv_rows = build_csv_rows(s, user)

    _user_store.write_audit_log(chat_id, actor="user", action="export_json", user_agent="telegram-bot")

    json_bytes = json.dumps(export_data, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    today_str = date.today().isoformat()
    await context.bot.send_document(
        chat_id=int(chat_id),
        document=InputFile(io.BytesIO(json_bytes), filename=f"expensum_dati_{today_str}.json"),
        caption="📥 Copia completa dei tuoi dati personali (Art. 15 GDPR).",
    )

    if csv_rows is not None:
        _user_store.write_audit_log(chat_id, actor="user", action="export_csv", user_agent="telegram-bot")
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(CSV_HEADER)
        for row in csv_rows:
            writer.writerow(row)
        csv_bytes = buffer.getvalue().encode("utf-8")
        await context.bot.send_document(
            chat_id=int(chat_id),
            document=InputFile(io.BytesIO(csv_bytes), filename=f"expensum_transazioni_{today_str}.csv"),
            caption="📥 Le tue transazioni in formato portabile (Art. 20 GDPR).",
        )
    else:
        await context.bot.send_message(
            chat_id=int(chat_id),
            text=(
                "ℹ️ I tuoi dati finanziari sono nel tuo workspace Notion personale: "
                "esportali direttamente da notion.so."
            ),
        )
    return True


async def _send_privacy_policy_link(context: ContextTypes.DEFAULT_TYPE, chat_id: str) -> None:
    """Invia il link alla privacy policy, condiviso tra /privacy e il bottone /impostazioni."""
    await context.bot.send_message(
        chat_id=int(chat_id),
        text=f"📄 Privacy Policy: {Config.WEBAPP_BASE_URL}/privacy",
    )


async def cmd_privacy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler per /privacy — invia direttamente il link alla privacy policy."""
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return
    await _send_privacy_policy_link(context, str(update.effective_chat.id))


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler per /export — genera ed invia l'export dati (Art. 15/20 GDPR) senza passare dal menu."""
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text("⏳ Generazione export in corso...")
    ok = await _send_privacy_export(context, chat_id)
    if not ok:
        await update.message.reply_text("❌ Utente non trovato.")


async def handle_impostazioni_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dispatcher per i bottoni del menu /impostazioni (Privacy e dati / Preferenze)."""
    query = update.callback_query
    await query.answer()
    chat_id = str(update.effective_chat.id)
    if not _is_authorized(update):
        return

    if query.data == IMP_MENU_PRIVACY_CB:
        await _show_privacy_menu(query, chat_id)
        return

    if query.data == IMP_MENU_PREFS_CB:
        await _show_preferences_menu(query, chat_id)
        return

    if query.data == IMP_MENU_BACK_CB:
        await query.edit_message_text(
            "⚙️ <b>Impostazioni</b>\n\nCosa vuoi gestire?",
            parse_mode=ParseMode.HTML,
            reply_markup=_impostazioni_menu_keyboard(),
        )
        return

    if query.data == PRIVACY_EXPORT_CB:
        await query.edit_message_text("⏳ Generazione export in corso...")
        ok = await _send_privacy_export(context, chat_id)
        if not ok:
            await query.edit_message_text("❌ Utente non trovato.")
            return
        await _show_privacy_menu(query, chat_id)
        return

    if query.data == PRIVACY_DELETE_START_CB:
        text, keyboard = _delete_account_confirmation_text_and_keyboard()
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
        return

    if query.data == PRIVACY_NOTIF_TOGGLE_CB:
        prefs = _user_store.get_user_preferences(chat_id)
        new_value = not prefs.get("notifications_enabled", True)
        _user_store.save_onboarding_progress(chat_id, "notifications_toggle", {"notifications_enabled": new_value})
        await _show_privacy_menu(query, chat_id)
        return

    if query.data == PRIVACY_POLICY_CB:
        await _send_privacy_policy_link(context, chat_id)
        return

    if query.data == PRIVACY_TERMS_CB:
        await context.bot.send_message(
            chat_id=int(chat_id),
            text="📄 Termini e Condizioni: pubblicazione in arrivo a breve.",
        )
        return


def _build_onboarding_conversation_handler() -> ConversationHandler:
    """Costruisce il ConversationHandler per il wizard preferenze.

    Il comando /impostazioni ora apre il menu top-level (cmd_impostazioni_menu);
    il wizard si avvia solo dal bottone "✏️ Modifica preferenze" del submenu
    Preferenze (callback PREFS_EDIT_START_CB), non più come comando diretto.
    """
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(cmd_onboarding, pattern=f"^{PREFS_EDIT_START_CB}$")],
        states={
            OB_AGE_GATE: [CallbackQueryHandler(ob_handle_age_gate, pattern="^ob_age_")],
            OB_LANGUAGE: [CallbackQueryHandler(ob_handle_language, pattern="^ob_lang_")],
            OB_HOBBIES: [CallbackQueryHandler(ob_handle_hobbies, pattern="^ob_(hob_|back|skip)")],
            OB_NOTIFICATIONS: [CallbackQueryHandler(ob_handle_notifications, pattern="^ob_(notif_|back|skip)")],
            OB_CONFIRM: [CallbackQueryHandler(ob_handle_confirm, pattern="^ob_(confirm_|back)")],
        },
        fallbacks=[CommandHandler("impostazioni", _cancel_wizard_show_menu)],
        allow_reentry=True,
    )


def main():
    setup_logging()

    parser = argparse.ArgumentParser(description="Bot Telegram per inserimento spese")
    parser.add_argument(
        "--webhook",
        type=str,
        default=None,
        metavar="URL",
        help="URL pubblica per webhook (es. https://example.com/bot). Se omesso, usa long-polling.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8443,
        help="Porta locale per il webhook (default: 8443)",
    )
    args = parser.parse_args()

    # Valida config
    try:
        Config.validate()
    except EnvironmentError as exc:
        log_exception(logger, level="error", domain="startup", event="configuration_invalid", exception=exc)
        sys.exit(1)

    # Crea l'applicazione
    # http_version="1.1" evita RemoteProtocolError: NO_ERROR sui server Telegram
    app = (
        Application.builder()
        .token(Config.TELEGRAM_BOT_TOKEN)
        .post_init(_start_scheduler)
        .request(HTTPXRequest(http_version="1.1"))
        .build()
    )

    # --- Handlers ---

    # ConversationHandler onboarding — va registrato PRIMA degli handler generici
    app.add_handler(_build_onboarding_conversation_handler())

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("registrati", cmd_registra))
    app.add_handler(CommandHandler("elimina_account", cmd_elimina_account))
    app.add_handler(CommandHandler("logout", cmd_logout))
    app.add_handler(CommandHandler("accedi", cmd_login))
    app.add_handler(CommandHandler("modify", cmd_modify))
    app.add_handler(CommandHandler("impostazioni", cmd_impostazioni_menu))
    app.add_handler(CommandHandler("privacy", cmd_privacy))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("feedback", cmd_feedback))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("piano", cmd_piano))
    app.add_handler(CommandHandler("obiettivi", cmd_obiettivi))
    app.add_handler(CommandHandler("scova_abbonamenti", cmd_scova_abbonamenti))
    app.add_handler(CommandHandler("piano_settimanale", cmd_piano_settimanale))
    app.add_handler(CommandHandler("piano_mensile", cmd_piano_mensile))
    app.add_handler(CallbackQueryHandler(handle_impostazioni_menu_callback, pattern="^(imp_menu_|privacy_)"))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE & ~filters.COMMAND, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_photos))

    # Registra l'error handler globale — cattura tutte le eccezioni non gestite
    app.add_error_handler(handle_error)

    if args.webhook:
        # Modalità webhook
        logger.info("webhook_starting", extra={"domain": "startup", "event": "webhook_starting", "meta": {}})
        app.run_webhook(
            listen="0.0.0.0",
            port=args.port,
            url_path="bot",
            webhook_url=f"{args.webhook}/bot",
        )
    else:
        # Modalità polling (sviluppo locale)
        logger.info("🔄 Avvio bot in modalità POLLING (sviluppo locale)")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
