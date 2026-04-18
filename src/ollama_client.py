"""
src/ollama_client.py — Client per modelli locali Ollama.

Drop-in replacement per GeminiClient: stessa interfaccia, stesso prompt.
Usa il modello locale via Ollama per generare il report finanziario.

Caratteristiche:
- Stessa firma di GeminiClient.analyze_and_generate_report()
- Retry automatico su errori di connessione
- Misura e logga il tempo di inferenza per benchmarking
- Temperatura 0.2 per risposte numericamente accurate
"""

import logging
import time

import ollama as _ollama
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from config import Config

logger = logging.getLogger("financial_agent.ollama")

# Eccezioni su cui effettuare retry
_RETRYABLE = (
    ConnectionError,
    TimeoutError,
    _ollama.ResponseError,
)

# Template del prompt — identico a quello di GeminiClient
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


class OllamaClient:
    """Client per modelli locali Ollama — drop-in replacement per GeminiClient."""

    def __init__(self):
        self._client = _ollama.Client(host=Config.OLLAMA_BASE_URL)
        # Verifica che il modello sia disponibile
        try:
            models = self._client.list()
            model_names = [m.model for m in models.models]
            if not any(Config.OLLAMA_MODEL in name for name in model_names):
                logger.warning(
                    f"Modello '{Config.OLLAMA_MODEL}' non trovato tra i modelli locali: "
                    f"{model_names}. Potrebbe essere necessario eseguire: "
                    f"ollama pull {Config.OLLAMA_MODEL}"
                )
        except Exception as e:
            logger.error(f"Impossibile connettersi a Ollama: {e}")
            raise ConnectionError(
                f"Ollama non raggiungibile su {Config.OLLAMA_BASE_URL}. "
                f"Assicurati che Ollama sia in esecuzione."
            ) from e

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=3, max=30),
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
    ) -> str:
        """
        Chiama il modello locale Ollama con i dati aggregati e il forecast.
        Ritorna il report Markdown formattato per Telegram.

        Stessa interfaccia di GeminiClient.analyze_and_generate_report().
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
            f"Invio prompt a Ollama ({Config.OLLAMA_MODEL}), "
            f"~{len(prompt)} caratteri"
        )

        start_time = time.time()

        response = self._client.chat(
            model=Config.OLLAMA_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Sei un Senior Financial Analyst. Rispondi SOLO con il report "
                        "richiesto nel formato Markdown specificato. Non aggiungere "
                        "commenti o spiegazioni al di fuori del formato."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            options={
                "temperature": 0.2,
                "num_predict": 4096,
            },
        )

        elapsed = time.time() - start_time
        raw_text = response.message.content or ""

        if not raw_text:
            raise ValueError("Ollama ha restituito una risposta vuota")

        logger.info(
            f"Risposta Ollama ricevuta: {len(raw_text)} caratteri "
            f"in {elapsed:.1f}s"
        )

        # Rimuovi eventuale sezione di ragionamento (Chain of Thought)
        parts = raw_text.split("📊", 1)
        if len(parts) == 2:
            raw_text = "📊" + parts[1]

        return raw_text.strip()
