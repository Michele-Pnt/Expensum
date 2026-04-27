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
import logging
import sys
import json
import time
import threading
from cachetools import TTLCache
from apscheduler.schedulers.background import BackgroundScheduler

from src.billing_utils import get_next_billing_date
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.constants import ParseMode
from telegram.request import HTTPXRequest
from google import genai
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
from src.user_store import UserStore
from src.category_sync import refresh_category_averages
from src.dashboard_message import build_dashboard_text

logger = logging.getLogger("financial_agent.bot")

# ---------------------------------------------------------------------------
# Stati della conversazione
# ---------------------------------------------------------------------------
WAITING_INVITE_CODE, WAITING_API_KEY, WAITING_EXPENSE_DB, WAITING_INCOME_DB, WAITING_CATEGORIES_DB, WAITING_MONTHLY_DB, WAITING_ACCOUNTS_DB = range(7)
LOGIN_WAITING_EMAIL, LOGIN_WAITING_PASSWORD = range(7, 9)

# ---------------------------------------------------------------------------
# Stati della inizializzazione del template
# ---------------------------------------------------------------------------
SETUP_STATUS_WAIT_ACCOUNTS = "WAIT_ACCOUNTS"
SETUP_STATUS_DONE = "DONE"


# Cache globali (inizializzate al primo messaggio)
_notion: NotionFinanceClient | None = None
_parser: ExpenseParser | None = None

# Inizializziamo il database utenti (usando l'URL che abbiamo messo in Config)
_user_store = UserStore(db_url=Config.DATABASE_URL)

