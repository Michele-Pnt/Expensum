"""
src/mistral_client.py — Client Mistral Small 3.1 per report mensile.

Drop-in replacement di GeminiClient: stessa interfaccia pubblica,
stesso prompt template Chain-of-Thought, retry identico.
"""

import logging
import httpx

from mistralai.client import Mistral
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from config import Config

logger = logging.getLogger("financial_agent.mistral")


def _normalize_usage_metadata(response) -> dict:
    """Normalizza le usage metadata di Mistral in un formato stabile."""
    usage = {}
    if response.usage:
        prompt_tokens = response.usage.prompt_tokens or 0
        completion_tokens = response.usage.completion_tokens or 0
        total_tokens = response.usage.total_tokens or 0
        if total_tokens <= 0:
            total_tokens = prompt_tokens + completion_tokens
        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "provider": "mistral",
            "model": Config.MISTRAL_SMALL_MODEL,
        }
    return usage

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
Per la tabella risparmio: usa un blocco di codice (``` ``` ```) con colonne allineate a spazi. La colonna "Var. %" è la variazione rispetto al mese precedente nella serie; se è il primo mese disponibile scrivi "—".

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

💸 *Spese*
[Confronto numerico del totale speso: mese corrente vs media storica, con variazione % e una frase di contesto]

💵 *Entrate*
[Confronto entrate mese corrente vs media storica: importi, variazione %, e commento sulla stabilità]

💾 *Risparmio — storico mensile*
```
Mese              Risparmio    Var. %
----------------  -----------  ------
[Mese più vecchio disponibile nei dati Monthly Balance, formato "Mmm YYYY"]  €[importo]   [+/-X%]
...una riga per ogni mese disponibile nel Monthly Balance...
[Mese corrente]   €[importo]   [+/-X%]
```
[Una frase che commenta il trend del risparmio: miglioramento, peggioramento, stabilità rispetto alla media storica di risparmio netto]

📂 *Categorie*
[Per ogni categoria con scostamento rilevante: nome, spesa attuale, media storica, variazione %. Evidenzia chiari sforamenti e virtuosismi. Ignora categorie con scostamento minimo.]

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
✨ _Generato con AI — verifica sempre i numeri_
"""


def _is_retryable(exc: Exception) -> bool:
    """Ritorna True se l'eccezione è retryable (rate limit, server error, timeout)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 503)
    if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException, ConnectionError, TimeoutError)):
        return True
    # Mistral SDK wrappa spesso gli errori API come SDKError con status code nel messaggio
    msg = str(exc).lower()
    return any(code in msg for code in ("429", "500", "503", "rate limit", "too many requests"))


class MistralClient:
    """Client Mistral Small 3.1 per generazione report mensile finanziario."""

    def __init__(self) -> None:
        self._client = Mistral(api_key=Config.MISTRAL_API_KEY, timeout_ms=Config.MISTRAL_TIMEOUT_MS)

    @retry(
        retry=retry_if_exception(_is_retryable),
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
        Genera il report mensile con Mistral Small 3.1.

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
            f"Invio prompt a Mistral ({Config.MISTRAL_SMALL_MODEL}), "
            f"~{len(prompt)} caratteri"
        )

        response = self._client.chat.complete(
            model=Config.MISTRAL_SMALL_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=8192,
        )

        raw_text = response.choices[0].message.content
        if not raw_text:
            raise ValueError("Mistral ha restituito una risposta vuota")

        logger.info(f"Risposta Mistral ricevuta: {len(raw_text)} caratteri")

        # Estrai usage metadata
        usage = _normalize_usage_metadata(response)

        # Rimuovi eventuale ragionamento pre-report (Chain of Thought)
        parts = raw_text.split("📊", 1)
        if len(parts) == 2:
            raw_text = "📊" + parts[1]

        return raw_text.strip(), usage

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=3, max=90),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def generate_weekly_plan(self, plan_data_text: str, week_label: str) -> tuple[str, dict]:
        """
        Genera il piano settimanale con Mistral Small 3.1.

        Args:
            plan_data_text: output di WeeklyPlanData.to_prompt_text()
            week_label: es. "15/05 → 21/05"

        Returns:
            (piano_markdown, usage_metadata)
        """
        prompt = _WEEKLY_PLAN_PROMPT_TEMPLATE.format(
            plan_data=plan_data_text,
            week_label=week_label,
        )

        logger.info(
            f"Invio prompt piano settimanale a Mistral ({Config.MISTRAL_SMALL_MODEL}), "
            f"~{len(prompt)} caratteri"
        )

        response = self._client.chat.complete(
            model=Config.MISTRAL_SMALL_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=4096,
        )

        raw_text = response.choices[0].message.content
        if not raw_text:
            raise ValueError("Mistral ha restituito una risposta vuota per il piano settimanale")

        usage = _normalize_usage_metadata(response)

        # Rimuovi eventuale ragionamento pre-piano
        parts = raw_text.split("📅", 1)
        if len(parts) == 2:
            raw_text = "📅" + parts[1]

        logger.info(f"Piano settimanale Mistral ricevuto: {len(raw_text)} caratteri")
        return raw_text.strip(), usage

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=3, max=90),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def generate_monthly_plan(self, plan_data_text: str, month_label: str) -> tuple[str, dict]:
        """
        Genera il piano mensile con Mistral Small 3.1.

        Args:
            plan_data_text: output di MonthlyPlanData.to_prompt_text()
            month_label: es. "Giugno 2026"

        Returns:
            (piano_markdown, usage_metadata)
        """
        prompt = _MONTHLY_PLAN_PROMPT_TEMPLATE.format(
            plan_data=plan_data_text,
            month_label=month_label,
        )

        logger.info(
            f"Invio prompt piano mensile a Mistral ({Config.MISTRAL_SMALL_MODEL}), "
            f"~{len(prompt)} caratteri"
        )

        response = self._client.chat.complete(
            model=Config.MISTRAL_SMALL_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=4096,
        )

        raw_text = response.choices[0].message.content
        if not raw_text:
            raise ValueError("Mistral ha restituito una risposta vuota per il piano mensile")

        usage = _normalize_usage_metadata(response)

        # Rimuovi eventuale ragionamento pre-piano
        parts = raw_text.split("📅", 1)
        if len(parts) == 2:
            raw_text = "📅" + parts[1]

        logger.info(f"Piano mensile Mistral ricevuto: {len(raw_text)} caratteri")
        return raw_text.strip(), usage

    def generate_lifestyle_categories(self, lifestyle: dict) -> list[str]:
        """Suggerisce categorie di spesa personalizzate basandosi sul profilo lifestyle.

        Privacy: al modello si invia solo il dizionario lifestyle anonimo — nessun dato
        personale, nessun user_id, nessuno storico finanziario.

        Args:
            lifestyle: dizionario anonimo, es. {"transport": "auto", "dining": "spesso",
                       "hobbies": ["palestra", "streaming"]}
        Returns:
            Lista di 10-20 nomi di categoria. Fallback su DEFAULT_CATEGORIES se la
            risposta non è JSON valido o Mistral non risponde.
        """
        from src.workspace_bootstrapper import DEFAULT_CATEGORIES

        baseline = ", ".join(DEFAULT_CATEGORIES)
        lifestyle_text = ", ".join(
            f"{k}: {v if not isinstance(v, list) else ', '.join(v)}"
            for k, v in lifestyle.items()
        )

        prompt = (
            "Sei un esperto di finanza personale. Devi suggerire categorie di spesa "
            "personalizzate per un utente in base al suo stile di vita.\n\n"
            f"Stile di vita: {lifestyle_text}\n\n"
            f"Categorie standard di partenza: {baseline}\n\n"
            "Restituisci SOLO un array JSON con 10-20 nomi di categoria in italiano, "
            "personalizzato in base allo stile di vita sopra. Includi le categorie "
            "standard rilevanti e aggiungine di specifiche per questo profilo. "
            "Esempio: [\"Alimentari\", \"Ristoranti\", \"Auto & Carburante\"]\n\n"
            "IMPORTANTE: rispondi solo con l'array JSON, nessun testo aggiuntivo."
        )

        logger.info(
            "Generazione categorie lifestyle con Mistral (%s)", Config.MISTRAL_SMALL_MODEL
        )

        try:
            response = self._client.chat.complete(
                model=Config.MISTRAL_SMALL_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=512,
            )
            raw = response.choices[0].message.content or ""
            # Estrai il JSON dall'eventuale testo circostante
            start = raw.find('[')
            end = raw.rfind(']')
            if start != -1 and end != -1:
                import json as _json
                categories = _json.loads(raw[start:end + 1])
                if isinstance(categories, list) and categories:
                    logger.info("Categorie lifestyle generate: %d", len(categories))
                    return [str(c) for c in categories]
        except Exception as e:
            logger.warning("Errore generazione categorie lifestyle: %s — uso default", e)

        return list(DEFAULT_CATEGORIES)


_WEEKLY_PLAN_PROMPT_TEMPLATE = """
Sei un Coach Finanziario Personale specializzato in finanza quotidiana.
Hai ricevuto i seguenti dati sull'andamento finanziario settimanale e mensile di un cliente:

--- DATI ANALIZZATI ---
{plan_data}

# ISTRUZIONI DI RAGIONAMENTO (Chain of Thought)

Prima di produrre il piano, analizza internamente:
1. Quali categorie sono critiche (status=attenzione o sforato: proiezione a fine mese supera il budget)?
2. Quali categorie mostrano miglioramento: rinforza il comportamento positivo.
3. Gli abbonamenti in scadenza riducono il budget netto: tienine conto nei consigli.
4. I pattern giornalieri indicano quando l'utente spende di più: sfruttali per i consigli.
5. Se l'utente ha indicato vincoli espliciti, rispettali e costruisci attorno a loro.
6. Se la spesa della settimana scorsa per una categoria è €0.00 (indicato nel dato con [spesa=0: non mostrare avvisi negativi]), NON mostrare avvisi negativi per quella categoria — usa ⬜ nella tabella.

# OUTPUT RICHIESTO

Produci ESATTAMENTE il seguente piano settimanale in Markdown per Telegram.
Usa *grassetto* solo con singolo asterisco.
NON inventare numeri non presenti nei dati.
Il linguaggio deve essere in italiano, il tono deve essere amichevole e informale. 
Sii spiritoso e simpatico MA NON MENTIRE MAI SUI DATI.
Sii specifico e concreto: USA I DATI FORNITI E REALI, non consigli generici.
Tono prospettico: "questa settimana punta a...", non retrospettivo.

---

📅 *Piano Settimana {week_label}*

🔔 *Abbonamenti in uscita questa settimana:*
[Se ci sono abbonamenti nei dati: elencali con importo e data di scadenza]
[Se NON ci sono abbonamenti in scadenza: scrivi "Nessun abbonamento in scadenza questa settimana. 🎉"]

---

🎯 *Obiettivi per categoria*
_Gli obiettivi sono calcolati sul budget mensile impostato dall'utente. Può cambiarlo con /modify_ 🎛️

Genera una tabella in code block (```) con ESATTAMENTE 4 colonne e larghezza MASSIMA 34 caratteri per riga (indispensabile per non andare a capo su Telegram mobile).
Colonne: Categoria (13 car, ljust, tronca con "." se più lungo) | Scorsa (7 car, rjust, €XX.XX) | /sett (6 car, rjust, €XXX/s senza decimali) | T (emoji stato).
Legenda T: usa il campo "status" presente nei dati per ogni categoria.
  • status=ok → ✅ (proiezione fine mese entro il budget)
  • status=attenzione → ⚠️ (al ritmo attuale supererai il budget a fine mese)
  • status=sforato → 🔴 (budget mensile già superato)
  • spesa settimana scorsa = €0.00 → ⬜ (indipendentemente dallo status)
