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
import difflib
import io
import logging
import shutil
import sys
import json
import time
import threading
from datetime import date, datetime, timedelta
from cachetools import TTLCache
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED
import requests

from src.billing_utils import get_next_billing_date
from src.privacy_export import build_export_json, build_csv_rows, CSV_HEADER
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update, WebAppInfo
from telegram.constants import ParseMode
from telegram.request import HTTPXRequest
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

from config import Config, setup_logging
from src.expense_parser import ExpenseParser
from src.notion_client import NotionFinanceClient
from src.storage.base import FinancialStorage
from src.storage.notion_storage import NotionStorage                                                                                                         
from src.storage.postgres_storage import PostgresStorage
from src.rate_limiter import is_rate_limited
from src.user_store import UserStore, User
from src.ocr_client import OcrClient, OCRError
from src.vertex_ai_client import get_vertex_ai_client
from src.category_sync import refresh_category_averages
from src.budget_alert import check_expense_budget_alert
from src.dashboard_message import build_dashboard_text
from src.llm_usage_tracker import build_request_key, estimate_reserved_tokens, normalize_usage_metadata
from src.report_builder import WeeklyPlanBuilder, WeeklyPlanData, MonthlyPlanBuilder, MonthlyPlanData
from src.mistral_client import MistralClient
from src.report_notify import display_name, notify_webapp_report
from src import analytics
from src import brevo_client
from src.unsubscribe_token import make_unsubscribe_token
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
    categories = _user_store.get_user_category_names(chat_id)
    logger.info(f"Parser con {len(categories)} categorie per {chat_id}")
    return ExpenseParser(categories=categories)


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
            "⏸️ *Account sospeso.*\nUsa /login per riprendere da dove hai lasciato.",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            "⚠️ *Non sei ancora registrato!*\nUsa /registrati per configurare il bot.",
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


def _is_premium(chat_id: str) -> bool:
    """Ritorna True se l'utente ha un piano Pro."""
    plan = _user_store.get_user_plan(chat_id)
    return plan.get("plan_type") == "pro"


def _get_dashboard_keyboard(is_premium: bool) -> InlineKeyboardMarkup | None:
    """Ritorna la tastiera con il pulsante Analytics solo per utenti Pro."""
    if not is_premium:
        return None
    base_url = Config.WEBAPP_BASE_URL
    analytics_url = f"{base_url}/analytics"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                text="📊 Apri Analytics",
                web_app=WebAppInfo(url=analytics_url)
            )
        ]
    ])