# Cache client storage: TTL 30 min, max 200 utenti (VPS Hetzner CX23 — 4GB RAM)
_storage_clients: TTLCache = TTLCache(maxsize=200, ttl=1800)


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
          return _storage_clients[chat_id]
                                                                                                                                                               
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
    return user is not None

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
                f"Usa /piano per fare l'upgrade e continuare a usare Traky, o attendi il reset mensile.", 
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                "🛑 *Limite sistema raggiunto*\n"
                "Hai superato il limite di sicurezza del piano PRO. Contatta l'assistenza.", 
                parse_mode=ParseMode.MARKDOWN
            )
        return False
        
    # Consuma i token
    res = _user_store.consume_tokens(chat_id, cost)
    
    # Notifiche soft
    if res["alert"] == "warning_90":
        await update.message.reply_text(
            "⚠️ *Attenzione:* hai consumato il 90% dei token mensili. Usa /piano per maggiori info.", 
            parse_mode=ParseMode.MARKDOWN
        )
    elif res["alert"] == "warning_70":
        await update.message.reply_text(
            "ℹ️ *Info:* hai consumato il 70% dei token mensili.", 
            parse_mode=ParseMode.MARKDOWN
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
        await update.message.reply_text(
            "⚠️ *Non sei ancora registrato!*\nUsa /registrati per configurare il bot.",
            parse_mode=ParseMode.MARKDOWN,
        )
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
        await update.message.reply_text(
            "⚠️ *Non sei ancora registrato!*\nUsa /registrati per configurare il bot.",
            parse_mode=ParseMode.MARKDOWN,
        )
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
            spending_by_cat[cat] = spending_by_cat.get(cat, 0.0) + tx.get("amount", 0.0)

        # Recupera le medie storiche dal DB locale
        cat_averages = _user_store.get_user_categories_with_averages(chat_id)
        avg_map = {c["name"]: c["average"] for c in cat_averages}

        # Unisci spese attuali + medie
        all_cat_names = set(spending_by_cat.keys()) | set(avg_map.keys())
        categories_spending = []
        for cat_name in sorted(all_cat_names):
            categories_spending.append({
                "name": cat_name,
                "spent_this_month": spending_by_cat.get(cat_name, 0.0),
                "average": avg_map.get(cat_name, 0.0),
            })

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
    rimanenti = plan["tokens_remaining"]
    totali = plan["tokens_total"]
    reset = plan["tokens_reset_at"].strftime("%d/%m/%Y")
    percent = round(((totali - rimanenti) / totali) * 100) if totali > 0 else 0
    
    testo = (
        f"📊 *Il tuo Piano: {tipo}*\n\n"
        f"🔹 Token utilizzati: {percent}%\n"
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
        testo += "Grazie per essere un utente PRO! Hai accesso a tutte le funzionalità premium di Traky 🚀"
        
    await update.message.reply_text(testo, parse_mode=ParseMode.MARKDOWN)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler per /start — messaggio di benvenuto."""
    if not _is_authorized(update):
        await update.message.reply_text(
            "👋 *Benvenuto!*\n\n"
            "Sono **Moneo** 🐷, la tua mascotte e assistente finanziario.\n"
            "Visto che sono molto geloso dei miei file, questo sistema è privato. Per poterti aiutare, devi prima configurare le tue credenziali Notion.\n\n"
            "Digita /registrati per creare un account, o /login se ne hai già uno! 🚀",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    await update.message.reply_text(
        "👋 *Bentornato!* Sono **Moneo** 🐷, il tuo amichevole assistente finanziario.\n\n"
        "Dimmi, cosa hai comprato di bello?\n"
        "Scrivimi una spesa in modo naturale:\n"
        "• _\"ieri ho sganciato 25€ per la pizza\"_\n"
        "• _\"spesa al super per 67 euro\"_\n"
        "• _\"netflix 13.99\"_\n\n"
        "Ci penso io a fare i conti e salvarti tutto su Notion! 🚀",
        parse_mode=ParseMode.MARKDOWN,
    )

async def cmd_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler per /feedback — raccoglie e salva i suggerimenti/problemi dell'utente."""
    if not _is_authorized(update):
        await update.message.reply_text("⚠️ *Non sei ancora registrato!*\nUsa /registrati per configurare il bot.", parse_mode=ParseMode.MARKDOWN)
        return

    chat_id = str(update.effective_chat.id)
    # Rimuove il comando dal testo
    text = update.message.text.split("/feedback", 1)[-1].strip()
    
    if not text:
        await update.message.reply_text("Esempio di utilizzo:\n`/feedback Il bot ha sbagliato categoria per l'Esselunga`", parse_mode=ParseMode.MARKDOWN)
        return
        
    _user_store.save_feedback(chat_id, text)
    await update.message.reply_text("✅ *Grazie per il tuo feedback!*\n\nIl tuo commento è stato salvato e lo terremo in considerazione per le prossime versioni di Moneo ✨", parse_mode=ParseMode.MARKDOWN)

async def cmd_registra(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fornisce due opzioni di registrazione: OAuth Notion oppure backend PostgreSQL interno."""
    chat_id = str(update.effective_chat.id)

    if _user_store.get_user(chat_id):
        await update.message.reply_text(
            "⚠️ *Hai già un account attivo!*\n\n"
            "Usa /status per vedere la tua dashboard, o /elimina\\_account se vuoi cancellare tutto e ripartire da zero.",
            parse_mode=ParseMode.MARKDOWN
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
        "🐘 *PostgreSQL* — salva i dati nel database interno di Moneo, più veloce e senza rate limit.\n\n"
        "Puoi cambiare idea più avanti scrivendo al supporto. 🛡️",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )

async def cmd_elimina_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler per /elimina_account — chiede conferma prima di cancellare tutti i dati."""
    if not _is_authorized(update):
        await update.message.reply_text(
            "⚠️ *Non sei ancora registrato!*\nUsa /registrati per configurare il bot.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💀 Sì, elimina tutto", callback_data="delete_account_confirm")],
        [InlineKeyboardButton("❌ Annulla", callback_data="delete_account_cancel")],
    ])
    await update.message.reply_text(
        "⚠️ *Sei sicuro di voler eliminare il tuo account?*\n\n"
        "Questa operazione è *irreversibile* e cancellerà:\n"
        "• Tutti i tuoi dati finanziari (spese, entrate, conti, abbonamenti)\n"
        "• Le tue categorie e impostazioni\n"
        "• Il tuo account Moneo\n\n"
        "I dati sul tuo workspace Notion *non* vengono toccati.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )


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
        notion_api_key=context.user_data["notion_api_key"],
        expense_db_id=context.user_data["expense_db_id"],
        income_db_id=context.user_data["income_db_id"],
        categories_db_id=context.user_data["categories_db_id"],
        monthly_balance_db_id=context.user_data["monthly_balance_db_id"],
        accounts_db_id=update.message.text.strip(),
    )

    context.user_data.clear()
    logger.info(f"[User {chat_id}] Registrazione completata con tutti i DB.")
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
# /login — Accesso con email e password
# ---------------------------------------------------------------------------

