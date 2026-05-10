"""
src/gemini_client.py — Client per Gemini 2.5 Flash con Chain of Thought e retry.

Usa il nuovo SDK ufficiale google-genai (>= 1.0.0).

Caratteristiche:
- Modello: gemini-2.5-flash (finestra di contesto ampia, gratuito)
- Chain of Thought: il prompt chiede al modello di mostrare i passaggi logici
  prima di produrre il report finale (riduce le allucinazioni numeriche)
- Unica chiamata al modello per tutto il report (minimizza costi API)
- Retry automatico su errori 503/429/500 con exponential backoff (max 5 tentativi)
- Temperatura 0.2 per risposte numericamente accurate
"""

import logging
import httpx

from google import genai
from google.genai import types
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from config import Config

logger = logging.getLogger("financial_agent.gemini")


def _normalize_usage_metadata(response) -> dict:
    """Normalizza le usage metadata di Gemini in un formato stabile."""
    usage = {}
    if response.usage_metadata:
        um = response.usage_metadata
        prompt_tokens = getattr(um, "prompt_token_count", 0) or 0
        completion_tokens = getattr(um, "candidates_token_count", 0) or 0
        total_tokens = getattr(um, "total_token_count", 0) or 0
        if total_tokens <= 0:
            total_tokens = prompt_tokens + completion_tokens
        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "thinking_tokens": getattr(um, "thoughts_token_count", None),
            "provider": "gemini",
            "model": Config.GEMINI_MODEL,
        }
    return usage

# Eccezioni su cui effettuare retry
_RETRYABLE = (
    httpx.HTTPStatusError,
    httpx.ConnectError,
    httpx.TimeoutException,
    ConnectionError,
    TimeoutError,
)

# Template del prompt con Chain of Thought
_PROMPT_TEMPLATE = """
Sei un Senior Financial Analyst specializzato in finanza personale.
Hai ricevuto i seguenti dati strutturati sulle spese mensili di un cliente:

--- DATI ANALIZZATI ---
{data_block}

--- STATO DEI CONTI ---
{accounts_block}

--- DATI PREVISIONE ---
{forecast_block}

# ISTRUZIONI DI RAGIONAMENTO (Chain of Thought)

Prima di produrre il report finale, esegui i seguenti passaggi di ragionamento
internamente (puoi mostrarli come "RAGIONAMENTO:"):

1. Verifica che i totali per categoria sommino al totale mensile dichiarato.
2. Controlla che le variazioni percentuali siano coerenti con i dati.
3. Valuta le anomalie: sono significative o rumore?
4. Per i consigli, basa le raccomandazioni ESCLUSIVAMENTE sui dati reali,
   non su generici consigli di risparmio.

# OUTPUT RICHIESTO

Produci ESATTAMENTE il seguente report in formato Markdown per Telegram.
USA questi emoji esatti nelle intestazioni.
NON inventare numeri non presenti nei dati.
NON ricalcolare il "Denaro sui conti": usa ESATTAMENTE il valore già fornito.
Usa *grassetto* solo con singolo asterisco (esempio: *testo*), MAI con doppio asterisco.

---

📊 *Riepilogo {current_month}*
Spesa totale: *€{total_amount}*
Entrate totali: *€{total_income}*
🏦 Denaro sui conti: *€{total_accounts_balance}*
Risparmio mensile: *{net_savings}*

*Spesa per categorie:*
[Lista completa di tutte le categorie di spesa del mese attuale con relativo importo e percentuale]

---

📉 *Analisi e Confronto Trend*
- *Spese*: [Confronto testuale e numerico del totale speso: mese corrente vs storico]
- *Entrate*: [Confronto entrate mese corrente vs storico o commento sulla stabilità]
- *Risparmio*: [Confronto del risparmio mensile corrente vs i mesi storici del Monthly Balance]
- *Categorie*: [Confronto delle spese per categoria del mese corrente vs la "Media Notion" o media storica, evidenziando chiari sforamenti o virtuosismi]

---

🔮 *Previsione {next_month}*

Stima ottimistica: *€[valore]*
Stima base: *€[valore]*
Stima pessimistica: *€[valore]*

[Spiega brevemente i fattori principali che influenzano la previsione]

---

💡 *3 Consigli Azionabili*

Basati ESCLUSIVAMENTE sulle anomalie e i trend nei dati:

1️⃣ [Consiglio specifico con numero reale dai dati]
2️⃣ [Consiglio specifico con numero reale dai dati]
3️⃣ [Consiglio specifico con numero reale dai dati]

---
_Report generato automaticamente dall'Agente Finanziario 🤖_
"""


def _is_retryable_http(exc: Exception) -> bool:
    """Ritorna True se l'errore HTTP è un 429, 500 o 503."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 503)
    return isinstance(exc, (httpx.ConnectError, httpx.TimeoutException, ConnectionError, TimeoutError))


class GeminiClient:
    """Client per Gemini 2.5 Flash con retry e Chain of Thought."""

    def __init__(self):
        self._client = genai.Client(api_key=Config.GEMINI_API_KEY)

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=3, max=90),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def analyze_and_generate_report(
        self,
        data_text: str,
        accounts_text: str,
        forecast_text: str,
        current_month_label: str,
        next_month_label: str,
        total_income: str,
        total_amount: str,
        total_accounts_balance: str,
        net_savings: str = "n/d",
    ) -> tuple[str, dict]:
        """
        Chiama Gemini 2.5 Flash con i dati aggregati e il forecast.

        Returns:
            (report_markdown, usage_metadata) dove usage_metadata è:
            {prompt_tokens, completion_tokens, total_tokens, provider, model}
        """
        prompt = _PROMPT_TEMPLATE.format(
            data_block=data_text,
            accounts_block=accounts_text,
            forecast_block=forecast_text,
            current_month=current_month_label,
            next_month=next_month_label,
            total_income=total_income,
            total_amount=total_amount,
            total_accounts_balance=total_accounts_balance,
            net_savings=net_savings,
        )

        logger.info(
            f"Invio prompt a Gemini ({Config.GEMINI_MODEL}), "
            f"~{len(prompt)} caratteri"
        )

        response = self._client.models.generate_content(
            model=Config.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=8192,
            ),
        )

        # response.text può essere None se il modello usa thinking tokens separati
        raw_text = response.text
        if raw_text is None:
            raw_text = ""
            for candidate in (response.candidates or []):
                for part in (candidate.content.parts or []):
                    if hasattr(part, "text") and part.text:
                        raw_text += part.text

        if not raw_text:
            raise ValueError("Gemini ha restituito una risposta vuota")

        logger.info(f"Risposta Gemini ricevuta: {len(raw_text)} caratteri")

        # Estrai usage metadata
        usage = _normalize_usage_metadata(response)

        # Rimuovi eventuale sezione di ragionamento (Chain of Thought)
        parts = raw_text.split("📊", 1)
        if len(parts) == 2:
            raw_text = "📊" + parts[1]

        return raw_text.strip(), usage