Dopo il code block aggiungi SEMPRE questa legenda in corsivo:
_✅ in target · ⚠️ a questo ritmo esci dal budget · ⬜ nessuna spesa sett. scorsa_
Esempio formato (rispetta ESATTAMENTE questi allineamenti):
```
Categoria      Scorsa   /sett T
───────────────────────────────
Alimentari     €26.84  €86/s ✅
Ristoranti.    €21.41  €46/s ⚠️
Trasporti       €0.00  €37/s ⬜
Svago & Int.  €120.00  €75/s 🔴
```
_✅ in target · ⚠️ a questo ritmo esci dal budget · ⬜ nessuna spesa sett. scorsa_

---

💡 *3 Consigli per questa settimana*

Basati ESCLUSIVAMENTE sui pattern e anomalie nei dati:

1️⃣ [Consiglio specifico con giorno/categoria/importo reale dai dati — es. "il sabato spendi il 35% del tuo budget settimanale alimentare: pianifica la spesa in anticipo"]
2️⃣ [Consiglio specifico]
3️⃣ [Consiglio specifico]

---
✨ _Generato con AI — verifica sempre i numeri_
_Scrivi in modo naturale per modificare un obiettivo_
"""


_MONTHLY_PLAN_PROMPT_TEMPLATE = """
Sei un Coach Finanziario Personale specializzato in pianificazione mensile.
Hai ricevuto i seguenti dati per pianificare il mese di {month_label}:

