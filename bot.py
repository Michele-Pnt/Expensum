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

from config import Config, setup_logging
from src.expense_parser import ExpenseParser
from src.notion_client import NotionExpenseClient

logger = logging.getLogger("financial_agent.bot")

# Cache globali (inizializzate al primo messaggio)
_notion: NotionExpenseClient | None = None
_parser: ExpenseParser | None = None

def _get_notion() -> NotionExpenseClient:
    """Lazy-init del client Notion."""
    global _notion
    if _notion is None:
        _notion = NotionExpenseClient()
    return _notion


def _get_parser() -> ExpenseParser:
    """Lazy-init del parser con categorie da Notion."""
    global _parser
    if _parser is None:
        notion = _get_notion()
        categories = notion.get_category_names()
        _parser = ExpenseParser(categories=categories)
        logger.info(f"Parser inizializzato con {len(categories)} categorie: {categories}")
    return _parser

def _is_authorized(update: Update) -> bool:
    """Verifica che il messaggio arrivi dall'utente autorizzato."""
    chat_id = str(update.effective_chat.id)
    return chat_id == Config.TELEGRAM_CHAT_ID


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler per /start — messaggio di benvenuto."""
    if not _is_authorized(update):
        return

    await update.message.reply_text(
        "👋 *Ciao!* Sono il tuo assistente finanziario.\n\n"
        "Scrivimi una spesa in modo naturale, come a un amico:\n"
        "• _\"ieri pizza con amici 25€\"_\n"
        "• _\"ho speso 67 euro al supermercato\"_\n"
        "• _\"netflix 13.99\"_\n\n"
        "Io la interpreto e la salvo su Notion per te! 🚀",
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler per messaggi di testo — parsing spesa con LLM."""
    if not _is_authorized(update):
        return

    message_text = update.message.text.strip()
    if not message_text:
        return

    logger.info(f"Messaggio ricevuto: '{message_text}'")
 
    # Mostra "sta scrivendo..."
    await update.message.chat.send_action("typing")

    # Controlla se siamo in attesa dell'importo
    if context.user_data.get("waiting_for_amount"):
        parser = _get_parser()
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
    await _process_expense_text(update, context, message_text)


async def _process_expense_text(update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str) -> None:
    # Parsa con LLM (nuovo messaggio)
    parser = _get_parser()
    result = parser.parse(message_text)

    if result is None:
        await update.message.reply_text(
            "🤔 Non ho capito che spesa intendi. "
            "Prova a scrivermi qualcosa come:\n"
            "• _\"45€ esselunga\"_\n"
            "• _\"ieri cena 80 euro\"_",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Salva i dati nel contesto utente (evita il limite 64 byte di callback_data)
    context.user_data["pending_expense"] = {
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
            f"📝 Ho capito: *{result['name']}*{cat_info}\n\n"
            "Ma quanto hai speso? Scrivimi l'importo.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Se abbiamo già tutto, formatta
    date_str = result["date"].strftime("%d/%m/%Y")
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
    if not _is_authorized(update):
        return

    file_info = await update.message.voice.get_file()

    await update.message.chat.send_action("record_voice")

    logger.info(f"Messaggio ricevuto: '{file_info}'")

    await file_info.download_to_drive("temp_voice.ogg")

    #Trascrizione via Gemini
    from google.genai import types
    
    #collegamento con la chiave API
    client = genai.Client(api_key=Config.GEMINI_API_KEY)
    
    #leggo file audio
    with open("temp_voice.ogg", "rb") as f:
        audio_bytes = f.read()

    #creo pacchetto audio compatibile con Gemini
    audio_part = types.Part.from_bytes(data=audio_bytes, mime_type="audio/ogg")

    #prompt per la trascrizione
    response=client.models.generate_content(
        model=Config.GEMINI_MODEL,
        contents=["Trascrivi esattamente e parola per parola questo audio in italiano. "
            "Restituisci SOLO ed esclusivamente il testo trascritto, nient'altro.", 
            audio_part]
    )
    message_trascribed = response.text.strip()
    logger.info(f"Trascrizione Cloud: {message_trascribed}")
    await update.message.reply_text("Sto elaborando la tua spesa... 🧠")
    
    # Passa il testo trascritto alla funzione condivisa
    await _process_expense_text(update, context, message_trascribed)

async def handle_photos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler per le foto (scontrini e screenshot) — estrae il contesto con Gemini Vision."""
    if not _is_authorized(update):
        return

    # 1. Telegram invia la foto in varie risoluzioni. Noi prendiamo la migliore (l'ultima della lista: [-1])
    foto_hd = update.message.photo[-1]

    # 2. Otteniamo le info del file dai server di Telegram
    file_info = await foto_hd.get_file()

    await update.message.chat.send_action("upload_photo")

    logger.info(f"Foto ricevuta: '{file_info.file_id}'")

    await file_info.download_to_drive("temp_photo.jpg")

    await update.message.reply_text("Immagine ricevuta! Sto accendendo gli occhi bionici... 👁️📸")
    
    #collegamento con la chiave API
    client = genai.Client(api_key=Config.GEMINI_API_KEY)

    # 1. LEGGIAMO IL FILE DAL DISCO
    with open("temp_photo.jpg", "rb") as f:
        photo_bytes = f.read()

    #creo pacchetto foto compatibile con Gemini
    photo_part = types.Part.from_bytes(data=photo_bytes, mime_type="image/jpeg")

    #prompt per la trascrizione
    response=client.models.generate_content(
        model=Config.GEMINI_MODEL,
        contents=["Tu sei un parser di spese. Guarda questa foto (può essere scontrino o notifica), estrai l'importo esatto, la data e il commerciante, e riassumi tutto in una singola frase di testo come se fossi io a dirlo", 
            photo_part]
    )
    message_trascribed = response.text.strip()
    logger.info(f"Trascrizione Cloud: {message_trascribed}")
    await update.message.reply_text("Sto elaborando la tua spesa... 🧠")
    
    # Passa il testo trascritto alla funzione condivisa
    await _process_expense_text(update, context, message_trascribed)

async def _save_to_notion(query, context, account_id: str | None = None):
    data = context.user_data.pop("pending_expense", None)
    context.user_data.pop("waiting_for_amount", None)
    
    if not data:
        await query.edit_message_text("⚠️ Nessuna spesa in sospeso.")
        return
        
    try:
        from datetime import datetime
        expense_date = datetime.strptime(data["date"].split("T")[0], "%Y-%m-%d").date()

        notion = _get_notion()
        notion.create_expense(
            expense_date=expense_date,
            amount=data["amount"],
            name=data["name"],
            category_name=data.get("category"),
            account_id=account_id
        )

        date_str = expense_date.strftime("%d/%m/%Y")
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

    if not _is_authorized(update):
        return

    if query.data == "cancel":
        context.user_data.pop("pending_expense", None)
        context.user_data.pop("waiting_for_amount", None)
        await query.edit_message_text("❌ Spesa annullata.")
        return

    if query.data == "confirm":
        data = context.user_data.get("pending_expense")
        if not data:
            await query.edit_message_text("⚠️ Nessuna spesa in sospeso.")
            return

        # Recupera accounts da Notion per far selezionare il conto
        try:
            notion = _get_notion()
            accounts = notion.fetch_accounts()
        except Exception as e:
            logger.error("Errore fetch accounts. Bypass...")
            accounts = []
            
        if not accounts:
            # Fallback salva subito
            await _save_to_notion(query, context)
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
        await _save_to_notion(query, context, account_id=account_id)
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

    # Registra handlers
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