async def cmd_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Avvia il flusso di login: chiede l'email."""
    chat_id = str(update.effective_chat.id)
    user = _user_store.get_user(chat_id)
    if user and user.email:
        await update.message.reply_text(
            "✅ Sei già autenticato come *" + (user.email or chat_id) + "*.\n",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END
    await update.message.reply_text(
        "🔑 *Accedi a Moneo*\n\nInserisci la tua *email*:",
        parse_mode=ParseMode.MARKDOWN,
    )
    return LOGIN_WAITING_EMAIL


async def login_receive_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Riceve l'email e chiede la password."""
    context.user_data["login_email"] = update.message.text.strip()
    await update.message.reply_text("🔒 Inserisci la tua *password*:", parse_mode=ParseMode.MARKDOWN)
    return LOGIN_WAITING_PASSWORD


async def login_receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Verifica le credenziali e completa il login."""
    email = context.user_data.pop("login_email", "")
    password = update.message.text
    context.user_data.clear()

    # Elimina subito il messaggio con la password per sicurezza
    try:
        await update.message.delete()
    except Exception:
        pass

    user = _user_store.verify_password(email, password)
    if not user:
        await update.message.reply_text(
            "❌ Email o password errati. Riprova con /login.",
        )
        return ConversationHandler.END

    # Aggiorna il chat_id se l'utente accede da un account diverso
    current_chat_id = str(update.effective_chat.id)
    if user.chat_id != current_chat_id:
        _user_store.add_user(chat_id=current_chat_id, email=user.email, password_hash=user.password_hash,
                             storage_backend=user.storage_backend)

    reg_token = _user_store.create_oauth_session(user.chat_id)
    base_url = Config.WEBAPP_BASE_URL
    setup_url = f"{base_url}/setup?reg_token={reg_token}"

    await update.message.reply_text(
        f"✅ *Login effettuato!* Benvenuto, {user.email}.\n\n"
        f"Accedi alla tua area personale:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📂 Apri Moneo", url=setup_url)]]),
    )
    return ConversationHandler.END


async def cancel_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Annulla il login."""
    context.user_data.clear()
    await update.message.reply_text("❌ Login annullato.")
    return ConversationHandler.END

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler per messaggi di testo — parsing spesa con LLM."""
    
    chat_id = str(update.effective_chat.id) #recupero id chat utente che ha fatto richiesta

    if not _is_authorized(update):
        await update.message.reply_text("⚠️ *Non sei ancora registrato!*\nUsa /registrati per configurare il bot.", parse_mode=ParseMode.MARKDOWN)
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

    logger.info(f"[User {chat_id}] Messaggio ricevuto: '{message_text}'")
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
        from datetime import datetime
        dt = datetime.fromisoformat(data["date"])
        date_str = dt.strftime("%d/%m/%Y")
        summary = (
            f"📝 *Nuova spesa riconosciuta:*\n\n"
            f"📅 Data: *{date_str}*\n"
            f"💰 Importo: *€{data['amount']:.2f}*\n"
            f"📂 Categoria: *{data['category'] or 'Non determinata'}*\n"
            f"📝 Descrizione: *{data['name']}*"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Conferma", callback_data="confirm"),
                InlineKeyboardButton("❌ Annulla", callback_data="cancel"),
            ]
        ])
        await update.message.reply_text(summary, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
        return

    # Passa la palla alla nuova funzione condivisa
    await _process_expense_text(update, context, message_text, chat_id)

async def _process_expense_text(update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str, chat_id: str) -> None:
    # 🛡️ DIFESA 3: Wrapping sicuro dell'input — isoliamo il contenuto utente dal prompt di sistema
    # Questo rende molto più difficile la Prompt Injection
    safe_input = f"[INIZIO INPUT UTENTE]\n{message_text}\n[FINE INPUT UTENTE]"

    # 1. Recuperiamo il parser specifico per l'utente
    parser = _get_parser(chat_id)
    # 2. Parsa con LLM (input sanificato)
    result = parser.parse(safe_input)

    if result is None:
        _user_store.increment_ai_metrics(success=False)
        await update.message.reply_text(
            "⚠️ Non sono riuscito ad elaborare il messaggio in questo momento.\n"
            "Il servizio AI è temporaneamente sovraccarico — riprova tra qualche secondo! 🔄",
        )
        return

    logger.info(f"[User {chat_id}] Risultato parser: {result['type']} - {result['name']} (€{result['amount']})")

    # Salva i dati nel contesto utente (evita il limite 64 byte di callback_data)
    context.user_data["pending_expense"] = {
        "type": result["type"],
        "date": result["date"].isoformat(),
        "amount": result["amount"],
        "category": result["category"],
        "income_type": result.get("income_type"),
        "name": result["name"],
    }
    
    # Se manca l'importo, chiedi chiarimento e metti in attesa
    if result["amount"] is None:
        _user_store.increment_ai_metrics(success=False)
        context.user_data["waiting_for_amount"] = True
        cat_info = f" ({result['category']})" if result["category"] else ""
        await update.message.reply_text(
            f"📝 Non ho Capito l'importo. Prova a ridirmelo, grazie!❤️\n",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    date_str = result["date"].strftime("%d/%m/%Y")

    # Scegliamo l'etichetta giusta in base al tipo
    if result.get("type") == "income":
        # Se abbiamo già tutto, formatta l'entrata
        
        income_type_label = result.get("income_type") or "Non determinato"
        summary = (
            f"📝 *Nuova Entrata riconosciuta:*\n\n"
            f"📅 Data: *{date_str}*\n"
            f"💰 Importo: *€{result['amount']:.2f}*\n"
            f"🏷️ Tipo: *{income_type_label}*\n"
            f"📝 Descrizione: *{result['name']}*"
        )

    else:
        # Se abbiamo già tutto, formatta la spesa
        summary = (
            f"📝 *Nuova spesa riconosciuta:*\n\n"
            f"📅 Data: *{date_str}*\n"
            f"💰 Importo: *€{result['amount']:.2f}*\n"
            f"📂 Categoria: *{result['category'] or 'Non determinata'}*\n"
            f"📝 Descrizione: *{result['name']}*"
        )

    # Bottoni inline
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Conferma", callback_data="confirm"),
            InlineKeyboardButton("❌ Annulla", callback_data="cancel"),
        ]
    ])

    await update.message.reply_text(summary, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler per messaggi vocali — trascrizione e parsing spesa con LLM."""

    chat_id = str(update.effective_chat.id) #recupero id chat utente che ha fatto richiesta


    if not _is_authorized(update):
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

        client = genai.Client(api_key=Config.GEMINI_API_KEY)
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
        logger.info(f"[User {chat_id}] Trascrizione Audio: {message_trascribed}")
        _user_store.increment_usage(chat_id, "voice")
        await update.message.reply_text("🎙️ Ho ascoltato! Sto elaborando...")
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

        client = genai.Client(api_key=Config.GEMINI_API_KEY)
        with open(temp_path, "rb") as f:
            photo_bytes = f.read()

        photo_part = types.Part.from_bytes(data=photo_bytes, mime_type="image/jpeg")
        response = client.models.generate_content(
            model=Config.GEMINI_MODEL,
            contents=[
                "Tu sei un parser di spese. Guarda questa foto (può essere scontrino o notifica), "
                "estrai l'importo esatto, la data e il commerciante, e riassumi tutto in una singola "
                "frase di testo come se fossi io a dirlo",
                photo_part
            ]
        )
        message_trascribed = response.text.strip()
        logger.info(f"[User {chat_id}] Analisi Foto: {message_trascribed}")
        _user_store.increment_usage(chat_id, "photo")
        await update.message.reply_text("📸 Foto analizzata! Sto elaborando...")
        await _process_expense_text(update, context, message_trascribed, chat_id)

    finally:
        # 🛡️ Auto-cleanup: il file viene cancellato SEMPRE, anche se c'è un errore
        if os.path.exists(temp_path):
            os.remove(temp_path)
            logger.info(f"[User {chat_id}] File temporaneo eliminato: {temp_path}")

async def _save_to_notion(query, context, chat_id: str, account_id: str | None = None):
    data = context.user_data.pop("pending_expense", None)
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
                f"✅ *Entrata salvata su Notion!*\n\n"
                f"📅 {date_str} — *€{data['amount']:.2f}* — {data['name']}",
                parse_mode=ParseMode.MARKDOWN,
            )
            logger.info(f"[User {chat_id}] Entrata salvata: {data['name']} €{data['amount']:.2f}")
        else:
            storage.create_expense(
                expense_date=date,
                amount=data["amount"],
                name=data["name"],
                category_name=data.get("category"),
                account_id=account_id
            )
            date_str = date.strftime("%d/%m/%Y")
            await query.edit_message_text(
                f"✅ *Spesa salvata su Notion!*\n\n"
                f"📅 {date_str} — *€{data['amount']:.2f}* — {data['name']}",
                parse_mode=ParseMode.MARKDOWN,
            )
            logger.info(f"Spesa salvata: {data['name']} €{data['amount']:.2f}")

        # Aggiorna la dashboard pinnata in background (se esiste)
        try:
            _user_store.increment_ai_metrics(success=True)
            await _refresh_pinned_dashboard(query._bot, chat_id)
        except Exception as e:
            logger.warning(f"[User {chat_id}] Errore refresh dashboard post-save: {e}")

    except Exception as e:
        logger.error(f"Errore salvataggio Notion: {e}")
        await query.edit_message_text(
            "⚠️ Non sono riuscito a salvare su Notion in questo momento.\n"
            "Riprova tra qualche secondo oppure contatta il supporto se il problema persiste.",
        )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler per i bottoni inline (conferma/annulla/conti)."""
    query = update.callback_query
    await query.answer()

    chat_id = str(update.effective_chat.id)

    if not _is_authorized(update):
        return

    if query.data == "delete_account_confirm":
        backend = _user_store.delete_user_completely(chat_id)
        logger.info(f"[User {chat_id}] Account eliminato (backend: {backend})")
        await query.edit_message_text(
            "✅ Account eliminato. Tutti i tuoi dati sono stati cancellati.\n\nCiao! 👋"
        )
        return

    if query.data == "delete_account_cancel":
        await query.edit_message_text("❌ Eliminazione annullata. Il tuo account è al sicuro.")
        return

    if query.data == "cancel":
        context.user_data.pop("pending_expense", None)
        context.user_data.pop("waiting_for_amount", None)
        await query.edit_message_text("❌ Operazione annullata.")
        return

    if query.data == "confirm":
        data = context.user_data.get("pending_expense")
        if not data:
            await query.edit_message_text("⚠️ Nessuna spesa in sospeso.")
            return

        # Recupera accounts da Notion per far selezionare il conto
        try:
            storage = _get_storage(chat_id)
            accounts = storage.fetch_accounts()
        except Exception as e:
            logger.error(f"[User {chat_id}] Errore fetch accounts: {e}")
            accounts = []
            
        if not accounts:
            # Fallback salva subito
            await _save_to_notion(query, context, chat_id)
            return

        # Disegna bottoni
        keyboard = []
        for acc in accounts:
            bal = acc.get('balance', acc.get('current_balance', 0.0))
            keyboard.append([InlineKeyboardButton(f"🏦 {acc['name']} (€{bal:.2f})", callback_data=f"account:{acc['id']}")])
        keyboard.append([InlineKeyboardButton("❌ Annulla", callback_data="cancel")])
        
        pending = context.user_data.get("pending_expense", {})
        question = "🏦 Su quale conto è arrivata l'entrata?" if pending.get("type") == "income" else "🏦 Da quale conto hai pagato?"
        await query.edit_message_text(question, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if query.data.startswith("account:"):
        account_id = query.data.split(":", 1)[1]
        await _save_to_notion(query, context, chat_id, account_id=account_id)
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

def _nightly_category_sync() -> None:
    """Job APScheduler alle 03:00 — aggiorna medie categorie per tutti gli utenti attivi.

    Sequenziale con 200ms di sleep tra utenti per non saturare CPU/rete su Hetzner CX23.
    Ogni utente Notion usa il proprio OAuth token → bucket rate limit separato.
    """
    logger.info("[NightlySync] Avvio sincronizzazione notturna categorie.")

    # --- Utenti Notion ---
    try:
        notion_users = _user_store.get_active_notion_users()
        logger.info("[NightlySync] Utenti Notion: %d", len(notion_users))
        for user in notion_users:
            try:
                db_schemas_raw = _user_store.get_database_schemas(user.chat_id)
                schemas = {}
                for data in db_schemas_raw.values():
                    # get_database_schemas ritorna {db_key: {database_id, properties, mapped}}
                    pass
                notion_client = NotionFinanceClient(
                    api_key=user.notion_access_token,
                    categories_db_id=user.categories_db_id,
                )
                refresh_category_averages(user.chat_id, _user_store, notion_client=notion_client)
            except Exception as e:
                logger.error("[NightlySync] Errore Notion per %s: %s", user.chat_id, e)
            time.sleep(0.2)
    except Exception as e:
        logger.error("[NightlySync] Errore fetch utenti Notion: %s", e)

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


def _daily_dashboard_job(app: Application) -> None:
    """Job APScheduler alle 08:00 — invia una nuova dashboard giornaliera per ogni utente attivo.

    Per ogni utente:
    1. Costruisce il testo dashboard aggiornato
    2. Invia un nuovo messaggio
    3. Unpin il vecchio, pin il nuovo
    4. Salva il nuovo msg_id
    """
    import asyncio

    logger.info("[DailyDashboard] Avvio invio dashboard giornaliere.")

    async def _send_dashboards():
        bot = app.bot
        # Recupera tutti gli utenti attivi (sia Notion che Postgres)
        notion_users = _user_store.get_active_notion_users()
        pg_users = _user_store.get_active_postgres_users()
        all_users = list(notion_users) + list(pg_users)

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
                sent += 1
                logger.info(f"[DailyDashboard] Dashboard inviata a {chat_id}")

            except Exception as e:
                logger.error(f"[DailyDashboard] Errore per {chat_id}: {e}")

            time.sleep(0.5)  # Rate limit tra utenti

        logger.info(f"[DailyDashboard] Completato: {sent}/{len(all_users)} dashboard inviate.")

    # APScheduler gira in un thread separato — eseguiamo la coroutine
    # nell'event loop dell'applicazione Telegram
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_send_dashboards())
        else:
            loop.run_until_complete(_send_dashboards())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_send_dashboards())


def _nightly_subscription_job(app: Application) -> None:
    """Job APScheduler alle 03:00 — processa abbonamenti automatici per utenti Pro."""
    import asyncio
    import time
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
                    amount = sub.get("amount", 0.0)
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
                        await update_dashboard_if_pinned(chat_id, app.bot)
                        
            except Exception as e:
                logger.error(f"[NightlySubs] Errore processing abbonamenti per {chat_id}: {e}")
            
            time.sleep(0.5) # Rate limit tra utenti
            
    # Eseguo nell'event loop dell'applicazione
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_process_subs())
        else:
            loop.run_until_complete(_process_subs())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_process_subs())


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
    app = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).request(HTTPXRequest(http_version="1.1")).build()

    # --- Handlers ---
    
    login_conv = ConversationHandler(
        entry_points=[CommandHandler("login", cmd_login)],
        states={
            LOGIN_WAITING_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_receive_email)],
            LOGIN_WAITING_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_receive_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel_login)],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("registrati", cmd_registra))
    app.add_handler(CommandHandler("elimina_account", cmd_elimina_account))
    app.add_handler(CommandHandler("modify", cmd_modify))
    app.add_handler(CommandHandler("feedback", cmd_feedback))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("piano", cmd_piano))
    app.add_handler(login_conv)
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE & ~filters.COMMAND, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_photos))

    # Registra l'error handler globale — cattura tutte le eccezioni non gestite
    app.add_error_handler(handle_error)

    # Job notturno: aggiornamento medie categorie alle 03:00
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(_nightly_category_sync, 'cron', hour=3, minute=0)
    scheduler.add_job(_nightly_subscription_job, 'cron', hour=3, minute=5, args=[app])
    scheduler.add_job(_daily_dashboard_job, 'cron', hour=8, minute=0, args=[app])
    scheduler.start()
    logger.info("⏰ Scheduler notturno avviato (sync categorie alle 03:00).")

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