--- DATI ANALIZZATI ---
{plan_data}

# ISTRUZIONI DI RAGIONAMENTO (Chain of Thought)

Prima di produrre il piano, analizza internamente:
1. Quali categorie mostrano trend in crescita negli ultimi 3 mesi? Richiedono attenzione o un piano di contenimento?
2. Quali categorie sono in calo? Rinforza questo comportamento positivo nel piano.
3. L'obiettivo di risparmio è realistico rispetto alle entrate previste e alle spese storiche?
4. Gli abbonamenti in scadenza riducono il budget disponibile: quantificali nei consigli.
5. Se l'utente ha indicato vincoli espliciti, rispettali e costruisci il piano attorno a loro.

# OUTPUT RICHIESTO

Produci ESATTAMENTE il seguente piano mensile in Markdown per Telegram.
Usa *grassetto* solo con singolo asterisco.
NON inventare numeri non presenti nei dati.
Sii specifico e concreto: usa i dati reali, non consigli generici.
Tono prospettico: "questo mese punta a...", non retrospettivo.

---

📅 *Piano Mensile {month_label}*

💰 Previsione entrate: *€[income_forecast]*
🎯 Obiettivo risparmio: *€[savings_goal]*
🏦 Saldo conti attuale: *€[total_accounts]*

[Se ci sono abbonamenti in scadenza:]
🔔 *Abbonamenti in uscita questo mese:*
[lista abbonamenti con importo e data di scadenza]

---

🎯 *Budget per categoria*

[Per ogni categoria con target, una riga: nome, target €/mese, e una nota breve basata sul trend. Es:]
• *Alimentari* — €X/mese _(stabile negli ultimi 6 mesi)_
• *Ristoranti* — €X/mese _(attenzione: tendenza in crescita, cerca di contenere)_
• *Trasporti* — €X/mese _(ottimo: in calo, continua così)_

---

💡 *3 Consigli per questo mese*

Basati ESCLUSIVAMENTE sui trend e anomalie nei dati:

1️⃣ [Consiglio specifico con categoria/importo reale dai dati]
2️⃣ [Consiglio specifico]
3️⃣ [Consiglio specifico]

---
✨ _Generato con AI — verifica sempre i numeri_
_Scrivi in modo naturale per modificare un obiettivo_
"""