def _get_dashboard_button() -> InlineKeyboardMarkup:
    """Bottone "Apri Dashboard" verso la webapp, usato nei messaggi drip trial (D7/D14)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                text="📊 Apri Dashboard",
                web_app=WebAppInfo(url=f"{Config.WEBAPP_BASE_URL}/dashboard"),
            )
        ]
    ])




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
) -> str | None:
    """Costruisce e invia il piano settimanale intelligente per un utente.

    Usata sia dal command handler che dal job APScheduler. Ritorna lo `share_token`
    del report salvato, o `None` se non è stato possibile generarlo.
    """
    storage = _get_storage(chat_id)
    builder = WeeklyPlanBuilder()

    try:
        plan_data = builder.build(storage)
    except Exception as e:
        logger.error(f"[User {chat_id}] Errore costruzione piano settimanale: {e}")
        err_text = "⚠️ Non riesco a raccogliere i dati per il piano settimanale. Riprova tra poco."
        if message:
            await message.reply_text(err_text)
        elif bot:
            await bot.send_message(chat_id=int(chat_id), text=err_text)
        return None

    # Prova con AI, fallback su testo statistico
    plan_text = None
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
        plan_text, usage = mistral.generate_weekly_plan(plan_data.to_prompt_text(), week_label)
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
        logger.warning(f"[User {chat_id}] Mistral weekly plan fallito, uso fallback: {e}")
        if reservation_created:
            try:
                _user_store.release_llm_reservation(chat_id, request_key, reason=str(e))
            except Exception:
                pass
        plan_text = builder.build_fallback_text(plan_data)

    # Salva report nel DB e notifica la chat webapp
    share_token: str | None = None
    try:
        share_token = storage.save_report(
            user_id=str(chat_id),
            report_type="weekly",
            report_date=plan_data.reference_date,
            text_content=plan_text,
            report_data=_serialize_weekly_data(plan_data),
        )
        if share_token:
            _notify_webapp_report(chat_id, "weekly", week_label, share_token)
    except Exception as e:
        logger.warning(f"[User {chat_id}] Salvataggio report settimanale fallito: {e}")

    # Genera tabella budget come immagine PNG
    table_image_path: str = ""
    try:
        table_image_path = builder.build_budget_table_image(plan_data)
    except Exception as e:
        logger.warning(f"[User {chat_id}] Generazione tabella immagine fallita: {e}")

    try:
        if message:
            await message.reply_text(plan_text, parse_mode=ParseMode.MARKDOWN)
            if table_image_path:
                with open(table_image_path, "rb") as img:
                    await message.reply_photo(img)
        elif bot:
            await bot.send_message(
                chat_id=int(chat_id),
                text=plan_text,
                parse_mode=ParseMode.MARKDOWN,
            )
            if table_image_path:
                with open(table_image_path, "rb") as img:
                    await bot.send_photo(chat_id=int(chat_id), photo=img)
    except Exception as e:
        logger.error(f"[User {chat_id}] Errore invio piano settimanale: {e}")
    finally:
        if table_image_path:
            try:
                os.remove(table_image_path)
            except OSError:
                pass

    return share_token


async def _build_and_send_monthly_plan(
    chat_id: str,
    bot=None,
    message=None,
    category_overrides: dict[str, float] | None = None,
) -> str | None:
    """Costruisce e invia il piano mensile intelligente per un utente.

    Usata dal command handler /monthly_plan. Ritorna lo `share_token` del report
    salvato, o `None` se non è stato possibile generarlo.
    """
    storage = _get_storage(chat_id)
    builder = MonthlyPlanBuilder()

    try:
        plan_data = builder.build(storage, category_overrides=category_overrides)
    except Exception as e:
        logger.error(f"[User {chat_id}] Errore costruzione piano mensile: {e}")
        err_text = "⚠️ Non riesco a raccogliere i dati per il piano mensile. Riprova tra poco."
        if message:
            await message.reply_text(err_text)
        elif bot:
            await bot.send_message(chat_id=int(chat_id), text=err_text)
        return None

    plan_text = None
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
        plan_text, usage = mistral.generate_monthly_plan(plan_data.to_prompt_text(), month_label)
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
        logger.warning(f"[User {chat_id}] Mistral monthly plan fallito, uso fallback: {e}")
        if reservation_created:
            try:
                _user_store.release_llm_reservation(chat_id, request_key, reason=str(e))
            except Exception:
                pass
        plan_text = builder.build_fallback_text(plan_data)

    # Salva report nel DB e notifica la chat webapp
    share_token: str | None = None
    try:
        share_token = storage.save_report(
            user_id=str(chat_id),
            report_type="monthly",
            report_date=plan_data.target_month,
            text_content=plan_text,
            report_data=_serialize_monthly_data(plan_data),
        )
        if share_token:
            _notify_webapp_report(chat_id, "monthly", month_label, share_token)
    except Exception as e:
        logger.warning(f"[User {chat_id}] Salvataggio report mensile fallito: {e}")

    try:
        if message:
            await message.reply_text(plan_text, parse_mode=ParseMode.MARKDOWN)
        elif bot:
            await bot.send_message(
                chat_id=int(chat_id),
                text=plan_text,
                parse_mode=ParseMode.MARKDOWN,
            )
    except Exception as e:
        logger.error(f"[User {chat_id}] Errore invio piano mensile: {e}")

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
    """Apre la mini app per gestire conti, categorie e abbonamenti."""
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    chat_id = str(update.effective_chat.id)
    reg_token = _user_store.create_oauth_session(chat_id)
    setup_url = f"{Config.WEBAPP_BASE_URL}/setup?reg_token={reg_token}"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Gestisci il tuo spazio", web_app=WebAppInfo(url=setup_url))]
    ])

    await update.message.reply_text(
        "⚙️ *Gestione Spazio Personale*\n\n"
        "Modifica i tuoi conti, categorie e abbonamenti:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )

# ---------------------------------------------------------------------------
# Dashboard / Status
# ---------------------------------------------------------------------------

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Invia la dashboard finanziaria e la fissa in alto nella chat."""
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    chat_id = str(update.effective_chat.id)
    await update.message.chat.send_action("typing")

    try:
        dashboard_text = _build_dashboard_for_user(chat_id)
    except Exception as e:
        logger.error(f"[User {chat_id}] Errore costruzione dashboard: {e}")
        await update.message.reply_text(
            "⚠️ Non sono riuscito a caricare la dashboard. Riprova tra qualche secondo."
        )
        return

    # Invia il nuovo messaggio dashboard
    msg = await update.message.reply_text(
        dashboard_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_get_dashboard_keyboard(_is_premium(chat_id))
    )

    # Unpin il vecchio messaggio dashboard (se esiste)
    old_msg_id = _user_store.get_pinned_dashboard_msg_id(chat_id)
    if old_msg_id:
        try:
            await context.bot.unpin_chat_message(
                chat_id=int(chat_id), message_id=old_msg_id
            )
        except Exception:
            pass  # Il messaggio potrebbe essere stato cancellato dall'utente

    # Pin il nuovo messaggio
    try:
        await msg.pin(disable_notification=True)
    except Exception as e:
        logger.warning(f"[User {chat_id}] Impossibile pinnare la dashboard: {e}")

    # Salva il message_id per futuri aggiornamenti
    _user_store.set_pinned_dashboard_msg_id(chat_id, msg.message_id)
    logger.info(f"[User {chat_id}] Dashboard inviata e pinnata (msg_id={msg.message_id})")


async def cmd_weekly_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Alias legacy → rimanda a cmd_weekly_plan."""
    await cmd_weekly_plan(update, context)


async def cmd_weekly_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Genera e invia il piano settimanale intelligente."""
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    chat_id = str(update.effective_chat.id)
    await update.message.chat.send_action("typing")

    await _build_and_send_weekly_plan(
        chat_id=chat_id,
        message=update.message,
    )


