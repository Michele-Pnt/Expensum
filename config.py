"""
config.py — Gestione centralizzata della configurazione dell'agente.
Carica tutte le variabili d'ambiente dal file .env e le espone come
attributi di un oggetto Config singleton.
"""

import json
import os
import logging
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from dotenv import load_dotenv

# Il twin di audit riceve esclusivamente un ambiente Docker sintetico e non deve mai
# leggere file dell'host: altrimenti un build/scanner locale potrebbe ereditare secret
# reali da .env o .env.local. Le normali esecuzioni restano invariate.
_AUDIT_MODE = os.getenv("EXPENSUM_AUDIT_MODE") == "1"
if not _AUDIT_MODE:
    # Carica il file .env dalla root del progetto.
    load_dotenv(dotenv_path=Path(__file__).parent / ".env")

    # Ambiente Postgres locale dockerizzato (development documentation): se .env.local esiste,
    # le sue variabili (DATABASE_URL su localhost:5433, ecc.) vincono su .env. Senza questo,
    # qualsiasi script/processo lanciato in un terminale dove non è stato fatto
    # `source .env.local` a mano ricade silenziosamente sul fallback sqlite di
    # Config.DATABASE_URL, con schema disallineato dalle migration Alembic più recenti.
    # In produzione .env.local non esiste: load_dotenv su un path assente è un no-op innocuo.
    # Esclusa la modalità test (conftest.py imposta TESTING=True prima di ogni import,
    # vedi tests/conftest.py riga 18): i test devono restare sqlite-in-memory, mai Postgres.
    if os.getenv("TESTING") != "True":
        load_dotenv(dotenv_path=Path(__file__).parent / ".env.local", override=True)


