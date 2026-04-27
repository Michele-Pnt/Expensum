from abc import ABC, abstractmethod
from datetime import date


class FinancialStorage(ABC):
    """Interfaccia astratta per il layer di storage information.
   
      Ogni backend (Notion, PostgreSQL, ecc.) deve implementare questi metodi.
      Il resto del codice (bot.py, main.py) usa solo questa interfaccia,
      senza sapere quale backend c'è sotto.
    """
    @abstractmethod
    def get_category_names(self) -> list[str]:
        """Restituisce i nomi di tutte le categorie dell'utente."""
        ...

    @abstractmethod
    def create_expense(
        self,
        expense_date: date,
        amount: float,
        name: str,
        category_name: str,
        account_id: str,
        monthly_balance_id: str | None = None,
    ) -> dict:
        """Crea una nuova spesa e restituisce un dict con i dati salvati."""
        ...

    @abstractmethod
    def create_income(
        self,
        income_date: date,
        amount: float,
        name: str,
        account_id: str,
        income_type: str | None = None,
    ) -> dict:
        """Crea una nuova entrata e restituisce un dict con i dati salvati."""
        ...

    @abstractmethod
    def fetch_all_transactions(self, start_date: date, end_date: date) -> list[dict]:
        """Restituisce tutte le spese nel periodo indicato."""
        ...

    @abstractmethod
    def fetch_monthly_balances(self, start_date: date, end_date: date) -> list[dict]:
        """Restituisce i bilanci mensili nel periodo indicato."""
        ...

    @abstractmethod
    def fetch_income(self, start_date: date, end_date: date) -> list[dict]:
        """Restituisce tutte le entrate nel periodo indicato."""
        ...

    @abstractmethod
    def fetch_accounts(self) -> list[dict]:
        """Restituisce tutti i conti dell'utente con il saldo."""
        ...

    @abstractmethod
    def create_account(self, name: str, initial_balance: float = 0.0) -> dict:
        """Crea un nuovo conto. Restituisce dict con almeno 'id' e 'name'."""
        ...

    @abstractmethod
    def create_category(self, name: str) -> dict:
        """Crea una nuova categoria. Restituisce dict con almeno 'id' e 'name'."""
        ...

    @abstractmethod
    def create_subscription(self, name: str) -> dict:
        """Crea un nuovo abbonamento. Restituisce dict con almeno 'id' e 'name'."""
        ...

    @abstractmethod
    def fetch_subscriptions(self) -> list[dict]:
        """Restituisce tutti gli abbonamenti dell'utente.

        Ogni dict contiene almeno: name, amount, last_billed (ISO string o None).
        """
        ...

    def update_subscription(self, sub_id: str, last_billed: date | None = None) -> bool:
        """Aggiorna i dati di un abbonamento. Per ora supportiamo solo last_billed."""
        return False

    @abstractmethod
    def get_or_create_monthly_balance(self, target_date: date) -> str | None:
        """Ritorna l'ID del record Monthly Balance per il mese della data fornita.
        Se non esiste, lo crea.
        """
        ...