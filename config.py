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
    # Nomi colonne database Expense
    NOTION_COL_DATE: str = os.getenv("NOTION_COL_DATE", "Date")
    NOTION_COL_CATEGORY: str = os.getenv("NOTION_COL_CATEGORY", "Categories")
    NOTION_COL_NAME: str = os.getenv("NOTION_COL_NAME", "Name")
    NOTION_COL_AMOUNT: str = os.getenv("NOTION_COL_AMOUNT", "Amount")
    NOTION_COL_ACCOUNT: str = os.getenv("NOTION_COL_ACCOUNT", "Accounts")
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

    # --- OLLAMA ---
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

    # --- TELEGRAM ---
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # --- OPZIONI AGENTE ---
    HISTORY_MONTHS: int = int(os.getenv("HISTORY_MONTHS", "6"))
    ANOMALY_THRESHOLD_PCT: float = float(os.getenv("ANOMALY_THRESHOLD_PCT", "25"))
    SCHEDULE_HOUR: int = int(os.getenv("SCHEDULE_HOUR", "7"))
    SCHEDULE_MINUTE: int = int(os.getenv("SCHEDULE_MINUTE", "0"))

    # --- LOGGING ---
    LOG_DIR: Path = Path(__file__).parent / "logs"
    LOG_LEVEL: int = logging.INFO

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
    return logging.getLogger("financial_agent")