class Config:
    """Configurazione centralizzata dell'agente finanziario."""
    # --- PRIVACY POLICY ---
    # Incrementare quando il testo di privacy.html cambia in modo sostanziale:
    # forza un nuovo consenso esplicito (consent_change in audit_log).
    CURRENT_PRIVACY_POLICY_VERSION: str = "2026-06-30"

    # --- TERMINI DI SERVIZIO ---
    # Stesso meccanismo della privacy policy: incrementare quando il testo dei ToS
    # cambia in modo sostanziale, forza un nuovo consenso esplicito.
    CURRENT_TOS_VERSION: str = "2026-09-11"

    # --- NOTION ---
    # Nessuna credenziale/DB ID di default globale: ogni utente usa solo le proprie
    # (src/notion_client.py non ha più fallback su credenziali condivise).

    # URL pubblica della webapp Flask (ngrok in dev, dominio reale in prod)
    WEBAPP_BASE_URL: str = os.getenv("WEBAPP_BASE_URL", "http://localhost:5000")

    # OAuth (Fase 2)
    NOTION_CLIENT_ID: str = os.getenv("NOTION_CLIENT_ID", "")
    NOTION_CLIENT_SECRET: str = os.getenv("NOTION_CLIENT_SECRET", "")
    NOTION_REDIRECT_URI: str = os.getenv("NOTION_REDIRECT_URI", "http://localhost:5000/auth/notion/callback")
    # Nomi colonne database Expense
    NOTION_COL_DATE: str = os.getenv("NOTION_COL_DATE", "Date")
    NOTION_COL_CATEGORY: str = os.getenv("NOTION_COL_CATEGORY", "Categories")
    NOTION_COL_NAME: str = os.getenv("NOTION_COL_NAME", "Name")
    NOTION_COL_AMOUNT: str = os.getenv("NOTION_COL_AMOUNT", "Amount")
    NOTION_COL_ACCOUNT: str = os.getenv("NOTION_COL_ACCOUNT", "Accounts")
    NOTION_INCOME_COL_MISC: str = os.getenv("NOTION_INCOME_COL_MISC", "Misc")
    # Nomi colonne database Accounts (setup)
    NOTION_ACCOUNTS_COL_TYPE: str = os.getenv("NOTION_ACCOUNTS_COL_TYPE", "Account Type")
    # Nomi colonne database Subscriptions
    NOTION_SUB_COL_TYPE:        str = os.getenv("NOTION_SUB_COL_TYPE", "Type")
    NOTION_SUB_COL_AMOUNT:      str = os.getenv("NOTION_SUB_COL_AMOUNT", "Amount")
    NOTION_SUB_COL_CATEGORY:    str = os.getenv("NOTION_SUB_COL_CATEGORY", "Category")
    NOTION_SUB_COL_ACCOUNT:     str = os.getenv("NOTION_SUB_COL_ACCOUNT", "Account")
    NOTION_SUB_COL_LAST_BILLED: str = os.getenv("NOTION_SUB_COL_LAST_BILLED", "Last Billed")
    # Nomi colonne database Accounts
    NOTION_ACCOUNTS_COL_NAME: str = os.getenv("NOTION_ACCOUNTS_COL_NAME", "Name")
    NOTION_ACCOUNTS_COL_BALANCE: str = os.getenv("NOTION_ACCOUNTS_COL_BALANCE", "Current Balance")
    NOTION_ACCOUNTS_COL_INITIAL_AMOUNT: str = os.getenv("NOTION_ACCOUNTS_COL_INITIAL_AMOUNT", "Initial Amount")
    NOTION_ACCOUNTS_COL_TOTAL_INCOME: str = os.getenv("NOTION_ACCOUNTS_COL_TOTAL_INCOME", "Total Income")
    NOTION_ACCOUNTS_COL_TOTAL_TRANSFER_IN: str = os.getenv("NOTION_ACCOUNTS_COL_TOTAL_TRANSFER_IN", "Total Transfer In")
    NOTION_ACCOUNTS_COL_TOTAL_EXPENSE: str = os.getenv("NOTION_ACCOUNTS_COL_TOTAL_EXPENSE", "Total Expense")
    NOTION_ACCOUNTS_COL_TOTAL_TRANSFER_OUT: str = os.getenv("NOTION_ACCOUNTS_COL_TOTAL_TRANSFER_OUT", "Total Transfer Out")
    # Nomi colonne database Monthly Balance
    NOTION_MB_DATE: str = os.getenv("NOTION_MB_DATE", "Month")
    NOTION_MB_NET_SAVINGS: str = os.getenv("NOTION_MB_NET_SAVINGS", "Risparmio Netto")

    # --- MISTRAL ---
    MISTRAL_API_KEY: str = os.getenv("MISTRAL_API_KEY", "")
    MISTRAL_SMALL_MODEL: str = "mistral-small-latest"   # risolve a Mistral Small 4 (2026)
    MISTRAL_LARGE_MODEL: str = "mistral-large-latest"   # ritirato dal catalogo, non più servito da nessun tier
    # Catena modelli per il parsing spese (src/expense_parser.py::_call_mistral).
    # TEMPORANEO (2026-09): sul piano Free MISTRAL_SMALL_MODEL/MISTRAL_LARGE_MODEL sono
    # entrambi a 0 req/min o ritirati — vedi memoria project_mistral_free_tier_model_access.
    # Da riportare a MISTRAL_SMALL_MODEL/MISTRAL_LARGE_MODEL (o equivalenti attivi) appena
    # viene ricaricato credito sull'account Mistral, cambiando solo questi due default.
    MISTRAL_EXPENSE_PARSER_MODEL: str = os.getenv("MISTRAL_EXPENSE_PARSER_MODEL", "ministral-14b-latest")
    MISTRAL_EXPENSE_PARSER_FALLBACK_MODEL: str = os.getenv(
        "MISTRAL_EXPENSE_PARSER_FALLBACK_MODEL", "ministral-8b-latest",
    )
    # Timeout HTTP per chiamata (ms): senza questo il client può restare
    # appeso a tempo indeterminato su una risposta lenta (nessuna eccezione,
    # quindi né retry né except a valle scattano mai).
    MISTRAL_TIMEOUT_MS: int = int(os.getenv("MISTRAL_TIMEOUT_MS", "120000"))

    # --- GEMINI / VERTEX AI ---
    # GEMINI_API_KEY usato solo come fallback; la produzione usa Vertex AI
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    # Vertex AI — trascrizione voce GDPR compliant (dati in EU)
    GOOGLE_CLOUD_PROJECT: str = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    VERTEX_AI_LOCATION: str = os.getenv("VERTEX_AI_LOCATION", "europe-west3")
    # Service account key (JSON minificato) incollata direttamente in .env, alternativa
    # alle Application Default Credentials basate su file quando non disponibili (es. VPS)
    GOOGLE_APPLICATION_CREDENTIALS_JSON: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", "")

    # --- TELEGRAM ---
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    # Destinatari degli alert operativi (log anomali, servizi down) — co-founder inclusi.
    # Comma-separated; se assente ricade sul solo TELEGRAM_CHAT_ID (mai vuoto per errore).
    ADMIN_ALERT_CHAT_IDS: list[str] = [
        cid.strip() for cid in os.getenv("ADMIN_ALERT_CHAT_IDS", "").split(",") if cid.strip()
    ] or ([TELEGRAM_CHAT_ID] if TELEGRAM_CHAT_ID else [])
    # Bot Telegram dedicato agli alert operativi (separato da quello che l'utente usa
    # per tracciare le proprie finanze, così i due flussi di messaggi non si mischiano
    # nella stessa chat). Se assente ricade sullo stesso bot applicativo.
    ALERTS_BOT_TOKEN: str = os.getenv("ALERTS_BOT_TOKEN", "") or TELEGRAM_BOT_TOKEN
    # Username del bot (senza @), usato per costruire deep link t.me/<username>?start=...
    TELEGRAM_BOT_USERNAME: str = os.getenv("TELEGRAM_BOT_USERNAME", "")
    INVITE_CODE: str = os.getenv("INVITE_CODE", "")
    
    # --- BREVO ---
    # Email marketing (sede EU) — sync waitlist beta Tally e futuri contatti utenti.
    BREVO_API_KEY: str = os.getenv("BREVO_API_KEY", "")
    # ID della lista Brevo "Beta Waitlist" (Contacts → Lists → apri la lista → ID nell'URL)
    BREVO_BETA_WAITLIST_LIST_ID: int = int(os.getenv("BREVO_BETA_WAITLIST_LIST_ID", "5"))
    # Segreto HMAC configurato nel webhook Tally: autentica i submit server-to-server.
    TALLY_WEBHOOK_SIGNING_SECRET: str = os.getenv("TALLY_WEBHOOK_SIGNING_SECRET", "")
    # Mittente delle email transazionali (deve essere un dominio verificato su Brevo:
    # Settings → Senders & IP → Domains, con SPF/DKIM configurati)
    BREVO_SENDER_EMAIL: str = os.getenv("BREVO_SENDER_EMAIL", "hello@expensum.it")
    BREVO_SENDER_NAME: str = os.getenv("BREVO_SENDER_NAME", "Expensum")

    # --- TRIAL LIFECYCLE ---
    # Automazione drip (Telegram+email) e downgrade a scadenza trial. Costruita e testata,
    # ma tenuta spenta finché il prodotto è in beta (trial concesso solo manualmente via
    # scripts/grant_trial.py). Va abilitata al passaggio da beta a pubblico.
    TRIAL_AUTOMATION_ENABLED: bool = os.getenv("TRIAL_AUTOMATION_ENABLED", "false").lower() == "true"
    TRIAL_DISCOUNT_CODE: str = os.getenv("TRIAL_DISCOUNT_CODE", "")

    # --- STRIPE (scaffolding, non ancora attivo — vedi task ClickUp pagamenti post-beta) ---
    STRIPE_API_KEY: str = os.getenv("STRIPE_API_KEY", "")
    STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    # Secret key Flask, riusata per firmare i token di unsubscribe nelle email lifecycle
    # (src/unsubscribe_token.py) — stessa variabile usata da src/dashboard/app.py.
    FLASK_SECRET_KEY: str = os.getenv("FLASK_SECRET_KEY", "")

    # --- DATABASE ---
    # Default: SQLite locale (sqlite:///users.db).
    # Per PostgreSQL usa il driver psycopg3 (postgresql+psycopg://):
    #   "postgresql+psycopg://utente:password@localhost:5432/expensum"
    # In produzione questo è il ruolo runtime DML-only (expensum_app), soggetto a RLS.
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///users.db")
    # URL con privilegi DDL (ruolo OWNER) usato SOLO dalle migration Alembic; il
    # runtime dell'app non deve mai usarlo. Fallback su DATABASE_URL se assente.
    MIGRATION_DATABASE_URL: str = os.getenv("MIGRATION_DATABASE_URL", "")
    # DDL a runtime (create_all/_ensure_schema all'avvio). In produzione DEVE essere
    # false: lo schema lo gestisce solo Alembic e il ruolo runtime non ha privilegi DDL.
    RUN_RUNTIME_MIGRATIONS: bool = os.getenv("RUN_RUNTIME_MIGRATIONS", "false").lower() == "true"

    # --- SICUREZZA e CLOUD ---
    # Email di supporto mostrata agli utenti bannati per comportamento malevolo
    SUPPORT_EMAIL: str = os.getenv("SUPPORT_EMAIL", "support@expensum.app")
    # Password master per la web dashboard
    DASHBOARD_PASSWORD: str = os.getenv("DASHBOARD_PASSWORD", "admin")
    # Fase beta: registrazione self-service disattivata, gli account vengono
    # creati manualmente (administrative provisioning) e le credenziali inviate
    # via email. Riattivare (true) solo al lancio pubblico.
    PUBLIC_REGISTRATION_ENABLED: bool = os.getenv("PUBLIC_REGISTRATION_ENABLED", "false").lower() == "true"
    # Accesso beta automatico al submit del form Tally: crea l'account e manda le
    # credenziali subito, senza revisione manuale. Kill-switch rapido: mettere a
    # false blocca le nuove creazioni automatiche senza toccare il resto del flusso
    # (il lead resta comunque salvato/sincronizzato su Brevo).
    AUTO_BETA_ACCESS_ENABLED: bool = os.getenv("AUTO_BETA_ACCESS_ENABLED", "true").lower() == "true"
    # Tetto sul numero di account beta creati automaticamente (oltre, servono
    # creazioni manuali via administrative provisioning). Protegge da un afflusso
    # di submit non previsto in questa fase.
    AUTO_BETA_ACCESS_MAX_ACCOUNTS: int = int(os.getenv("AUTO_BETA_ACCESS_MAX_ACCOUNTS", "50"))
    # Rate Limiting: max messaggi per utente per finestra di 60 secondi
    # Motivazione: un utente legittimo non inserisce più di 2-3 spese al minuto
    MAX_MESSAGES_PER_MINUTE: int = int(os.getenv("MAX_MESSAGES_PER_MINUTE", "10"))
    # Validazione file: uno scontrino pesa 1-3MB, un vocale da 30s ~500KB → 5MB è sicuro
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "5"))
    # Sanitizzazione LLM: "ho speso 45 euro di cena" = ~40 char, 300 è ampiamente sufficiente
    MAX_MESSAGE_LEN: int = int(os.getenv("MAX_MESSAGE_LEN", "300"))

    # --- OPZIONI AGENTE ---
    HISTORY_MONTHS: int = int(os.getenv("HISTORY_MONTHS", "6"))
    ANOMALY_THRESHOLD_PCT: float = float(os.getenv("ANOMALY_THRESHOLD_PCT", "25"))
    SCHEDULE_HOUR: int = int(os.getenv("SCHEDULE_HOUR", "7"))
    SCHEDULE_MINUTE: int = int(os.getenv("SCHEDULE_MINUTE", "0"))

    # --- CATEGORIZZAZIONE ADATTIVA ---
    # Sotto questa soglia la categoria proposta dal parser non viene accettata subito:
    # la spesa resta sulla categoria fallback finché il pattern non si consolida.
    CATEGORY_MATCH_THRESHOLD: float = float(os.getenv("CATEGORY_MATCH_THRESHOLD", "0.70"))
    # Pesi dello score combinato (confidenza string-match LLM + similarità storica).
    # Default 50/50: nessuno dei due segnali è a priori più affidabile dell'altro.
    CATEGORY_MATCH_WEIGHT_LLM: float = float(os.getenv("CATEGORY_MATCH_WEIGHT_LLM", "0.5"))
    CATEGORY_MATCH_WEIGHT_HISTORY: float = float(os.getenv("CATEGORY_MATCH_WEIGHT_HISTORY", "0.5"))
    # Soglia (più alta della 0.6 usata per correggere typo su categorie note) per decidere
    # se due nomi spesa liberi sono lo stesso pattern ricorrente: qui il rischio è
    # raggruppare per errore eventi scorrelati, quindi serve più margine.
    CATEGORY_CANDIDATE_CLUSTER_CUTOFF: float = float(os.getenv("CATEGORY_CANDIDATE_CLUSTER_CUTOFF", "0.8"))
    # Occorrenze minime dello stesso pattern prima di promuoverlo a categoria reale
    # (es. "25 ciabatte" sì, "1 ciabatta" no).
    CATEGORY_PROMOTION_THRESHOLD: int = int(os.getenv("CATEGORY_PROMOTION_THRESHOLD", "5"))
    # Finestra entro cui le occorrenze contano ai fini della promozione (stesso
    # orizzonte trimestrale già usato per i budget suggestion in postgres_storage.py).
    CATEGORY_PROMOTION_WINDOW_DAYS: int = int(os.getenv("CATEGORY_PROMOTION_WINDOW_DAYS", "90"))
    # Categoria di fallback usata finché un pattern resta "pending".
    CATEGORY_FALLBACK_NAME: str = os.getenv("CATEGORY_FALLBACK_NAME", "Altro")

    # --- NORMALIZZAZIONE VOCI DI SPESA (src/expense_label_normalizer.py) ---
    # Metadato di sola aggregazione per i grafici (mai mostrato come descrizione):
    # raggruppa "coca"/"coca cola"/"coca-cola" sotto un'unica ancora per utente+categoria.
    # Soglia più permissiva di CATEGORY_CANDIDATE_CLUSTER_CUTOFF perché qui l'errore
    # costa poco (solo una barra di un grafico), non la creazione di una categoria vera —
    # e partial_ratio (containment) richiede margine diverso da ratio.
    EXPENSE_LABEL_MATCH_THRESHOLD: float = float(os.getenv("EXPENSE_LABEL_MATCH_THRESHOLD", "85"))

    # --- RILEVAMENTO ABBONAMENTI (src/subscription_detector.py) ---
    # Occorrenze alla stessa cadenza prima di chiedere conferma Sì/No all'utente.
    # Basso (2) perché il rischio di falsi positivi è già ridotto a monte dal
    # filtro sulle categorie subscription-prone e dalla cadenza regolare richiesta:
    # un "No" costa solo un tap, non c'è bisogno di aspettare una terza conferma.
    SUBSCRIPTION_CANDIDATE_THRESHOLD: int = int(os.getenv("SUBSCRIPTION_CANDIDATE_THRESHOLD", "2"))
    # Tolleranza sull'importo per considerare due spese "la stessa ricorrenza"
    # (percentuale + minimo assoluto, così un abbonamento da pochi euro non ha
    # una banda troppo stretta per centesimi di arrotondamento).
    SUBSCRIPTION_AMOUNT_TOLERANCE_PCT: float = float(os.getenv("SUBSCRIPTION_AMOUNT_TOLERANCE_PCT", "0.03"))
    SUBSCRIPTION_AMOUNT_TOLERANCE_MIN: float = float(os.getenv("SUBSCRIPTION_AMOUNT_TOLERANCE_MIN", "0.50"))
    # Lookback per il backfill storico e per il comando on-demand: prova prima la
    # finestra più larga (serve per confermare la periodicità), ripiega su quelle
    # più corte se l'utente ha meno storico.
    SUBSCRIPTION_LOOKBACK_DAYS_CASCADE: tuple = (90, 60, 30)

    # --- LOGGING ---
    LOG_DIR: Path = Path(__file__).parent / "logs"
    # Default INFO in produzione: DEBUG va abilitato esplicitamente in dev via .env
    # (il vecchio default fisso a DEBUG era la causa diretta di agent.log a 75MB/mese).
    LOG_LEVEL: int = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)



    @classmethod
    def validate(cls) -> None:
        """Valida che tutte le variabili obbligatorie siano presenti."""
        required = {
            "TELEGRAM_BOT_TOKEN": cls.TELEGRAM_BOT_TOKEN,
            "NOTION_CLIENT_ID": cls.NOTION_CLIENT_ID,
            "NOTION_CLIENT_SECRET": cls.NOTION_CLIENT_SECRET,
        }
        required["MISTRAL_API_KEY"] = cls.MISTRAL_API_KEY
        # Usata per firmare i token di unsubscribe (src/unsubscribe_token.py via bot.py):
        # se assente, i token verrebbero firmati con secret vuoto (HMAC prevedibile).
        required["FLASK_SECRET_KEY"] = cls.FLASK_SECRET_KEY
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise EnvironmentError(
                f"Variabili d'ambiente mancanti nel file .env: {', '.join(missing)}"
            )


