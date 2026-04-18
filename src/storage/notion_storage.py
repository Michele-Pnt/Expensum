from datetime import date
from typing import Optional

from src.notion_client import NotionFinanceClient
from src.storage.base import FinancialStorage


class NotionStorage(FinancialStorage):
    """Adapter che implementa FinancialStorage usando Notion come backend.

    Le categorie vengono lette dal DB locale (user_categories) tramite store,
    eliminando la dipendenza da _category_map in-memory e dalle chiamate Notion API
    per il parsing quotidiano.
    """

    def __init__(self, client: NotionFinanceClient, store=None, user_id: Optional[str] = None) -> None:
        self._client = client
        self._store = store
        self._user_id = user_id

    def get_category_names(self) -> list[str]:
        if self._store and self._user_id:
            return self._store.get_user_category_names(self._user_id)
        # Fallback: legge da Notion API se store non disponibile (es. durante bootstrap)
        return self._client.get_category_names()

    def create_expense(
        self,
        expense_date: date,
        amount: float,
        name: str,
        category_name: str,
        account_id: str,
    ) -> dict:
        cat_page_id = None
        if self._store and self._user_id and category_name:
            cat_page_id = self._store.get_notion_page_id_for_category(self._user_id, category_name)
        return self._client.create_expense(
            expense_date, amount, name, category_name, account_id,
            _category_page_id=cat_page_id,
        )

    def create_income(
        self,
        income_date: date,
        amount: float,
        name: str,
        account_id: str,
        income_type: str | None = None,
    ) -> dict:
        return self._client.create_income(income_date, amount, name, account_id, income_type)

    def fetch_all_transactions(self, start_date: date, end_date: date) -> list[dict]:
        resolver = None
        if self._store and self._user_id:
            resolver = lambda pid: self._store.get_category_by_notion_page_id(self._user_id, pid)
        return self._client.fetch_all_transactions(start_date, end_date, category_resolver=resolver)

    def fetch_monthly_balances(self, start_date: date, end_date: date) -> list[dict]:
        return self._client.fetch_monthly_balances(start_date, end_date)

    def fetch_income(self, start_date: date, end_date: date) -> list[dict]:
        return self._client.fetch_income(start_date, end_date)

    def fetch_accounts(self) -> list[dict]:
        return self._client.fetch_accounts()

    def create_account(self, name: str, initial_balance: float = 0.0) -> dict:
        result = self._client.create_account(name, initial_amount=initial_balance)
        return {"id": result["id"], "name": name}

    def create_category(self, name: str) -> dict:
        result = self._client.create_category(name)
        return {"id": result["id"], "name": name}

    def create_subscription(self, name: str) -> dict:
        result = self._client.create_subscription(name)
        return {"id": result["id"], "name": name}
