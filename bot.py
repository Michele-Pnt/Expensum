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

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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
WAITING_INVITE_CODE, WAITING_API_KEY, WAITING_EXPENSE_DB, WAITING_INCOME_DB = range(4)

# Cache globali (inizializzate al primo messaggio)
_notion: NotionFinanceClient | None = None
_parser: ExpenseParser | None = None

# Inizializziamo il database utenti (usando l'URL che abbiamo messo in Config)
_user_store = UserStore(db_url=Config.DATABASE_URL)

# Questi dizionari terranno in memoria i client degli utenti attivi
# Formato: { "chat_id": OggettoClient }
_notion_clients: dict[str, NotionFinanceClient] = {}
_parsers: dict[str, ExpenseParser] = {}

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
    client = NotionFinanceClient(
        api_key=user.notion_api_key,
        expense_db_id=user.expense_db_id,
        income_db_id=user.income_db_id,
        categories_db_id=user.categories_db_id,
        monthly_balance_db_id=user.monthly_balance_db_id,
        accounts_db_id=user.accounts_db_id
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


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler per /start — messaggio di benvenuto."""
    if not _is_authorized(update):
        await update.message.reply_text(
            "👋 *Benvenuto!*\n\n"
            "Questo bot è privato. Per usarlo, devi prima configurare le tue credenziali Notion.\n\n"
            "Digita /registra per iniziare! 🚀",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    await update.message.reply_text(
        "👋 *Bentornato!* Sono il tuo assistente finanziario.\n\n"
        "Scrivimi una spesa in modo naturale, come a un amico:\n"
        "• _\"ieri pizza con amici 25€\"_\n"
        "• _\"ho speso 67 euro al supermercato\"_\n"
        "• _\"netflix 13.99\"_\n\n"
        "Io la interpreto e la salvo su Notion per te! 🚀",
        parse_mode=ParseMode.MARKDOWN,
    )

async def cmd_registra(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """PUNTO DI INIZIO: Chiede il codice invito."""
    await update.message.reply_text(
        "🔐 *Accesso Riservato*\n\n"
        "Questo bot è privato. Inserisci il tuo **Codice d'Invito** per procedere:",
        parse_mode=ParseMode.MARKDOWN
    )
    return WAITING_INVITE_CODE

async def process_invite_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fase 1: Verifica il codice e chiede la API Key."""
    text = update.message.text.strip()
    if text != Config.INVITE_CODE:
        await update.message.reply_text("❌ Codice errato! Riprova o scrivi /cancel.")
        return WAITING_INVITE_CODE
        
    await update.message.reply_text("✅ Codice accettato! Ora incolla la tua **Notion API Key**:")
    return WAITING_API_KEY

async def process_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fase 2: Riceve la API Key e chiede l'ID database Spese."""
    api_key = update.message.text.strip()
    if not api_key.startswith("ntn_"):
        await update.message.reply_text("⚠️ Chiave non valida. Inserisci la tua Notion API Key (inizia con `ntn_`):")
        return WAITING_API_KEY
        
    context.user_data["notion_api_key"] = api_key
    await update.message.reply_text("Ottimo! Ora incolla l'**ID del Database Spese** (Expense):")
    return WAITING_EXPENSE_DB

async def process_expense_db(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fase 3: Riceve ID Spese e chiede ID Entrate."""
    context.user_data["expense_db_id"] = update.message.text.strip()
    await update.message.reply_text("Ricevuto. Infine, incolla l'**ID del Database Entrate** (Income):")
    return WAITING_INCOME_DB

async def process_income_db(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fase Finale: Salva tutto nel database utenti."""
    income_id = update.message.text.strip()
    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username
    
    _user_store.add_user(
        chat_id=chat_id,
        username=username,
        notion_api_key=context.user_data["notion_api_key"],
        expense_db_id=context.user_data["expense_db_id"],
        income_db_id=income_id
    )
    
    context.user_data.clear()
    logger.info(f"[User {chat_id}] Registrazione completata.")
    await update.message.reply_text("🎊 *Configurazione completata!* Ora puoi usare il bot per tracciare le tue finanze.")
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
    
    logger.info(f"[User {chat_id}] Risultato parser: {result['type']} - {result['name']} (€{result['amount']})")

    if result is None:
        await update.message.reply_text(
            "🤔 Non ho capito che spesa intendi. "
            "Prova a scrivermi qualcosa come:\n"
            "• _\"Ho speso 45 euro di spesa\"_\n"
            "• _\"Ho ricevuto 20 euro di bonifico\"_",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

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
            f"❌ Errore nel salvataggio su Notion:\n`{str(e)[:200]}`",
            parse_mode=ParseMode.MARKDOWN,
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
        
        await query.edit_message_text("🏦 Da quale conto hai pagato?", reply_markup=InlineKeyboardMarkup(keyboard))
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
    
    # 1. Registrazione (deve stare prima per gestire i messaggi di testo dedicati)
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("registra", cmd_registra)],
        states={
            WAITING_INVITE_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_invite_code)],
            WAITING_API_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_api_key)],
            WAITING_EXPENSE_DB: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_expense_db)],
            WAITING_INCOME_DB: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_income_db)],
        },
        fallbacks=[CommandHandler("cancel", cancel_registra)],
    )
    app.add_handler(conv_handler)

    # 2. Altri comandi e messaggi
    app.add_handler(CommandHandler("start", cmd_start))
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
