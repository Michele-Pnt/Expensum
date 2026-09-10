"""
src/mistral_client.py — Client Mistral Small 3.1 per report mensile.

Drop-in replacement di GeminiClient: stessa interfaccia pubblica,
stesso prompt template Chain-of-Thought, retry identico.

I metodi di generazione report/piani (`analyze_and_generate_report`,
`generate_weekly_plan`, `generate_monthly_plan`) chiedono a Mistral SOLO la
narrazione (paragrafi di commento e consigli), mai numeri o tabelle: quelli
sono sempre costruiti deterministicamente da `src/report_builder.py` a partire
dai dati reali. Questo riduce drasticamente la superficie di errore (l'AI non
può più disallineare una tabella o inventare una cifra) e la latenza (JSON
compatto invece di un intero report Markdown formattato).
"""

import json
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


def _normalize_usage_metadata(response, model: str = Config.MISTRAL_SMALL_MODEL) -> dict:
    """Normalizza le usage metadata di Mistral in un formato stabile.

    `model` deve essere il modello EFFETTIVAMENTE chiamato per generare `response`:
    il ledger token usa questo valore per il lookup del prezzo (vedi
    `UserStore._seed_default_pricing`), quindi un valore hardcoded diverso dalla
    chiamata reale attribuirebbe il costo al modello sbagliato.
    """
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
            "model": model,
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

Prima di produrre la risposta finale, analizza internamente:
1. Verifica che i totali per categoria sommino al totale mensile dichiarato.
2. Controlla che le variazioni percentuali siano coerenti con i dati.
3. Valuta le anomalie: sono significative o rumore?
4. Per i consigli, basa le raccomandazioni ESCLUSIVAMENTE sui dati reali,
   non su generici consigli di risparmio.

# OUTPUT RICHIESTO

Rispondi SOLO con un oggetto JSON valido, nessun testo prima o dopo, nessun
blocco di codice Markdown attorno. Struttura ESATTA:

{{
  "trend_paragraphs": [
    "un paragrafo (1-2 frasi) sul confronto spesa mese corrente vs media storica",
    "un paragrafo sul confronto entrate mese corrente vs media storica",
    "un paragrafo sul trend del risparmio netto rispetto alla media storica",
    "un paragrafo sulle categorie con lo scostamento più rilevante rispetto alla media"
  ],
  "tips": [
    "consiglio specifico basato su un numero reale dai dati",
    "consiglio specifico basato su un numero reale dai dati",
    "consiglio specifico basato su un numero reale dai dati"
  ]
}}

