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

    def get_category_names(self, include_archived: bool = False) -> list[str]:
        """Notion non ha il concetto di archiviazione: il parametro è ignorato."""
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
        monthly_balance_id: str | None = None,
    ) -> dict:
        cat_page_id = None
        if self._store and self._user_id and category_name:
            cat_page_id = self._store.get_notion_page_id_for_category(self._user_id, category_name)
        return self._client.create_expense(
            expense_date, amount, name, category_name, account_id,
            monthly_balance_id=monthly_balance_id,
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

    def create_category(
        self, name: str, monthly_budget: float | None = None,
        description: str | None = None, description_summary: str | None = None,
    ) -> dict:
        # description/description_summary non supportati su Notion (solo Postgres, vedi base.py).
        result = self._client.create_category(name)
        return {"id": result["id"], "name": name}

    def create_transfer(
        self,
        transfer_date: date,
        amount: float,
        from_account_id: str,
        to_account_id: str,
        name: str | None = None,
    ) -> dict:
        result = self._client.create_transfer(
            transfer_date, amount, from_account_id, to_account_id, name=name,
        )
        return {
            "id": result["id"],
            "amount": amount,
            "from_account_id": from_account_id,
            "to_account_id": to_account_id,
        }

    def fetch_transfers(self, start_date: date, end_date: date) -> list[dict]:
        return self._client.fetch_transfers(start_date, end_date)

    def create_subscription(
        self,
        name: str,
        amount: float | None = None,
        last_billed: str | None = None,
        sub_type: str | None = None,
        account_id: str | None = None,
        category_id: str | None = None,
        category_name: str | None = None,
    ) -> dict:
        """Crea un abbonamento. `category_name` viene risolta in page_id Notion
        (stesso pattern di `create_expense`) se `category_id` non è già passato."""
        resolved_category_id = category_id
        if resolved_category_id is None and self._store and self._user_id and category_name:
            resolved_category_id = self._store.get_notion_page_id_for_category(self._user_id, category_name)
        result = self._client.create_subscription(
            name,
            sub_type=sub_type,
            amount=amount,
            category_id=resolved_category_id,
            account_id=account_id,
            last_billed=last_billed,
        )
        return {"id": result["id"], "name": name}

    def get_categories(self, include_archived: bool = False) -> list[dict]:
        """Categorie con budget e average dal DB locale. Notion non archivia: parametro ignorato."""
        if self._store and self._user_id:
            return self._store.get_user_categories_with_budget(self._user_id)
        return [{"name": n, "monthly_budget": None, "average": 0.0} for n in self.get_category_names()]

    def fetch_subscriptions(self) -> list[dict]:
        return self._client.fetch_subscriptions()

    def update_subscription(self, sub_id: str, last_billed: date | None = None) -> bool:
        return self._client.update_subscription(sub_id, last_billed=last_billed)

    def get_or_create_monthly_balance(self, target_date: date) -> str | None:
        return self._client.get_or_create_monthly_balance(target_date)