# Mappa segmento del nome logger (es. "bot" in "financial_agent.bot" o in
# "src.dashboard.app") -> dominio, usata solo come fallback quando il
# chiamante non passa esplicitamente extra={"domain": ...}.
_DOMAIN_MAP: dict[str, str] = {
    "bot": "bot",
    "main": "bot",
    "user_store": "storage",
    "dashboard": "dashboard",
    "rate_limiter": "security",
    "input_sanitizer": "security",
    "breach_notifier": "security",
    "oauth_bg": "security",
    "postgres_bg": "storage",
    "auth_postgres": "security",
}


def _derive_domain(logger_name: str) -> str:
    """Deriva il dominio dal nome del logger cercando un segmento noto.

    Serve perché non tutti i logger del progetto seguono la gerarchia
    "financial_agent.xxx" (es. src/dashboard/app.py usa logging.getLogger(__name__)
    = "src.dashboard.app"), quindi non si può assumere una posizione fissa.
    """
    for part in logger_name.split("."):
        if part in _DOMAIN_MAP:
            return _DOMAIN_MAP[part]
    return "app"


class JsonFormatter(logging.Formatter):
    """Formatta ogni record come una riga JSON (JSON Lines).

    Schema fisso (ts/level/domain/logger/event/meta) pensato per restare
    stabile anche in caso di futura migrazione a un servizio di log esterno
    (Loki/Better Stack): cambia solo il trasporto, non il parsing.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "domain": getattr(record, "domain", _derive_domain(record.name)),
            "logger": record.name,
            "event": getattr(record, "event", record.getMessage()[:60]),
            "meta": getattr(record, "meta", {}),
        }
        chat_id = getattr(record, "chat_id", None)
        if chat_id is not None:
            payload["chat_id"] = str(chat_id)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class DomainFilter(logging.Filter):
    """Fa passare solo i record il cui dominio è tra quelli consentiti.

    Se `allowed_domains` è None, il filtro lascia passare tutto (usato per
    gli handler "aggregati" come app.jsonl/error.jsonl).
    """

    def __init__(self, allowed_domains: set[str] | None) -> None:
        super().__init__()
        self._allowed_domains = allowed_domains

    def filter(self, record: logging.LogRecord) -> bool:
        if self._allowed_domains is None:
            return True
        domain = getattr(record, "domain", _derive_domain(record.name))
        return domain in self._allowed_domains


def setup_logging() -> logging.Logger:
    """Configura il sistema di logging multi-file JSON Lines, separato per dominio.

    File prodotti in logs/: app.jsonl (flusso generale), error.jsonl (solo
    ERROR+ cross-dominio), security.jsonl (eventi di sicurezza), usage.jsonl
    (azioni utente ed esiti — spese/OCR/audio/parsing, senza contenuto libero,
    include gli errori "attesi" gestiti come WARNING/ERROR di dominio usage),
    debug.jsonl (solo se LOG_LEVEL=DEBUG).
    """
    Config.LOG_DIR.mkdir(exist_ok=True)

    # Handler agganciati al ROOT logger (non a "financial_agent"): in questo
    # modo si catturano anche i logger che non seguono quella gerarchia, es.
    # src/dashboard/app.py usa logging.getLogger(__name__) = "src.dashboard.app".
    root = logging.getLogger()
    root.setLevel(Config.LOG_LEVEL)
    root.handlers.clear()

    # (filename, livello minimo, retention in giorni, domini ammessi o None=tutti)
    handlers_spec: list[tuple[str, int, int, set[str] | None]] = [
        ("app.jsonl", logging.INFO, 14, None),
        ("error.jsonl", logging.ERROR, 30, None),
        ("security.jsonl", logging.WARNING, 180, {"security"}),
        ("usage.jsonl", logging.INFO, 30, {"usage"}),
    ]
    if Config.LOG_LEVEL <= logging.DEBUG:
        handlers_spec.append(("debug.jsonl", logging.DEBUG, 3, None))

    for filename, level, backup_days, allowed_domains in handlers_spec:
        handler = TimedRotatingFileHandler(
            Config.LOG_DIR / filename, when="midnight", backupCount=backup_days, encoding="utf-8",
        )
        handler.setLevel(level)
        handler.setFormatter(JsonFormatter())
        handler.addFilter(DomainFilter(allowed_domains))
        root.addHandler(handler)

    # stdout resta testo semplice (non JSON) per compatibilità con journalctl/systemd
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    root.addHandler(stream_handler)

    return logging.getLogger("financial_agent")

# Inizializza il logging centralizzato
setup_logging()
