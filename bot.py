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

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.constants import ParseMode
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
from src.rate_limiter import is_rate_limited
from src.user_store import UserStore

logger = logging.getLogger("financial_agent.bot")

# ---------------------------------------------------------------------------
# Stati della conversazione
# ---------------------------------------------------------------------------
WAITING_INVITE_CODE, WAITING_API_KEY, WAITING_EXPENSE_DB, WAITING_INCOME_DB, WAITING_CATEGORIES_DB, WAITING_MONTHLY_DB, WAITING_ACCOUNTS_DB = range(7)

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

# Questi dizionari terranno in memoria i client degli utenti attivi
# Formato: { "chat_id": OggettoClient }
_notion_clients: dict[str, NotionFinanceClient] = {}
_parsers: dict[str, ExpenseParser] = {}


def _safe_json_load(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else None
    except Exception:
        return None

def _get_notion(chat_id: str) -> NotionFinanceClient:
    """Ritorna il client Notion specifico per l'utente, creandolo se manca."""
    chat_id = str(chat_id)  # Convertiamo in stringa per sicurezza (le chiavi dei dizionari sono stringhe)

    # 1. Se abbiamo già il client in memoria, restituiamolo subito 
    if chat_id in _notion_clients:
        return _notion_clients[chat_id]
    
    # 2. Se non c'è, dobbiamo andare a chiederlo al database
    user = _user_store.get_user(chat_id)
    if not user:
        raise ValueError(f"Utente {chat_id} non autorizzato, devi registrati per poter accedere al servizio")

    # 3. Creiamo un NUOVO client personalizzato con le chiavi di quell'utente
    # Fase 2: Preferiamo il token OAuth se presente, altrimenti usiamo la vecchia API key
    api_key = user.notion_access_token or user.notion_api_key
    
    # Carichiamo gli schemi dalla nuova tabella dedicata
    stored_schemas = _user_store.get_database_schemas(chat_id)
    
    # Prepariamo il dizionario dei db_schemas per il client, effettuando il parsing JSON
    db_schemas = {}
    for db_key, data in stored_schemas.items():
        db_schemas[db_key] = {
            "database_id": data["database_id"],
            "properties": _safe_json_load(data["properties"]),
            "mapped": _safe_json_load(data["mapped"])
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
        db_schemas=db_schemas,
    )

    #salviamo il client
    _notion_clients[chat_id] = client
    return client
    

def _get_parser(chat_id: str) -> ExpenseParser:
    """Ritorna il parser con categorie da Notion specifico per l'utente, creandolo se manca."""
    chat_id = str(chat_id)  # Convertiamo in stringa per sicurezza (le chiavi dei dizionari sono stringhe)


    # 1. Se abbiamo già il client in memoria, restituiamolo subito 
    if chat_id in _parsers:
        return _parsers[chat_id]
    
    # 2. Creiamo un NUOVO parser personalizzato con le chiavi di quell'utente
    notion = _get_notion(chat_id)
    categories = notion.get_category_names()
    parser = ExpenseParser(categories=categories)
    #3. salvo il parser
    _parsers[chat_id] = parser
    logger.info(f"Parser inizializzato con {len(categories)} categorie: {categories}")
    return parser


def _is_authorized(update: Update) -> bool:
    """Verifica che il messaggio arrivi dall'utente autorizzato (presente nel database) e attivo."""
    if not update.effective_chat:
        return False
    
    chat_id = str(update.effective_chat.id)
    user = _user_store.get_user(chat_id)
    return user is not None


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

async def cmd_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fornisce il link alla Mini App per il setup dinamico."""
    if not _is_authorized(update):
        await update.message.reply_text(
            "⚠️ *Non sei ancora registrato!*\nUsa /registrati per configurare il bot.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    chat_id = str(update.effective_chat.id)
    user = _user_store.get_user(chat_id)
    if not _has_notion_template_binding(user):
        await update.message.reply_text(
            "⚠️ Prima completa /registrati (binding Notion template) e poi rilancia /setup."
        )
        return

    # Generiamo un token sicuro per la sessione di setup
    reg_token = _user_store.create_oauth_session(chat_id)
    
    # URL della Mini App (usiamo lo stesso host dell'OAuth)
    # NOTA: In produzione andrà configurata l'URL pubblica
    setup_url = f"https://bondless-charlena-bicolor.ngrok-free.dev/setup?reg_token={reg_token}"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛠️ Apri Setup Form", web_app=WebAppInfo(url=setup_url))]
    ])
    
    await update.message.reply_text(
        "🚀 *Configurazione Rapida Moneo*\n\n"
        "Ho preparato un form dinamico per impostare i tuoi **Conti**, le **Categorie** e gli **Abbonamenti** direttamente in questa chat.\n\n"
        "È il modo più veloce per iniziare! ✨",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )

# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler per /start — messaggio di benvenuto."""
    if not _is_authorized(update):
        await update.message.reply_text(
            "👋 *Benvenuto!*\n\n"
            "Sono **Moneo** 🐷, la tua mascotte e assistente finanziario.\n"
            "Visto che sono molto geloso dei miei file, questo sistema è privato. Per poterti aiutare, devi prima configurare le tue credenziali Notion.\n\n"
            "Digita /registra per iniziare! 🚀",
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
        await update.message.reply_text("⚠️ *Non sei ancora registrato!*\nUsa /registra per configurare il bot.", parse_mode=ParseMode.MARKDOWN)
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
    """Fornisce il link per il setup automatico tramite OAuth."""
    chat_id = str(update.effective_chat.id)
    
    # Fase 2 (Security Patch): Generiamo un token monouso sicuro
    # Invece di passare il chat_id nell'URL, passiamo un segreto temporaneo.
    reg_token = _user_store.create_oauth_session(chat_id)
    
    # URL del nostro server locale (Fase 2)
    # NOTA: In produzione qui useremo l'URL pubblico (es. https://traky.app/...)
    auth_url = f"https://bondless-charlena-bicolor.ngrok-free.dev/auth/notion?reg_token={reg_token}"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Connetti a Notion", url=auth_url)]
    ])
    
    await update.message.reply_text(
        "🚀 *Configurazione Rapida con Traky*\n\n"
        "Verrai reindirizzato su Notion per autorizzare Traky ad accedere (solo alle pagine che sceglierai tu!).\n\n"
        "È facile, veloce e sicuro. 🛡️",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )

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

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler per messaggi di testo — parsing spesa con LLM."""
    
    chat_id = str(update.effective_chat.id) #recupero id chat utente che ha fatto richiesta

    if not _is_authorized(update):
        await update.message.reply_text("⚠️ *Non sei ancora registrato!*\nUsa /registra per configurare il bot.", parse_mode=ParseMode.MARKDOWN)
        return

    # 🛡️ DIFESA 1: Rate Limiting (Anti-DoS)
    if is_rate_limited(chat_id, max_messages=Config.MAX_MESSAGES_PER_MINUTE):
        await update.message.reply_text("⏳ Stai inviando troppi messaggi. Aspetta un momento e riprova.")
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
        "name": result["name"],
    }
    
    # Se manca l'importo, chiedi chiarimento e metti in attesa
    if result["amount"] is None:
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
        
        summary = (
            f"📝 *Nuova Entrata riconosciuta:*\n\n"
            f"📅 Data: *{date_str}*\n"
            f"💰 Importo: *€{result['amount']:.2f}*\n"
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

        notion = _get_notion(chat_id)
        if data["type"] == "income":
            notion.create_income(
                income_date=date,
                amount=data["amount"],
                name=data["name"],
                account_id=account_id
            )
            date_str = date.strftime("%d/%m/%Y")
            await query.edit_message_text(
                f"✅ *Entrata salvata su Notion!*\n\n"
                f"📅 {date_str} — *€{data['amount']:.2f}* — {data['name']}",
                parse_mode=ParseMode.MARKDOWN,
            )
            logger.info(f"[User {chat_id}] Entrata salvata: {data['name']} €{data['amount']:.2f}")
        else:
            notion.create_expense(
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
            notion = _get_notion(chat_id)
            accounts = notion.fetch_accounts()
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
            keyboard.append([InlineKeyboardButton(f"🏦 {acc['name']} (€{acc['current_balance']:.2f})", callback_data=f"account:{acc['id']}")])
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
# Entry point
# ---------------------------------------------------------------------------

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
    app = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).build()

    # --- Handlers ---
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("registrati", cmd_registra))
    app.add_handler(CommandHandler("setup", cmd_setup))
    app.add_handler(CommandHandler("feedback", cmd_feedback))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE & ~filters.COMMAND, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_photos))

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