async def cmd_monthly_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Genera e invia il piano mensile intelligente per il mese successivo."""
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    chat_id = str(update.effective_chat.id)
    await update.message.chat.send_action("typing")

    overrides = context.user_data.get("monthly_overrides")

    await _build_and_send_monthly_plan(
        chat_id=chat_id,
        message=update.message,
        category_overrides=overrides,
    )

    context.user_data["monthly_plan_active_until"] = datetime.now().timestamp() + 1800


async def cmd_monthly_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lancia la pipeline mensile completa e invia il report al chat_id richiedente."""
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    chat_id = str(update.effective_chat.id)

    # Verifica quota token prima di avviare il subprocess (5000 token stimati)
    plan = _user_store.get_user_plan(chat_id)
    if plan["tokens_remaining"] < 5000:
        if plan["plan_type"] == "free":
            await update.message.reply_text(
                f"🛑 *Token mensili insufficienti*\n"
                f"Il report mensile richiede molte risorse, ma ne hai solo {plan['tokens_remaining']:,} rimasti.\n\n"
                f"Usa /piano per fare l'upgrade o attendi il reset mensile.",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text(
                "🛑 *Limite sistema raggiunto*\n"
                "Token insufficienti per generare il report. Contatta l'assistenza.",
                parse_mode=ParseMode.MARKDOWN,
            )
        return

    month_value = context.args[0] if context.args else None
    if month_value:
        try:
            target_dt = datetime.strptime(month_value, "%Y-%m")
            target_year, target_month = target_dt.year, target_dt.month
        except ValueError:
            await update.message.reply_text(
                "Formato non valido. Usa /monthly_report oppure /monthly_report YYYY-MM (es. 2026-04)."
            )
            return
    else:
        import main as main_module
        target_year, target_month = main_module._resolve_default_target_month(date.today())

    await update.message.reply_text(
        "📈 Sto analizzando il mese, un attimo..."
    )

    try:
        import main as main_module
        await main_module.run_agent(
            target_year, target_month, dry_run=False, chat_id=chat_id, shared_store=_user_store,
        )
    except Exception as e:
        logger.exception("[User %s] Errore generazione monthly_report: %s", chat_id, e)
        await update.message.reply_text(
            "⚠️ Errore tecnico nella generazione del report mensile. Riprova più tardi."
        )
        return

    # Aggiorna la dashboard pinnata: i token sono cambiati dopo la chiamata AI
    await _refresh_pinned_dashboard(context.bot, chat_id)


def _build_dashboard_for_user(chat_id: str) -> str:
    """Costruisce il testo della dashboard per un utente."""
    storage = _get_storage(chat_id)

    # Dati base: conti e abbonamenti
    accounts = storage.fetch_accounts()
    subscriptions = storage.fetch_subscriptions()

    # Dati premium: spese per categoria con medie storiche
    plan = _user_store.get_user_plan(chat_id)
    is_premium = plan["plan_type"] == "pro"
    categories_spending = None

    if is_premium:
        from datetime import date as _date
        today = _date.today()
        first_of_month = today.replace(day=1)

        # Prendi tutte le transazioni del mese corrente
        try:
            transactions = storage.fetch_all_transactions(first_of_month, today)
        except Exception as e:
            logger.warning(f"[User {chat_id}] Errore fetch transazioni per dashboard: {e}")
            transactions = []

        # Raggruppa per categoria
        spending_by_cat: dict[str, float] = {}
        for tx in transactions:
            cat = tx.get("category") or "Senza categoria"
            spending_by_cat[cat] = spending_by_cat.get(cat, 0.0) + float(tx.get("amount") or 0)

        # Recupera le medie storiche dal DB locale
        cat_averages = _user_store.get_user_categories_with_averages(chat_id)
        avg_map = {c["name"]: float(c["average"] or 0) for c in cat_averages}

        # Unisci spese attuali + medie
        all_cat_names = set(spending_by_cat.keys()) | set(avg_map.keys())
        categories_spending = []
        for cat_name in all_cat_names:
            categories_spending.append({
                "name": cat_name,
                "spent_this_month": spending_by_cat.get(cat_name, 0.0),
                "average": avg_map.get(cat_name, 0.0),
            })
        # Ordina per spesa del mese corrente decrescente
        categories_spending.sort(key=lambda c: c["spent_this_month"], reverse=True)

    return build_dashboard_text(
        accounts=accounts,
        subscriptions=subscriptions,
        categories_spending=categories_spending,
        is_premium=is_premium,
        user_plan=plan,
    )


async def _refresh_pinned_dashboard(bot, chat_id: str) -> None:
    """Aggiorna il messaggio dashboard pinnato con i dati più recenti.

    Chiamata dopo ogni salvataggio (spesa/entrata) per mantenere
    la dashboard sempre sincronizzata.
    """
    msg_id = _user_store.get_pinned_dashboard_msg_id(chat_id)
    if not msg_id:
        return  # L'utente non ha ancora una dashboard pinnata

    try:
        dashboard_text = _build_dashboard_for_user(chat_id)
        await bot.edit_message_text(
            chat_id=int(chat_id),
            message_id=msg_id,
            text=dashboard_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_get_dashboard_keyboard(_is_premium(chat_id))
        )
        logger.info(f"[User {chat_id}] Dashboard pinnata aggiornata (msg_id={msg_id})")
    except Exception as e:
        logger.warning(f"[User {chat_id}] Impossibile aggiornare dashboard pinnata: {e}")


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def cmd_piano(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mostra i dettagli del piano e dei token mensili."""
    chat_id = str(update.effective_chat.id)
    if not _is_authorized(update):
        await update.message.reply_text("Devi prima registrarti con /registrati.")
        return
        
    plan = _user_store.get_user_plan(chat_id)
    tipo = plan["plan_type"].upper()
    usati = plan["tokens_used_current_cycle"]
    rimanenti = plan["tokens_remaining"]
    totali = plan["tokens_total"]
    reset = plan["tokens_reset_at"].strftime("%d/%m/%Y")
    percent = round(usati / totali * 100, 1) if totali > 0 else 0.0
    percent_str = f"{percent:.1f}%" if percent > 0 else "<0.1%"

    testo = (
        f"📊 *Il tuo Piano: {tipo}*\n\n"
        f"🔹 Token utilizzati: {usati:,} ({percent_str})\n"
        f"🔹 Token rimanenti: {rimanenti:,} / {totali:,}\n"
        f"🔄 Reset previsto: {reset}\n\n"
    )
    
    if tipo == "FREE":
        testo += (
            "✨ *Passa a PRO per sbloccare:*\n"
            "• Parsing spese da foto scontrino 📸\n"
            "• Parsing note vocali 🎙️\n"
            "• Abbonamenti automatici 🔄\n"
            "• Report mensili AI 📈\n"
            "• Conti illimitati 🏦\n\n"
            "Puoi provare il piano PRO gratis per 1 mese!"
        )
        # TODO: aggiungere pulsante inline per l'upgrade (Stripe/Stars) quando integrati
    else:
        testo += "Grazie per essere un utente PRO! Hai accesso a tutte le funzionalità premium di Expensum 🚀"
        
    await update.message.reply_text(testo, parse_mode=ParseMode.MARKDOWN)

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
        try:
            _user_store.reassign_user_chat_id(old_chat_id, chat_id)
        except ValueError:
            logger.warning("[User %s] Collegamento Telegram fallito: chat_id già associato", chat_id)
            await update.message.reply_text(
                "⚠️ Questo account Telegram è già associato a un altro profilo Expensum."
            )
            return
        except Exception:
            logger.exception("[User %s] Collegamento Telegram fallito per errore imprevisto", chat_id)
            await update.message.reply_text(
                "⚠️ Si è verificato un errore durante il collegamento. Riprova tra qualche istante "
                "riaprendo lo stesso link."
            )
            return
        # Consuma il token solo ora che il collegamento è andato a buon fine: un
        # fallimento sopra lascia lo state valido, cosi' l'utente puo' ritentare
        # con lo stesso link entro la scadenza (15 minuti).
        _user_store.get_and_delete_oauth_session(state)
        logger.info("[User %s] Account web collegato a Telegram", chat_id)
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
            "Digita /registrati per creare un account, o /login se ne hai già uno e inizia a migliorare la tua vita "
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
    """Fornisce due opzioni di registrazione: OAuth Notion oppure backend PostgreSQL interno."""
    chat_id = str(update.effective_chat.id)

    # Verifica se l'utente esiste già (attivo o sospeso)
    user = _user_store.get_user_any_status(chat_id)
    if user:
        base_url = Config.WEBAPP_BASE_URL
        reg_token = _user_store.create_oauth_session(chat_id)
        
        login_url = f"{base_url}/auth/telegram-login?state={reg_token}"
        keyboard_buttons = [
            [InlineKeyboardButton("🔑 Fai Login", web_app=WebAppInfo(url=login_url))]
        ]
        
        if user.storage_backend == "postgres":
            keyboard_buttons.append([InlineKeyboardButton("🔄 Passa a Notion (Riavvia da zero)", callback_data="switch_to_notion")])
        else:
            keyboard_buttons.append([InlineKeyboardButton("🐘 Passa a PostgreSQL (Riavvia da zero)", callback_data="switch_to_postgres")])
            
        current_backend = user.storage_backend.capitalize() if user.storage_backend else "Notion"
        
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

    # Un unico reg_token monouso valido per entrambi i percorsi:
    # chi clicca per primo lo consuma e l'altro bottone resta inattivo.
    reg_token = _user_store.create_oauth_session(chat_id)

    base_url = Config.WEBAPP_BASE_URL
    notion_url = f"{base_url}/auth/notion?reg_token={reg_token}"
    postgres_url = f"{base_url}/auth/postgres?reg_token={reg_token}"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Connetti a Notion", url=notion_url)],
        [InlineKeyboardButton("🐘 Registrati su PostgreSQL", url=postgres_url)],
    ])

    await update.message.reply_text(
        "🚀 *Scegli come registrarti*\n\n"
        "🔗 *Notion* — sincronizza le spese nel tuo workspace Notion (autorizzazione OAuth).\n"
        "⚠️ I tuoi dati finanziari saranno conservati sull'infrastruttura di Notion Labs Inc. "
        "(*USA* 🇺🇸), salvo che tu abbia attivato la data residency UE sul tuo account Notion "
        "(solo piani Enterprise).\n\n"
        "🐘 *PostgreSQL* — salva i dati nel database interno di Expensum, su server *UE* 🇪🇺 "
        "(Germania), più veloce e senza rate limit.\n\n"
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


async def cmd_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Effettua il login di un utente registrato."""
    chat_id = str(update.effective_chat.id)
    user = _user_store.get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Non sei registrato. Scrivi /registrati per iniziare.")
        return


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
    logger.info(f"[User {chat_id}] Registrazione completata con tutti i DB.")
    _track_event(chat_id, "user_signed_up", {"auth_method": "telegram", "storage_backend": "notion"})
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
# /login — Accesso tramite mini app WebApp
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
            [[InlineKeyboardButton("🔑 Accedi", web_app=WebAppInfo(url=login_url))]]
        ),
    )