Regole:
- NON inventare numeri non presenti nei dati forniti sopra.
- NON includere KPI, tabelle o il riepilogo: quelli sono già gestiti altrove.
- Testo semplice, senza Markdown (niente *, niente emoji, niente elenchi puntati dentro le stringhe).
- Lingua italiana.
"""


def _parse_json_object(raw_text: str) -> dict:
    """Estrae e valida un oggetto JSON dalla risposta di Mistral.

    Difensivo per costruzione: l'output del modello è un confine esterno non
    fidato, anche con `response_format={"type": "json_object"}" può arrivare
    circondato da testo o code fence se il modello non lo rispetta esattamente.
    """
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Nessun oggetto JSON trovato nella risposta Mistral")

    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("La risposta Mistral non è un oggetto JSON")
    return parsed


def _is_retryable(exc: Exception) -> bool:
    """Ritorna True se l'eccezione è retryable (rate limit, server/gateway error, timeout)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException, ConnectionError, TimeoutError)):
        return True
    # Mistral SDK wrappa spesso gli errori API come SDKError con status code nel messaggio
    msg = str(exc).lower()
    return any(code in msg for code in ("429", "500", "502", "503", "504", "rate limit", "too many requests"))


def _sdk_error_status_code(exc: Exception) -> int | None:
    """Estrae lo status code HTTP da un'eccezione del SDK Mistral, se presente.

    Il SDK espone `status_code` sulle sue `SDKError`; per le altre eccezioni (httpx,
    timeout di rete) non c'è un codice numerico. Nessun dato utente coinvolto: solo un
    intero, sicuro da loggare a livello ERROR.
    """
    return getattr(exc, "status_code", None)


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
    ) -> tuple[dict, dict]:
        """
        Genera la narrazione del report mensile (modello configurato in
        MISTRAL_EXPENSE_PARSER_MODEL) — KPI e tabelle restano a carico di
        `ReportBuilder.build_content`.

        Returns:
            (narrative, usage_metadata) dove narrative è
            `{"trend_paragraphs": [...], "tips": [...]}` e usage_metadata è
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
            f"Invio prompt a Mistral ({Config.MISTRAL_EXPENSE_PARSER_MODEL}), "
            f"~{len(prompt)} caratteri"
        )

        response = self._client.chat.complete(
            model=Config.MISTRAL_EXPENSE_PARSER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1024,
            response_format={"type": "json_object"},
        )

        raw_text = response.choices[0].message.content
        if not raw_text:
            raise ValueError("Mistral ha restituito una risposta vuota")

        narrative = _parse_json_object(raw_text)
        logger.info(f"Narrazione report mensile Mistral ricevuta: {len(raw_text)} caratteri")

        usage = _normalize_usage_metadata(response, model=Config.MISTRAL_EXPENSE_PARSER_MODEL)

        return narrative, usage

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=3, max=90),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def generate_weekly_plan(self, plan_data_text: str, week_label: str) -> tuple[dict, dict]:
        """
        Genera la narrazione del piano settimanale (modello configurato in
        MISTRAL_EXPENSE_PARSER_MODEL) — KPI, abbonamenti e tabella budget
        restano a carico di `WeeklyPlanBuilder.build_content`.

        Args:
            plan_data_text: output di WeeklyPlanData.to_prompt_text()
            week_label: es. "15/05 → 21/05"

        Returns:
            (narrative, usage_metadata) dove narrative è `{"tips": [...]}`
        """
        prompt = _WEEKLY_PLAN_PROMPT_TEMPLATE.format(
            plan_data=plan_data_text,
            week_label=week_label,
        )

        logger.info(
            f"Invio prompt piano settimanale a Mistral ({Config.MISTRAL_EXPENSE_PARSER_MODEL}), "
            f"~{len(prompt)} caratteri"
        )

        response = self._client.chat.complete(
            model=Config.MISTRAL_EXPENSE_PARSER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=512,
            response_format={"type": "json_object"},
        )

        raw_text = response.choices[0].message.content
        if not raw_text:
            raise ValueError("Mistral ha restituito una risposta vuota per il piano settimanale")

        narrative = _parse_json_object(raw_text)
        usage = _normalize_usage_metadata(response, model=Config.MISTRAL_EXPENSE_PARSER_MODEL)

        logger.info(f"Narrazione piano settimanale Mistral ricevuta: {len(raw_text)} caratteri")
        return narrative, usage

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=3, max=90),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def generate_monthly_plan(self, plan_data_text: str, month_label: str) -> tuple[dict, dict]:
        """
        Genera la narrazione del piano mensile previsionale (modello configurato
        in MISTRAL_EXPENSE_PARSER_MODEL) — KPI, abbonamenti e tabella target
        restano a carico di `MonthlyPlanBuilder.build_content`.

        Args:
            plan_data_text: output di MonthlyPlanData.to_prompt_text()
            month_label: es. "Giugno 2026"

        Returns:
            (narrative, usage_metadata) dove narrative è `{"tips": [...]}`
        """
        prompt = _MONTHLY_PLAN_PROMPT_TEMPLATE.format(
            plan_data=plan_data_text,
            month_label=month_label,
        )

        logger.info(
            f"Invio prompt piano mensile a Mistral ({Config.MISTRAL_EXPENSE_PARSER_MODEL}), "
            f"~{len(prompt)} caratteri"
        )

        response = self._client.chat.complete(
            model=Config.MISTRAL_EXPENSE_PARSER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=512,
            response_format={"type": "json_object"},
        )

        raw_text = response.choices[0].message.content
        if not raw_text:
            raise ValueError("Mistral ha restituito una risposta vuota per il piano mensile")

        narrative = _parse_json_object(raw_text)
        usage = _normalize_usage_metadata(response, model=Config.MISTRAL_EXPENSE_PARSER_MODEL)

        logger.info(f"Narrazione piano mensile Mistral ricevuta: {len(raw_text)} caratteri")
        return narrative, usage

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
            "Generazione categorie lifestyle con Mistral (%s)", Config.MISTRAL_EXPENSE_PARSER_MODEL
        )

        try:
            response = self._client.chat.complete(
                model=Config.MISTRAL_EXPENSE_PARSER_MODEL,
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

    def synthesize_category_description(self, raw_description: str) -> str | None:
        """Sintetizza la descrizione di una categoria scritta dall'utente in una
        frase breve, chiamata una tantum quando l'utente crea/modifica una
        categoria (non ad ogni parsing spesa — vedi `ExpenseParser`, che riusa
        solo il risultato salvato in `description_summary`).

        Mantiene il registro discorsivo dell'utente (frase in linguaggio
        naturale, non parole chiave): serve a comprimere descrizioni verbose in
        una forma compatta senza perdere il criterio comportamentale espresso.

        Se Mistral non risponde non produce un fallback dal testo originale: la
        descrizione resta salvata per l'utente, ma non viene mai promossa a
        contesto del system prompt senza una sintesi validata.
        """
        prompt = (
            "Sintetizza in UNA sola frase breve (massimo 20 parole), in italiano "
            "naturale e nello stesso registro discorsivo dell'originale, la seguente "
            "descrizione di una categoria di spesa personale. Non usare parole chiave "
            "o elenchi puntati, scrivi una frase normale che descriva il comportamento "
            "di spesa. Rispondi SOLO con la frase, nessun altro testo.\n\n"
            f"Descrizione originale: \"{raw_description.strip()}\""
        )

        try:
            response = self._client.chat.complete(
                model=Config.MISTRAL_EXPENSE_PARSER_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=128,
            )
            summary = (response.choices[0].message.content or "").strip().strip('"')
            if not summary:
                return None
            from src.input_sanitizer import sanitize_category_metadata
            return sanitize_category_metadata(summary, "system", field="description")
        except Exception as exc:
            logger.warning(
                "category_description_synthesis_failed",
                extra={"domain": "financial", "event": "category_description_synthesis_failed",
                       "meta": {"error_type": type(exc).__name__}},
            )
            return None

    def generate_category_description_from_name(
        self, category_name: str, example_expense_name: str | None = None,
    ) -> str | None:
        """Genera una descrizione comportamentale per una categoria creata
        automaticamente (promozione da pattern ricorrente, vedi
        `category_matcher._promote_candidate`), dove non esiste un testo scritto
        dall'utente da sintetizzare — solo il nome della categoria (e opzionalmente
        il nome di una spesa reale che l'ha originata).

        Ritorna `None` (non un fallback troncato: qui non c'è testo originale da
        recuperare) se Mistral non risponde — la categoria viene comunque creata,
        semplicemente senza descrizione, l'utente potrà scriverne una in webapp.
        """
        context = f" (nata da spese come \"{example_expense_name}\")" if example_expense_name else ""
        prompt = (
            "Sei un assistente finanziario. Scrivi UNA sola frase breve (massimo 15 "
            "parole), in italiano naturale, che descriva a quale tipo di spese si "
            f"riferisce generalmente una categoria di spesa personale chiamata "
            f"\"{category_name}\"{context}. Non usare parole chiave o elenchi, scrivi "
            "una frase normale. Rispondi SOLO con la frase, nessun altro testo."
        )
        try:
            response = self._client.chat.complete(
                model=Config.MISTRAL_EXPENSE_PARSER_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=128,
            )
            summary = (response.choices[0].message.content or "").strip().strip('"')
            return summary or None
        except Exception as e:
            logger.warning(
                "Errore generazione descrizione per categoria promossa '%s': %s", category_name, e,
            )
            return None


_WEEKLY_PLAN_PROMPT_TEMPLATE = """
Sei un Coach Finanziario Personale specializzato in finanza quotidiana.
Hai ricevuto i seguenti dati sull'andamento finanziario settimanale e mensile di un cliente
per la settimana {week_label}:

--- DATI ANALIZZATI ---
{plan_data}

# ISTRUZIONI DI RAGIONAMENTO (Chain of Thought)

Prima di produrre i consigli, analizza internamente:
1. Quali categorie sono critiche (status=attenzione o sforato: proiezione a fine mese supera il budget)?
2. Quali categorie mostrano miglioramento: rinforza il comportamento positivo.
3. Gli abbonamenti in scadenza riducono il budget netto: tienine conto.
4. I pattern giornalieri indicano quando l'utente spende di più: sfruttali.
5. Se la spesa della settimana scorsa per una categoria è €0.00 (indicato nel dato
   con [spesa=0: non mostrare avvisi negativi]), NON generare un consiglio negativo
   su quella categoria.

# OUTPUT RICHIESTO

Rispondi SOLO con un oggetto JSON valido, nessun testo prima o dopo, nessun
blocco di codice Markdown attorno. Struttura ESATTA:

{{
  "tips": [
    "consiglio specifico per questa settimana con giorno/categoria/importo reale dai dati",
    "consiglio specifico",
    "consiglio specifico"
  ]
}}

Regole:
- NON inventare numeri non presenti nei dati forniti sopra.
- Tono amichevole e informale, prospettico ("questa settimana punta a..."), MAI menzognero sui dati.
- Testo semplice, senza Markdown (niente *, niente emoji, niente elenchi puntati dentro le stringhe).
- Lingua italiana.
"""


_MONTHLY_PLAN_PROMPT_TEMPLATE = """
Sei un Coach Finanziario Personale specializzato in pianificazione mensile.
Hai ricevuto i seguenti dati per pianificare il mese di {month_label}:

--- DATI ANALIZZATI ---
{plan_data}

# ISTRUZIONI DI RAGIONAMENTO (Chain of Thought)

Prima di produrre i consigli, analizza internamente:
1. Quali categorie mostrano trend in crescita negli ultimi 3 mesi? Richiedono attenzione o un piano di contenimento?
2. Quali categorie sono in calo? Rinforza questo comportamento positivo.
3. L'obiettivo di risparmio è realistico rispetto alle entrate previste e alle spese storiche?
4. Gli abbonamenti in scadenza riducono il budget disponibile: quantificali nei consigli.
5. Se l'utente ha indicato vincoli espliciti, rispettali.

# OUTPUT RICHIESTO

Rispondi SOLO con un oggetto JSON valido, nessun testo prima o dopo, nessun
blocco di codice Markdown attorno. Struttura ESATTA:

{{
  "tips": [
    "consiglio specifico per questo mese con categoria/importo reale dai dati",
    "consiglio specifico",
    "consiglio specifico"
  ]
}}

Regole:
- NON inventare numeri non presenti nei dati forniti sopra.
- Tono prospettico ("questo mese punta a..."), specifico e concreto, MAI menzognero sui dati.
- Testo semplice, senza Markdown (niente *, niente emoji, niente elenchi puntati dentro le stringhe).
- Lingua italiana.
"""
