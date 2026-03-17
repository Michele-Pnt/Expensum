"""
src/telegram_client.py — Invio messaggi via Telegram Bot API.

Funzionalità:
- Invio messaggi con parse_mode MarkdownV2
- Split automatico per il limite di 4096 char di Telegram
- Metodo di test per verificare la connessione
- Retry su errori di rete
"""

import asyncio
import logging
import re

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from config import Config

logger = logging.getLogger("financial_agent.telegram")

MAX_MESSAGE_LENGTH = 4096


class TelegramClient:
    """Client per l'invio di messaggi Telegram."""

    def __init__(self):
        self._bot = Bot(token=Config.TELEGRAM_BOT_TOKEN)
        self._chat_id = Config.TELEGRAM_CHAT_ID

    # ------------------------------------------------------------------
    # Invio principale
    # ------------------------------------------------------------------
    async def send_report(self, text: str) -> None:
        """
        Invia il report Markdown su Telegram.
        Se il messaggio supera 4096 caratteri, viene spezzato in più parti.
        """
        text = self._normalize_markdown(text)
        chunks = self._split_message(text)
        logger.info(f"Invio report Telegram: {len(chunks)} messaggio/i")

        for i, chunk in enumerate(chunks, 1):
            await self._send_message(chunk)
            if len(chunks) > 1:
                logger.debug(f"Chunk {i}/{len(chunks)} inviato")
                await asyncio.sleep(0.5)  # Evita rate limiting

    @retry(
        retry=retry_if_exception_type((TelegramError, ConnectionError, TimeoutError)),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _send_message(self, text: str) -> None:
        """Invia un singolo messaggio con retry automatico."""
        try:
            await self._bot.send_message(
                chat_id=self._chat_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
        except TelegramError as e:
            # Se il Markdown è malformato, ritenta in plain text
            if "can't parse" in str(e).lower():
                logger.warning(
                    "Errore parsing Markdown, invio come testo semplice"
                )
                await self._bot.send_message(
                    chat_id=self._chat_id,
                    text=self._strip_markdown(text),
                )
            else:
                raise

    # ------------------------------------------------------------------
    # Invio Foto (Grafici)
    # ------------------------------------------------------------------
    @retry(
        retry=retry_if_exception_type((TelegramError, ConnectionError, TimeoutError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def send_photo(self, photo_path: str, caption: str = None) -> None:
        """Invia un'immagine con opzionale didascalia."""
        try:
            with open(photo_path, "rb") as photo_file:
                await self._bot.send_photo(
                    chat_id=self._chat_id,
                    photo=photo_file,
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN
                )
            logger.info(f"Foto inviata con successo: {photo_path}")
        except FileNotFoundError:
            logger.error(f"Impossibile inviare foto, file non trovato: {photo_path}")
        except TelegramError as e:
            logger.error(f"Errore Telegram invio foto: {e}")
            raise

    # ------------------------------------------------------------------
    # Test connessione
    # ------------------------------------------------------------------
    async def send_test_message(self) -> str:
        """Invia un messaggio di test e ritorna lo stato."""
        try:
            await self._bot.send_message(
                chat_id=self._chat_id,
                text=(
                    "✅ *Agente Finanziario* — Test connessione OK!\n"
                    "Il bot è configurato correttamente e pronto all'uso."
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
            return "✅ Messaggio di test inviato con successo!"
        except TelegramError as e:
            return f"❌ Errore Telegram: {e}"

    # ------------------------------------------------------------------
    # Utility: split messaggio lungo
    # ------------------------------------------------------------------
    @staticmethod
    def _split_message(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> list[str]:
        """
        Divide un testo lungo in chunk che rispettano il limite Telegram.
        Cerca di spezzare sui separatori "---" o su newline.
        """
        if len(text) <= max_length:
            return [text]

        chunks = []
        current_chunk = ""

        for line in text.split("\n"):
            candidate = current_chunk + "\n" + line if current_chunk else line
            if len(candidate) > max_length:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = line
            else:
                current_chunk = candidate

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks

    @staticmethod
    def _normalize_markdown(text: str) -> str:
        """Normalizza il markdown verso lo stile supportato da Telegram Markdown."""
        text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
        text = re.sub(r"__(.+?)__", r"_\1_", text)
        return text

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Rimuove marker markdown quando si invia in plain text."""
        return (
            text.replace("*", "")
            .replace("_", "")
            .replace("`", "")
        )