# ---------------------------------------------------------------------------
# /logout — Sospensione temporanea account
# ---------------------------------------------------------------------------

async def cmd_logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Chiede conferma prima di sospendere temporaneamente l'account."""
    if not _is_authorized(update):
        await update.message.reply_text(
            "⚠️ Non sei registrato. Usa /registrati per iniziare.",
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
        "I tuoi dati resteranno al sicuro. Potrai riprendere da dove hai lasciato usando /login.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )


# ---------------------------------------------------------------------------
# /trasferimento — Spostamento di denaro guidato a bottoni tra due conti
# ---------------------------------------------------------------------------

async def cmd_trasferimento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Avvia il flusso guidato a bottoni per spostare denaro tra due conti dell'utente.

    Stessa pipeline di risoluzione conti/importo/conferma usata dal ramo NLP in
    _process_expense_text — vedi _advance_transfer_flow.
    """
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    chat_id = str(update.effective_chat.id)

    if is_rate_limited(chat_id, max_messages=Config.MAX_MESSAGES_PER_MINUTE):
        await update.message.reply_text("⏳ Stai inviando troppi messaggi. Aspetta un momento e riprova.")
        return

    context.user_data["pending_expense"] = {
        "type": "transfer",
        "date": date.today().isoformat(),
        "amount": None,
        "category": None,
        "income_type": None,
        "name": "Trasferimento",
        "from_account_id": None,
        "to_account_id": None,
    }
    context.user_data.pop("waiting_for_amount", None)
    context.user_data.pop("expense_queue", None)
    context.user_data["input_method"] = "button"

    async def _send(text, reply_markup=None):
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

    await _advance_transfer_flow(context, chat_id, _send)


def _build_expense_summary(data: dict) -> str:
    """Costruisce il testo di riepilogo per una spesa/entrata in sospeso di conferma."""
    from datetime import datetime
    dt = datetime.fromisoformat(data["date"]) if isinstance(data["date"], str) else data["date"]
    date_str = dt.strftime("%d/%m/%Y")
    if data.get("type") == "income":
        income_type_label = data.get("income_type") or "Non determinato"
        return (
            f"📝 *Nuova Entrata riconosciuta:*\n\n"
            f"📅 Data: *{date_str}*\n"
            f"💰 Importo: *€{data['amount']:.2f}*\n"
            f"🏷️ Tipo: *{income_type_label}*\n"
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
        if data.get("type") == "expense":
            rows.append([InlineKeyboardButton("✏️ Cambia categoria", callback_data=f"medit_category:{tx_id}")])
        rows.append([
            InlineKeyboardButton("✅ Conferma", callback_data=f"mconfirm:{tx_id}"),
            InlineKeyboardButton("❌ Annulla", callback_data=f"mcancel:{tx_id}"),
        ])
        return InlineKeyboardMarkup(rows)

    rows = []
    if data.get("type") == "expense":
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


def _resolve_account_hint(hint: str | None, accounts: list[dict]) -> dict | None:
    """Risolve un nome conto libero (hint estratto dall'NLP) su un conto reale dell'utente.

    Prova prima il match esatto case-insensitive, poi un fuzzy match (stessa soglia 0.6
    usata in expense_parser.py per categorie/income_type). None se non menzionato o
    se non trova nessun conto abbastanza simile.
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
        except Exception as e:
            logger.error(f"[User {chat_id}] Errore fetch accounts per trasferimento: {e}")
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
            "domain": "access",
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

    # Controlla se siamo in attesa dell'importo
    if context.user_data.get("waiting_for_amount"):
        parser = _get_parser(chat_id)
        amount_res = parser.parse(message_text)
        
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
    transactions, usage = parser.parse_multi_with_usage(safe_input)
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
        _track_event(chat_id, "expense_tracking_failed", {"reason": "ai_unavailable", "input_method": "text"})
        _user_store.record_tx_event(chat_id, "unknown", "text", "failed", "telegram", reason="ai_unavailable")
        await update.message.reply_text(
            "⚠️ Non sono riuscito ad elaborare il messaggio in questo momento.\n"
            "Il servizio AI è temporaneamente sovraccarico — riprova tra qualche secondo! 🔄",
        )
        return

    logger.info(f"[User {chat_id}] Risultato parser: {len(transactions)} transazione/i rilevate")

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
    logger.info(f"[User {chat_id}] Vocale ricevuto: '{file_info.file_id}' ({voice.file_size} bytes)")

    # 🛡️ Nome file unico per chat_id (evita race condition tra utenti)
    temp_path = f"temp_voice_{chat_id}.ogg"

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
                "domain": "access",
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
            logger.info(f"[User {chat_id}] File temporaneo eliminato: {temp_path}")

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
    logger.info(f"[User {chat_id}] Foto ricevuta: '{file_info.file_id}' ({foto_hd.file_size} bytes)")

    # 🛡️ Nome file unico per chat_id (evita race condition tra utenti)
    temp_path = f"temp_photo_{chat_id}.jpg"

    # 🛡️ try/finally garantisce la pulizia del file anche in caso di errore
    try:
        await file_info.download_to_drive(temp_path)
        await update.message.reply_text("Immagine ricevuta! Sto accendendo gli occhi bionici... 👁️📸")

        try:
            message_trascribed = OcrClient().extract_text_from_image(temp_path)
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
                "domain": "access",
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
            logger.info(f"[User {chat_id}] File temporaneo eliminato: {temp_path}")

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
                income_type=data.get("income_type"),
            )
            date_str = date.strftime("%d/%m/%Y")
            await query.edit_message_text(
                f"✅ *Entrata salvata!*\n\n"
                f"📅 {date_str} — *€{data['amount']:.2f}* — {data['name']}",
                parse_mode=ParseMode.MARKDOWN,
            )
            logger.info(f"[User {chat_id}] Entrata salvata: {data['name']} €{data['amount']:.2f}")
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
            date_str = date.strftime("%d/%m/%Y")
            saved_msg = (
                f"✅ *Spesa salvata!*\n\n"
                f"📅 {date_str} — *€{data['amount']:.2f}* — {data['name']}"
            )
            # Alert budget categoria in tempo reale (soglie 80/100/120%).
            try:
                alert = check_expense_budget_alert(storage, data.get("category"), date)
                if alert:
                    saved_msg += f"\n\n{alert}"
            except Exception as _ae:
                logger.warning("[User %s] Calcolo alert budget fallito: %s", chat_id, _ae)
            await query.edit_message_text(
                saved_msg,
                parse_mode=ParseMode.MARKDOWN,
            )
            logger.info(f"Spesa salvata: {data['name']} €{data['amount']:.2f}")
            try:
                _success_text = f"✅ Spesa salvata: {data['name']} €{data['amount']:.2f}"
                _user_store.log_message(chat_id, source="telegram", role="bot", text=_success_text, metadata=data)
            except Exception as _le:
                logger.debug("[User %s] log_message expense saved fallito: %s", chat_id, _le)

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
        _user_store.record_tx_event(chat_id, tx_type, input_method, "confirmed", "telegram")

        # Aggiorna la dashboard pinnata in background (se esiste)
        try:
            _user_store.increment_ai_metrics(success=True)
            await _refresh_pinned_dashboard(query._bot, chat_id)
        except Exception as e:
            logger.warning(f"[User {chat_id}] Errore refresh dashboard post-save: {e}")

        # Messaggio multi-spesa: se ce ne sono altre in coda, presenta subito la prossima
        try:
            await _present_next_pending_expense(context, chat_id)
        except Exception as e:
            logger.warning(f"[User {chat_id}] Errore presentazione prossima transazione in coda: {e}")

    except Exception as e:
        logger.error(f"Errore salvataggio Notion: {e}")
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
            f"📅 {date_str} — *€{data['amount']:.2f}*\n"
            f"🏦 {from_name} → {to_name}",
            parse_mode=ParseMode.MARKDOWN,
        )
        logger.info(f"[User {chat_id}] Trasferimento salvato: €{data['amount']:.2f}")
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
            await _refresh_pinned_dashboard(query._bot, chat_id)
        except Exception as e:
            logger.warning(f"[User {chat_id}] Errore refresh dashboard post-save: {e}")

        try:
            await _present_next_pending_expense(context, chat_id)
        except Exception as e:
            logger.warning(f"[User {chat_id}] Errore presentazione prossima transazione in coda: {e}")

    except ValueError as e:
        logger.warning(f"[User {chat_id}] Trasferimento non valido: {e}")
        await query.edit_message_text(f"⚠️ {e}")
    except Exception as e:
        logger.error(f"Errore salvataggio trasferimento: {e}")
        await query.edit_message_text(
            "⚠️ Non sono riuscito a salvare il trasferimento in questo momento.\n"
            "Riprova tra qualche secondo oppure contatta il supporto se il problema persiste.",
        )


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
        logger.info(f"[User {chat_id}] Account sospeso via /logout")
        await query.edit_message_text(
            "👋 *Account sospeso.*\n\nI tuoi dati sono al sicuro. Usa /login per riprendere quando vuoi.",
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
        logger.info(f"[User {chat_id}] Account eliminato (backend: {backend})")
        farewell_name = (update.effective_user.first_name or "").strip()
        farewell = f"Ciao {farewell_name}! 👋" if farewell_name else "Ciao! 👋"
        await query.edit_message_text(
            f"✅ Account eliminato. Tutti i tuoi dati sono stati cancellati.\n\n{farewell}"
        )
        return

    if query.data in ["switch_to_notion", "switch_to_postgres"]:
        # Elimina tutti i dati dell'account
        _user_store.delete_user_completely(chat_id)
        logger.info(f"[User {chat_id}] Account eliminato per passaggio a nuova origine dati ({query.data})")
        
        # Rigenera token e bottoni per la registrazione pulita
        reg_token = _user_store.create_oauth_session(chat_id)
        base_url = Config.WEBAPP_BASE_URL
        notion_url = f"{base_url}/auth/notion?reg_token={reg_token}"
        postgres_url = f"{base_url}/auth/postgres?reg_token={reg_token}"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Connetti a Notion", url=notion_url)],
            [InlineKeyboardButton("🐘 Registrati su PostgreSQL", url=postgres_url)],
        ])

        target = "Notion" if query.data == "switch_to_notion" else "PostgreSQL"
        await query.edit_message_text(
            f"✅ *Dati precedenti eliminati con successo!*\n\n"
            f"Ora puoi procedere alla nuova registrazione con {target} (o cambiare idea) scegliendo un'opzione qui sotto:\n\n"
            "⚠️ *Notion*: dati conservati su infrastruttura USA 🇺🇸 (salvo data residency UE su piani "
            "Enterprise Notion). *PostgreSQL*: dati su server UE 🇪🇺 (Germania).",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
        return

    if query.data == "delete_account_cancel":
        await query.edit_message_text("❌ Eliminazione annullata. Il tuo account è al sicuro.")
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
        _track_event(chat_id, "expense_tracking_failed", {"reason": "user_cancelled", "input_method": "text"})
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
            category_names = storage.get_category_names()
        except Exception as e:
            logger.error(f"[User {chat_id}] Errore fetch categorie: {e}")
            await query.edit_message_text("⚠️ Errore nel recupero delle categorie. Riprova tra qualche istante.")
            return

        if not category_names:
            await query.edit_message_text("⚠️ Non hai ancora nessuna categoria configurata. Usa /modify per crearne una.")
            return

        context.user_data["category_options"] = category_names
        keyboard = [
            [InlineKeyboardButton(name, callback_data=f"msetcat:{tx_id}:{idx}")]
            for idx, name in enumerate(category_names)
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
        category_options = context.user_data.get("category_options")
        if not pending or not category_options:
            await query.edit_message_text("⚠️ Nessuna spesa in sospeso.")
            return
        try:
            new_category = category_options[int(idx_str)]
        except (ValueError, IndexError):
            await query.edit_message_text("⚠️ Categoria non valida. Riprova.")
            return

        pending["category"] = new_category
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
        except Exception as e:
            logger.error(f"[User {chat_id}] Errore fetch accounts: {e}")
            await query.edit_message_text("⚠️ Errore nel recupero dei tuoi conti. Riprova tra qualche istante.")
            return

        if not accounts:
            # Nessun conto configurato: blocca solo questa transazione (le altre in parallelo
            # restano in sospeso, l'utente potrà confermarle appena avrà creato un conto).
            context.user_data.get("pending_expenses", {}).pop(tx_id, None)
            _track_event(chat_id, "expense_tracking_failed", {"reason": "no_account", "input_method": "text"})
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
            category_names = storage.get_category_names()
        except Exception as e:
            logger.error(f"[User {chat_id}] Errore fetch categorie: {e}")
            await query.edit_message_text("⚠️ Errore nel recupero delle categorie. Riprova tra qualche istante.")
            return

        if not category_names:
            await query.edit_message_text("⚠️ Non hai ancora nessuna categoria configurata. Usa /modify per crearne una.")
            return

        # Le categorie vanno in user_data (non nel callback_data) per non rischiare
        # di superare il limite di 64 byte di Telegram con nomi lunghi o emoji.
        context.user_data["category_options"] = category_names
        keyboard = [
            [InlineKeyboardButton(name, callback_data=f"setcat:{idx}")]
            for idx, name in enumerate(category_names)
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
        category_options = context.user_data.get("category_options")
        if not pending or not category_options:
            await query.edit_message_text("⚠️ Nessuna spesa in sospeso.")
            return
        try:
            idx = int(query.data.split(":", 1)[1])
            new_category = category_options[idx]
        except (ValueError, IndexError):
            await query.edit_message_text("⚠️ Categoria non valida. Riprova.")
            return

        pending["category"] = new_category
        summary = _build_expense_summary(pending)
        keyboard = _build_confirm_keyboard(pending)
        await query.edit_message_text(summary, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
        return

    if query.data == "cancel":
        input_method = context.user_data.pop("input_method", "text")
        cancelled_data = context.user_data.pop("pending_expense", None)
        context.user_data.pop("waiting_for_amount", None)
        _track_event(chat_id, "expense_tracking_failed", {"reason": "user_cancelled", "input_method": input_method})
        _user_store.record_tx_event(
            chat_id, (cancelled_data or {}).get("type", "expense"), input_method, "cancelled", "telegram",
            reason="user_cancelled",
        )
        await query.edit_message_text("❌ Operazione annullata.")
        # Messaggio multi-spesa: annullare una transazione non annulla le altre in coda
        try:
            await _present_next_pending_expense(context, chat_id)
        except Exception as e:
            logger.warning(f"[User {chat_id}] Errore presentazione prossima transazione in coda: {e}")
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
        except Exception as e:
            logger.error(f"[User {chat_id}] Errore fetch accounts: {e}")
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
            _track_event(chat_id, "expense_tracking_failed", {"reason": "no_account", "input_method": input_method})
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
        except Exception as e:
            logger.error(f"[User {chat_id}] Errore fetch accounts: {e}")
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


# ---------------------------------------------------------------------------
# Error handler globale
# ---------------------------------------------------------------------------

async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler globale per le eccezioni non gestite nel bot.

    Logga l'errore con contesto (update_id, chat_id) senza dati sensibili
    e notifica l'utente con un messaggio generico.
    """
    logger.error(
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
                )
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


def _daily_dashboard_job(app: Application, loop: asyncio.AbstractEventLoop) -> None:
    """Job APScheduler alle 08:00 — invia una nuova dashboard giornaliera per ogni utente attivo.

    Per ogni utente:
    1. Costruisce il testo dashboard aggiornato
    2. Invia un nuovo messaggio
    3. Unpin il vecchio, pin il nuovo
    4. Salva il nuovo msg_id
    """
    logger.info("[DailyDashboard] Avvio invio dashboard giornaliere.")

    async def _send_dashboards():
        bot = app.bot
        # Recupera tutti gli utenti attivi (sia Notion che Postgres), escludendo
        # chi ha disattivato le notifiche (Art. 21 GDPR, opposizione al trattamento)
        notion_users = _user_store.get_active_notion_users()
        pg_users = _user_store.get_active_postgres_users()
        all_users = [u for u in list(notion_users) + list(pg_users) if u.notifications_enabled]

        sent = 0
        for user in all_users:
            chat_id = user.chat_id
            try:
                dashboard_text = _build_dashboard_for_user(chat_id)

                # Invia nuovo messaggio
                msg = await bot.send_message(
                    chat_id=int(chat_id),
                    text=dashboard_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=_get_dashboard_keyboard(_is_premium(chat_id)),
                )

                # Unpin vecchio
                old_msg_id = _user_store.get_pinned_dashboard_msg_id(chat_id)
                if old_msg_id:
                    try:
                        await bot.unpin_chat_message(
                            chat_id=int(chat_id), message_id=old_msg_id
                        )
                    except Exception:
                        pass

                # Pin nuovo
                try:
                    await bot.pin_chat_message(
                        chat_id=int(chat_id),
                        message_id=msg.message_id,
                        disable_notification=True,
                    )
                except Exception as e:
                    logger.warning(f"[DailyDashboard] Pin fallito per {chat_id}: {e}")

                # Salva
                _user_store.set_pinned_dashboard_msg_id(chat_id, msg.message_id)
                _track_event(chat_id, "notification_sent", {"notification_type": "daily_dashboard"})
                sent += 1
                logger.info(f"[DailyDashboard] Dashboard inviata a {chat_id}")

            except Exception as e:
                logger.error(f"[DailyDashboard] Errore per {chat_id}: {e}")

            await asyncio.sleep(0.5)

        logger.info(f"[DailyDashboard] Completato: {sent}/{len(all_users)} dashboard inviate.")

    future = asyncio.run_coroutine_threadsafe(_send_dashboards(), loop)
    try:
        future.result(timeout=300)
    except Exception as e:
        logger.error(f"[DailyDashboard] Errore job: {e}")
        raise


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
                logger.info(f"[WeeklyPlan] Piano inviato a {chat_id}")
            except Exception as e:
                logger.error(f"[WeeklyPlan] Errore per {chat_id}: {e}")
            await asyncio.sleep(0.5)

        logger.info(f"[WeeklyPlan] Completato: {sent}/{len(all_users)} piani inviati.")

    future = asyncio.run_coroutine_threadsafe(_send_plans(), loop)
    try:
        future.result(timeout=300)
    except Exception as e:
        logger.error(f"[WeeklyPlan] Errore job: {e}")
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
                logger.info(f"[MonthlyReport] Salto {chat_id}: token insufficienti")
                continue
            try:
                await main_module.run_agent(
                    target_year, target_month, dry_run=False, chat_id=chat_id, shared_store=_user_store,
                )
                _track_event(chat_id, "notification_sent", {"notification_type": "monthly_report"})
                sent += 1
                logger.info(f"[MonthlyReport] Report inviato a {chat_id}")
            except Exception as e:
                logger.error(f"[MonthlyReport] Errore per {chat_id}: {e}")
            await asyncio.sleep(0.5)

        logger.info(f"[MonthlyReport] Completato: {sent}/{len(all_users)} report inviati.")

    future = asyncio.run_coroutine_threadsafe(_send_reports(), loop)
    try:
        future.result(timeout=1800)
    except Exception as e:
        logger.error(f"[MonthlyReport] Errore job: {e}")
        raise


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
            _user_store.set_user_plan(user.chat_id, "free", payment_reference="trial_expired")
            _track_event(user.chat_id, "trial_expired", {})
            downgraded += 1
        except Exception as e:
            logger.error(f"[TrialExpiry] Errore downgrade per {user.chat_id}: {e}")

    logger.info(f"[TrialExpiry] Completato: {downgraded}/{len(expired)} downgrade effettuati.")


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
                except Exception as e:
                    logger.error(f"[TrialLifecycle] Errore Telegram {step} per {chat_id}: {e}")
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
                    except Exception as e:
                        logger.error(f"[TrialLifecycle] Errore email {step} per {chat_id}: {e}")
                    await asyncio.sleep(0.5)

        logger.info(f"[TrialLifecycle] Completato: {sent_telegram} telegram, {sent_email} email.")

    future = asyncio.run_coroutine_threadsafe(_send_drip(), loop)
    try:
        future.result(timeout=300)
    except Exception as e:
        logger.error(f"[TrialLifecycle] Errore job: {e}")
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
                        logger.info(f"[NightlySubs] Rinnovo dovuto per {chat_id}: {sub_name} (€{amount})")
                        
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
                        try:
                            new_next = get_next_billing_date(today, sub_type)
                            next_str = new_next.strftime('%d/%m/%Y') if new_next else "N/D"
                            
                            await app.bot.send_message(
                                chat_id=int(chat_id),
                                text=f"✅ *Rinnovo automatico effettuato!*\n\n"
                                     f"Ho registrato la spesa per *{sub_name}* (€{amount:,.2f}).\n"
                                     f"Prossimo rinnovo previsto: {next_str}",
                                parse_mode=ParseMode.MARKDOWN
                            )
                        except Exception as n_err:
                            logger.error(f"[NightlySubs] Errore notifica a {chat_id}: {n_err}")
                        
                        # 4. Aggiorna la dashboard pinnata
                        await _refresh_pinned_dashboard(app.bot, chat_id)
                        
            except Exception as e:
                logger.error(f"[NightlySubs] Errore processing abbonamenti per {chat_id}: {e}")
            
            await asyncio.sleep(0.5)

    future = asyncio.run_coroutine_threadsafe(_process_subs(), loop)
    try:
        future.result(timeout=600)
    except Exception as e:
        logger.error(f"[NightlySubs] Errore job: {e}")
        raise


def _nightly_retention_cleanup() -> None:
    """Job APScheduler alle 03:10 — rimuove OAuth session scadute e chat_messages oltre 90gg.

    Applica le retention policy dichiarate (Art. 5.1(e) GDPR) che altrimenti
    restano solo teoriche: i due metodi esistevano già ma nessun job li invocava.
    """
    try:
        deleted_oauth = _user_store.cleanup_expired_oauth_sessions()
        deleted_chats = _user_store.cleanup_old_chat_messages(days=90)
        deleted_jobs = _user_store.cleanup_old_job_runs(days=90)
        logger.info(
            "[NightlyRetention] OAuth sessions rimosse: %d, chat_messages rimossi: %d, "
            "job_runs rimossi: %d",
            deleted_oauth, deleted_chats, deleted_jobs,
        )
    except Exception as e:
        logger.error(f"[NightlyRetention] Errore job: {e}")


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
    scheduler.add_job(_trial_expiry_job, 'cron', hour=4, minute=0, args=[app, loop], id='trial_expiry_job')
    scheduler.add_job(_daily_dashboard_job, 'cron', hour=8, minute=0, args=[app, loop], id='daily_dashboard_job')
    scheduler.add_job(_weekly_plan_job, 'cron', day_of_week='mon', hour=8, minute=5, args=[app, loop], id='weekly_plan_job')
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
        "<i>D.Lgs. 101/2018 — capacità contrattuale</i>"
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
    keyboard = _ob_keyboard([
        ("💪 Sport / Palestra", "ob_hob_palestra"),
        ("📺 Streaming / Gaming", "ob_hob_streaming"),
        ("✈️ Viaggi", "ob_hob_viaggi"),
        ("🎭 Cinema / Cultura", "ob_hob_cultura"),
    ], skip=True)
    await query.edit_message_text(
        f"{_ob_progress(6)}🎮 <b>Hobby e interessi?</b>\n<i>Tocca più opzioni poi 'Avanti' (opzionale)</i>",
        parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💪 Palestra", callback_data="ob_hob_palestra"),
             InlineKeyboardButton("📺 Streaming", callback_data="ob_hob_streaming")],
            [InlineKeyboardButton("✈️ Viaggi", callback_data="ob_hob_viaggi"),
             InlineKeyboardButton("🎭 Cinema", callback_data="ob_hob_cultura")],
            [InlineKeyboardButton("✅ Avanti →", callback_data="ob_hob_done")],
            [InlineKeyboardButton("↩ Indietro", callback_data="ob_back"),
             InlineKeyboardButton("⏭ Salta", callback_data="ob_skip")],
        ]),
    )
    context.user_data.setdefault("hobbies_selected", [])
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

    webapp_url = f"{Config.WEBAPP_BASE_URL}/chat?tour=1&demo=1"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✨ Scopri Expensum", web_app=WebAppInfo(url=webapp_url))],
    ])
    await query.edit_message_text(
        "🎉 <b>Tutto pronto!</b>\n\n"
        "Ho preparato <b>30 giorni di dati di esempio</b> così puoi vedere subito "
        "come funzionano analytics, report e tutto il resto.\n\n"
        "Apri la web app — ti guiderò in un tour rapido, poi puliamo i dati demo "
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
    except EnvironmentError as e:
        logger.error(str(e))
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
    app.add_handler(CommandHandler("login", cmd_login))
    app.add_handler(CommandHandler("modify", cmd_modify))
    app.add_handler(CommandHandler("trasferimento", cmd_trasferimento))
    app.add_handler(CommandHandler("impostazioni", cmd_impostazioni_menu))
    app.add_handler(CommandHandler("privacy", cmd_privacy))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("feedback", cmd_feedback))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("piano", cmd_piano))
    app.add_handler(CommandHandler("weekly_report", cmd_weekly_report))
    app.add_handler(CommandHandler("weekly_plan", cmd_weekly_plan))
    app.add_handler(CommandHandler("monthly_report", cmd_monthly_report))
    app.add_handler(CommandHandler("monthly_plan", cmd_monthly_plan))
    app.add_handler(CallbackQueryHandler(handle_impostazioni_menu_callback, pattern="^(imp_menu_|privacy_)"))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE & ~filters.COMMAND, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_photos))

    # Registra l'error handler globale — cattura tutte le eccezioni non gestite
    app.add_error_handler(handle_error)

    if args.webhook:
        # Modalità webhook
        logger.info(f"🌐 Avvio bot in modalità WEBHOOK su {args.webhook}")
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
