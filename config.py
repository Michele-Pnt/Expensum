"""
config.py — Gestione centralizzata della configurazione dell'agente.
Carica tutte le variabili d'ambiente dal file .env e le espone come
attributi di un oggetto Config singleton.
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Carica il file .env dalla root del progetto
load_dotenv(dotenv_path=Path(__file__).parent / ".env")


class Config:
    """Configurazione centralizzata dell'agente finanziario."""
    # --- NOTION ---
    NOTION_API_KEY: str = os.getenv("NOTION_API_KEY", "")
    # Database IDs
    NOTION_EXPENSE_DATABASE_ID: str = os.getenv("NOTION_EXPENSE_DATABASE_ID", "")
    NOTION_CATEGORIES_DATABASE_ID: str = os.getenv("NOTION_CATEGORIES_DATABASE_ID", "")
    NOTION_MONTHLY_BALANCE_DATABASE_ID: str = os.getenv("NOTION_MONTHLY_BALANCE_DATABASE_ID", "")
    NOTION_INCOME_DATABASE_ID: str = os.getenv("NOTION_INCOME_DATABASE_ID", "")
    NOTION_ACCOUNTS_DATABASE_ID: str = os.getenv("NOTION_ACCOUNTS_DATABASE_ID", "")
    NOTION_SUBSCRIPTIONS_DATABASE_ID: str = os.getenv("NOTION_SUBSCRIPTIONS_DATABASE_ID", "")
    NOTION_PAY_TRANSFER_DATABASE_ID: str = os.getenv("NOTION_PAY_TRANSFER_DATABASE_ID", "")
    
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

    # --- LLM PROVIDER ---
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini")  # "gemini" o "ollama"

    # --- GEMINI ---
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    GEMINI_FALLBACK_1: str = os.getenv("GEMINI_FALLBACK_1", "gemini-1.5-flash")
    GEMINI_FALLBACK_2: str = os.getenv("GEMINI_FALLBACK_2", "gemini-1.5-flash-8b")

    # --- OLLAMA ---
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

    # --- TELEGRAM ---
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    INVITE_CODE: str = os.getenv("INVITE_CODE", "")
    
    # --- DATABASE ---
    # Default: SQLite locale (sqlite:///users.db). 
    # Per PostgreSQL: "postgresql://utente:password@localhost:5432/financebot"
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///users.db")

    # --- SICUREZZA e CLOUD ---
    # AWS Credentials for Cost Tracking (lettura dashboard)
    AWS_ACCESS_KEY_ID: str = os.getenv("AWS_ACCESS_KEY_ID", "")
    AWS_SECRET_ACCESS_KEY: str = os.getenv("AWS_SECRET_ACCESS_KEY", "")

    # Password master per la web dashboard
    DASHBOARD_PASSWORD: str = os.getenv("DASHBOARD_PASSWORD", "admin")
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

    # --- LOGGING ---
    LOG_DIR: Path = Path(__file__).parent / "logs"
    LOG_LEVEL: int = logging.DEBUG



    @classmethod
    def validate(cls) -> None:
        """Valida che tutte le variabili obbligatorie siano presenti."""
        required = {
            "NOTION_API_KEY": cls.NOTION_API_KEY,
            "NOTION_EXPENSE_DATABASE_ID": cls.NOTION_EXPENSE_DATABASE_ID,
            "NOTION_INCOME_DATABASE_ID": cls.NOTION_INCOME_DATABASE_ID,
            "NOTION_ACCOUNTS_DATABASE_ID": cls.NOTION_ACCOUNTS_DATABASE_ID,
            "TELEGRAM_BOT_TOKEN": cls.TELEGRAM_BOT_TOKEN,
            "TELEGRAM_CHAT_ID": cls.TELEGRAM_CHAT_ID,
            "NOTION_CLIENT_ID": cls.NOTION_CLIENT_ID,
            "NOTION_CLIENT_SECRET": cls.NOTION_CLIENT_SECRET,
        }
        # GEMINI_API_KEY è richiesta solo se il provider è Gemini
        if cls.LLM_PROVIDER == "gemini":
            required["GEMINI_API_KEY"] = cls.GEMINI_API_KEY
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise EnvironmentError(
                f"Variabili d'ambiente mancanti nel file .env: {', '.join(missing)}"
            )


def setup_logging() -> logging.Logger:
    """Configura il sistema di logging con output su file e console."""
    Config.LOG_DIR.mkdir(exist_ok=True)
    log_file = Config.LOG_DIR / "agent.log"

    logging.basicConfig(
        level=Config.LOG_LEVEL,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    # Forza il livello debug per i nostri moduli se impostato in Config
    logger = logging.getLogger("financial_agent.bot")
    logging.getLogger("financial_agent").setLevel(Config.LOG_LEVEL)
    
    return logging.getLogger("financial_agent")

# Inizializza il logging centralizzato
setup_logging()
