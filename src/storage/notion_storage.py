from datetime import date
from typing import Optional

from sqlalchemy.exc import IntegrityError

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
        income_category_id: int | None = None,
        income_category_name: str | None = None,
        income_type: str | None = None,
    ) -> dict:
        from src.income_categories import normalize_income_category_name

        category = self._owned_local_income_category(income_category_id) if income_category_id else None
        resolved_name = category["name"] if category else normalize_income_category_name(
            income_category_name if income_category_name is not None else income_type
        )
        category = category or self._ensure_local_income_category(resolved_name)
        result = self._client.create_income(income_date, amount, name, account_id, resolved_name)
        result["income_type"] = resolved_name
        result["income_category"] = resolved_name
        result["income_category_id"] = category["id"] if category else None
        return result

    def fetch_all_transactions(self, start_date: date, end_date: date) -> list[dict]:
        resolver = None
        if self._store and self._user_id:
            resolver = lambda pid: self._store.get_category_by_notion_page_id(self._user_id, pid)
        transactions = self._client.fetch_all_transactions(start_date, end_date, category_resolver=resolver)
        # Notion non ha la normalizzazione voci di spesa (solo Postgres, per scelta
        # esplicita) — `normalized_name` esiste comunque nel dict, come fallback su
        # `name`, così i chiamanti (es. `/api/analytics/top-merchants`) non devono
        # sapere quale backend è attivo. `label_cluster_id`/`category_id` restano
        # None: senza cluster non c'è nulla da correggere, e la UI nasconde le
        # azioni "Unisci"/"Dividi".
        for t in transactions:
            t.setdefault("normalized_name", t.get("name", ""))
            t.setdefault("label_cluster_id", None)
            t.setdefault("category_id", None)
        return transactions

    def fetch_monthly_balances(self, start_date: date, end_date: date) -> list[dict]:
        return self._client.fetch_monthly_balances(start_date, end_date)

    def fetch_income(self, start_date: date, end_date: date) -> list[dict]:
        """Read Notion incomes with one local category-cache lookup per batch."""
        rows = self._client.fetch_income(start_date, end_date)
        categories_by_name = self._income_category_map()
        pending_replacements = self._pending_income_category_page_replacements()
        for row in rows:
            name = row.get("income_type") or "Altra entrata"
            canonical = self._canonical_income_category_name(name)
            # Notion può contenere valori vecchi e nuovi dopo una sostituzione
            # parziale. Finché l'outbox non è completato, entrambi restano
            # attribuiti alla categoria locale precedente.
            canonical = pending_replacements.get(str(row.get("id") or ""), canonical)
            category = categories_by_name.get(canonical.casefold())
            if category is None:
                category = self._ensure_local_income_category(canonical)
                categories_by_name[canonical.casefold()] = category
            row["income_category"] = category["name"] if category else row.get("income_type")
            row["income_category_id"] = category["id"] if category else None
        return rows

    def get_income_categories(self, include_archived: bool = False) -> list[dict]:
        """The local cache is authoritative even when financial rows live in Notion."""
        if self._store and self._user_id:
            return self._store.get_user_income_categories(self._user_id, include_archived)
        return []

    def get_income_category_names(self, include_archived: bool = False) -> list[str]:
        """Return locally managed names so parser choices match PostgreSQL."""
        if self._store and self._user_id:
            return self._store.get_user_income_category_names(self._user_id, include_archived)
        return []

    def _require_income_category_store(self):
        """Return the local authoritative store or fail explicitly, never silently."""
        if not self._store or not self._user_id:
            raise NotImplementedError("Income categories require the local Expensum store")
        return self._store, str(self._user_id)

    def _resolve_local_income_category(self, name: str) -> dict | None:
        """Resolve the local category DTO by canonical name for a Notion row."""
        canonical = self._canonical_income_category_name(name)
        return self._income_category_map().get(canonical.casefold())

    @staticmethod
    def _canonical_income_category_name(name: str) -> str:
        """Normalize legacy values before comparing local cache entries."""
        from src.income_categories import normalize_income_category_name

        return normalize_income_category_name(name)

    def _income_category_map(self) -> dict[str, dict]:
        """Load the authoritative local catalogue once, indexed case-insensitively."""
        return {
            row["name"].casefold(): row
            for row in self.get_income_categories(include_archived=True)
        }

    def _pending_income_category_page_replacements(self) -> dict[str, str]:
        """Map only snapshot page IDs back to their still-local category."""
        from src.storage.models import IncomeCategoryNotionSyncTask

        if not self._store or not self._user_id:
            return {}
        with self._store._user_session(str(self._user_id)) as session:
            rows = session.query(IncomeCategoryNotionSyncTask).filter_by(
                user_id=str(self._user_id),
            ).all()
            return {
                page_id: row.previous_name
                for row in rows
                for page_id in (row.page_ids or [])
            }

    def _snapshot_income_type_page_ids(self, income_type: str) -> list[str] | None:
        """Read the immutable target set before persisting an outbox task."""
        page_ids = self._client.get_income_type_page_ids(income_type)
        if not isinstance(page_ids, list) or not all(isinstance(page_id, str) for page_id in page_ids):
            return None
        return page_ids

    def _queue_income_category_sync(
        self, category_id: int, operation: str, previous_name: str, next_name: str,
        page_ids: list[str] | None,
    ) -> int:
        """Persist work before touching Notion, so a partial remote update is retryable."""
        from src.storage.models import IncomeCategoryNotionSyncTask

        store, user_id = self._require_income_category_store()
        with store._user_session(user_id) as session:
            task = IncomeCategoryNotionSyncTask(
                user_id=user_id, category_id=category_id, operation=operation,
                previous_name=previous_name, next_name=next_name, page_ids=page_ids,
            )
            session.add(task)
            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()
                raise ValueError("Sincronizzazione categoria entrata già in corso") from error
            return task.id

    def _complete_income_category_sync(self, task_id: int) -> int:
        """Retry and atomically apply one durable Notion reconciliation task."""
        from src.storage.models import (
            IncomeCategoryNotionSyncTask, UserIncomeCategory, UserIncomeCategoryNotionLink,
        )

        store, user_id = self._require_income_category_store()
        with store._user_session(user_id) as session:
            task = session.query(IncomeCategoryNotionSyncTask).filter_by(
                id=task_id, user_id=user_id,
            ).one_or_none()
            if task is None:
                return 0
            operation, category_id = task.operation, task.category_id
            previous_name, next_name, page_ids = task.previous_name, task.next_name, task.page_ids

        # La chiamata remota è fuori dalla transazione DB: il task resta persistito
        # e quindi ogni tentativo successivo riprende esattamente la stessa sostituzione.
        reassigned = (
            self._client.replace_income_type_page_ids(page_ids, previous_name, next_name)
            if page_ids is not None
            else self._client.replace_income_type(previous_name, next_name)
        )

        with store._user_session(user_id) as session:
            task = session.query(IncomeCategoryNotionSyncTask).filter_by(
                id=task_id, user_id=user_id,
            ).one_or_none()
            if task is None:
                return reassigned
            category = session.query(UserIncomeCategory).filter_by(
                id=category_id, user_id=user_id,
            ).one_or_none()
            if operation == "rename" and category is not None:
                category.name = next_name
            elif operation == "delete" and category is not None:
                link = session.query(UserIncomeCategoryNotionLink).filter_by(
                    category_id=category.id,
                ).one_or_none()
                if link is not None:
                    session.delete(link)
                    session.flush()
                session.delete(category)
            session.delete(task)
            session.commit()
        return reassigned

    def _finish_pending_income_category_syncs(self) -> None:
        """Finish older tasks before accepting a new rename or deletion."""
        from src.storage.models import IncomeCategoryNotionSyncTask

        store, user_id = self._require_income_category_store()
        with store._user_session(user_id) as session:
            task_ids = [row.id for row in session.query(IncomeCategoryNotionSyncTask).filter_by(
                user_id=user_id,
            ).order_by(IncomeCategoryNotionSyncTask.id).all()]
        for task_id in task_ids:
            self._complete_income_category_sync(task_id)

    def retry_pending_income_category_syncs(self) -> int:
        """Complete all durable category tasks; invoked by the scheduled retry job."""
        from src.storage.models import IncomeCategoryNotionSyncTask

        store, user_id = self._require_income_category_store()
        with store._user_session(user_id) as session:
            task_ids = [row.id for row in session.query(IncomeCategoryNotionSyncTask).filter_by(
                user_id=user_id,
            ).order_by(IncomeCategoryNotionSyncTask.id).all()]
        for task_id in task_ids:
            self._complete_income_category_sync(task_id)
        return len(task_ids)

    def _ensure_local_income_category(self, name: str) -> dict:
        """Create or reactivate a tenant-owned local category for legacy Notion data."""
        from src.storage.models import UserIncomeCategory

        store, user_id = self._require_income_category_store()
        canonical = self._canonical_income_category_name(name)
        with store._user_session(user_id) as session:
            row = session.query(UserIncomeCategory).filter(
                UserIncomeCategory.user_id == user_id,
                UserIncomeCategory.name.ilike(canonical),
            ).first()
            if row is None:
                row = UserIncomeCategory(user_id=user_id, name=canonical)
                session.add(row)
                session.flush()
            dto = {
                "id": row.id,
                "name": row.name,
                "monthly_budget": float(row.monthly_budget) if row.monthly_budget is not None else None,
                "description": row.description,
                "description_summary": row.description_summary,
                "average": 0.0,
                "archived": False,
            }
            session.commit()
        return dto

    def _owned_local_income_category(self, category_id: int) -> dict:
        """Resolve an ID through the authoritative tenant-scoped local cache."""
        category = next(
            (row for row in self.get_income_categories(include_archived=True)
             if row["id"] == int(category_id)),
            None,
        )
        if category is None:
            raise ValueError("Income category not found")
        return category

    def create_income_category(self, name: str, monthly_budget: float | None = None,
                               description: str | None = None,
                               description_summary: str | None = None) -> dict:
        """Create local category metadata while Notion keeps its existing select."""
        from src.income_categories import normalize_income_category_name
        from src.storage.models import UserIncomeCategory

        store, user_id = self._require_income_category_store()
        canonical = normalize_income_category_name(name)
        with store._user_session(user_id) as session:
            exists = session.query(UserIncomeCategory).filter(
                UserIncomeCategory.user_id == user_id,
                UserIncomeCategory.name.ilike(canonical),
            ).first()
            if exists:
                raise ValueError("Income category already exists")
            row = UserIncomeCategory(user_id=user_id, name=canonical, monthly_budget=monthly_budget,
                                     description=description, description_summary=description_summary)
            session.add(row); session.commit()
        return next(category for category in self.get_income_categories(True) if category["id"] == row.id)

    def update_income_category(self, category_id: int, **fields) -> dict | None:
        """Update local metadata after verifying tenant ownership."""
        from src.income_categories import normalize_income_category_name
        from src.storage.models import UserIncomeCategory

        store, user_id = self._require_income_category_store()
        self._finish_pending_income_category_syncs()
        pending_task_id = None
        with store._user_session(user_id) as session:
            row = session.query(UserIncomeCategory).filter_by(id=category_id, user_id=user_id).first()
            if row is None:
                return None
            if fields.get("name"):
                canonical = normalize_income_category_name(fields["name"])
                duplicate = session.query(UserIncomeCategory).filter(
                    UserIncomeCategory.user_id == user_id,
                    UserIncomeCategory.id != row.id,
                    UserIncomeCategory.name.ilike(canonical),
                ).first()
                if duplicate is not None:
                    raise ValueError("Income category already exists")
                if canonical != row.name:
                    page_ids = self._snapshot_income_type_page_ids(row.name)
                    pending_task_id = self._queue_income_category_sync(
                        row.id, "rename", row.name, canonical,
                        page_ids,
                    )
                else:
                    row.name = canonical
            for name in ("monthly_budget", "description", "description_summary"):
                if name in fields:
                    setattr(row, name, fields[name])
            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()
                raise ValueError("Income category already exists") from error
        if pending_task_id is not None:
            self._complete_income_category_sync(pending_task_id)
        return next(category for category in self.get_income_categories(True) if category["id"] == category_id)

    def delete_income_category(self, category_id: int) -> dict | None:
        """Delete an income category after moving legacy Notion rows to fallback."""
        from src.storage.models import UserIncomeCategory, UserIncomeCategoryNotionLink

        store, user_id = self._require_income_category_store()
        self._finish_pending_income_category_syncs()
        with store._user_session(user_id) as session:
            row = session.query(UserIncomeCategory).filter_by(id=category_id, user_id=user_id).first()
            if row is None:
                return None
            if row.name.casefold() == "altra entrata":
                raise ValueError("La categoria «Altra entrata» non può essere eliminata")
            fallback = session.query(UserIncomeCategory).filter(
                UserIncomeCategory.user_id == user_id,
                UserIncomeCategory.name.ilike("Altra entrata"),
            ).first()
            if fallback is None:
                fallback = UserIncomeCategory(user_id=user_id, name="Altra entrata")
                session.add(fallback)
                session.commit()
            page_ids = self._snapshot_income_type_page_ids(row.name)
            task_id = self._queue_income_category_sync(
                row.id, "delete", row.name, fallback.name,
                page_ids,
            )
        reassigned = self._complete_income_category_sync(task_id)
        return {"incomes": reassigned}

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
