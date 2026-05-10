"""
postgres_storage.py — Implementazione FinancialStorage su PostgreSQL/SQLite (schema 3NF).

Invarianti:
- `Account.opening_balance` è il fatto persistito; `current_balance` è calcolato on-read.
- `Expense.category_id` è la FK authoritative; `category_name` è solo un bridge legacy.
- `MonthlyBalance` non esiste per backend Postgres: `fetch_monthly_balances` aggrega on-read.
- `get_or_create_monthly_balance` ritorna sempre None (compatibilità con FinancialStorage).
"""

from datetime import date, datetime

from sqlalchemy import func, text
from sqlalchemy.orm import Session

import uuid

from src.storage.base import FinancialStorage
from src.storage.models import Account, UserCategory, UserCategoryNotionLink, Expense, Income, Subscription, SavedReport


class PostgresStorage(FinancialStorage):
    """Implementazione di FinancialStorage su PostgreSQL/SQLite via SQLAlchemy."""

    def __init__(self, session: Session, user_id: str) -> None:
        self._session = session
        self._user_id = user_id

    # ------------------------------------------------------------------ helpers

    def _resolve_category_id(self, category_name: str) -> int | None:
        """Risolve category_name -> category_id per l'utente corrente.

        Se la categoria non esiste localmente, la crea al volo (per retrocompatibilità
        con flussi che ancora passano il nome stringa).
        """
        cat = self._session.query(UserCategory).filter(
            UserCategory.user_id == self._user_id,
            func.lower(UserCategory.name) == (category_name or "").lower(),
        ).first()
        if cat:
            return cat.id
        # Crea la categoria al volo per non perdere la spesa
        new_cat = UserCategory(user_id=self._user_id, name=category_name)
        self._session.add(new_cat)
        self._session.flush()
        return new_cat.id

    def _compute_balance(self, account: Account) -> float:
        """Calcola il saldo corrente: opening_balance + entrate - uscite."""
        total_income = self._session.query(
            func.coalesce(func.sum(Income.amount), 0)
        ).filter(
            Income.user_id == self._user_id,
            Income.account_id == account.id,
        ).scalar() or 0.0

        total_expense = self._session.query(
            func.coalesce(func.sum(Expense.amount), 0)
        ).filter(
            Expense.user_id == self._user_id,
            Expense.account_id == account.id,
        ).scalar() or 0.0

        return (account.opening_balance or 0.0) + total_income - total_expense

    # ------------------------------------------------------------------ categories

    def get_category_names(self) -> list[str]:
        """Ritorna i nomi di tutte le categorie dell'utente."""
        rows = self._session.query(UserCategory).filter(
            UserCategory.user_id == self._user_id
        ).all()
        return [r.name for r in rows]

    def create_category(self, name: str, monthly_budget: float | None = None) -> dict:
        """Crea una nuova categoria per l'utente."""
        category = UserCategory(user_id=self._user_id, name=name, monthly_budget=monthly_budget)
        self._session.add(category)
        self._session.commit()
        return {"id": category.id, "name": category.name, "monthly_budget": category.monthly_budget}

    def get_categories(self) -> list[dict]:
        """Restituisce id, nome, budget mensile e average di tutte le categorie dell'utente."""
        rows = self._session.query(UserCategory, UserCategoryNotionLink).outerjoin(
            UserCategoryNotionLink,
            UserCategoryNotionLink.category_id == UserCategory.id,
        ).filter(
            UserCategory.user_id == self._user_id
        ).all()
        return [
            {
                "id": cat.id,
                "name": cat.name,
                "monthly_budget": cat.monthly_budget,
                "average": link.average if link else 0.0,
            }
            for cat, link in rows
        ]

    def update_category(self, cat_id: int, name: str | None = None,
                        monthly_budget: float | None = None) -> dict | None:
        """Aggiorna nome o budget di una categoria."""
        row = self._session.query(UserCategory).filter(
            UserCategory.id == cat_id,
            UserCategory.user_id == self._user_id,
        ).first()
        if not row:
            return None
        if name is not None:
            row.name = name
        if monthly_budget is not None:
            row.monthly_budget = monthly_budget
        self._session.commit()
        return {"id": row.id, "name": row.name, "monthly_budget": row.monthly_budget}

    def delete_category(self, cat_id: int) -> bool:
        """Elimina una categoria (e il relativo link Notion se presente)."""
        row = self._session.query(UserCategory).filter(
            UserCategory.id == cat_id,
            UserCategory.user_id == self._user_id,
        ).first()
        if not row:
            return False
        # Elimina link Notion se presente
        link = self._session.query(UserCategoryNotionLink).filter_by(category_id=cat_id).first()
        if link:
            self._session.delete(link)
        self._session.delete(row)
        self._session.commit()
        return True

    # ------------------------------------------------------------------ expenses

    def create_expense(
        self,
        expense_date: date,
        amount: float,
        name: str,
        category_name: str,
        account_id: str,
        monthly_balance_id: str | None = None,  # ignorato per Postgres
    ) -> dict:
        """Crea una spesa. `monthly_balance_id` è ignorato (Postgres non usa MonthlyBalance).

        `category_name` viene risolto a `category_id` via query locale.
        `account_id` può essere un intero o stringa numerica.
        """
        # Risolvi category_name -> category_id
        resolved_category_id = self._resolve_category_id(category_name)

        # Normalizza account_id a intero
        try:
            acc_id_int = int(account_id) if account_id is not None else None
        except (ValueError, TypeError):
            acc_id_int = None

        expense = Expense(
            user_id=self._user_id,
            expense_date=expense_date,
            amount=amount,
            name=name,
            category_name=category_name,   # bridge legacy, non usato applicativamente
            category_id=resolved_category_id,
            account_id=acc_id_int,
        )
        self._session.add(expense)
        self._session.commit()
        return {
            "id": expense.id,
            "date": expense.expense_date,
            "amount": expense.amount,
            "name": expense.name,
            "category": category_name,
            "account_id": expense.account_id,
        }

    def fetch_all_transactions(self, start_date: date, end_date: date) -> list[dict]:
        """Restituisce tutte le spese nell'intervallo."""
        rows = self._session.query(Expense, UserCategory).outerjoin(
            UserCategory, UserCategory.id == Expense.category_id
        ).filter(
            Expense.user_id == self._user_id,
            Expense.expense_date >= start_date,
            Expense.expense_date <= end_date,
        ).all()
        return [
            {
                "date": exp.expense_date,
                "amount": exp.amount,
                "name": exp.name,
                "category": cat.name if cat else (exp.category_name or ""),
                "account_id": exp.account_id,
            }
            for exp, cat in rows
        ]

    # ------------------------------------------------------------------ income

    def create_income(
        self,
        income_date: date,
        amount: float,
        name: str,
        account_id: str,
        income_type: str | None = None,
    ) -> dict:
        """Crea un'entrata. Il saldo del conto è calcolato on-read, non persistito."""
        try:
            acc_id_int = int(account_id) if account_id is not None else None
        except (ValueError, TypeError):
            acc_id_int = None

        income = Income(
            user_id=self._user_id,
            income_date=income_date,
            amount=amount,
            name=name,
            account_id=acc_id_int,
            income_type=income_type,
        )
        self._session.add(income)
        self._session.commit()
        return {
            "id": income.id,
            "date": income.income_date,
            "amount": income.amount,
            "name": income.name,
            "account_id": income.account_id,
            "income_type": income.income_type,
        }

    def fetch_income(self, start_date: date, end_date: date) -> list[dict]:
        """Restituisce tutte le entrate nell'intervallo."""
        rows = self._session.query(Income).filter(
            Income.user_id == self._user_id,
            Income.income_date >= start_date,
            Income.income_date <= end_date,
        ).all()
        return [
            {
                "date": r.income_date,
                "amount": r.amount,
                "name": r.name,
                "account_id": r.account_id,
                "income_type": r.income_type,
            }
            for r in rows
        ]

    # ------------------------------------------------------------------ accounts

    def fetch_accounts(self) -> list[dict]:
        """Restituisce i conti dell'utente con saldo calcolato on-read."""
        rows = self._session.query(Account).filter(
            Account.user_id == self._user_id
        ).all()
        return [
            {
                "id": r.id,
                "name": r.name,
                "current_balance": self._compute_balance(r),
                "opening_balance": r.opening_balance,
                "currency": r.currency,
                "account_type": r.account_type,
            }
            for r in rows
        ]

    def create_account(self, name: str, initial_balance: float = 0.0,
                       account_type: str | None = None) -> dict:
        """Crea un conto. `initial_balance` diventa `opening_balance`."""
        account = Account(
            user_id=self._user_id,
            name=name,
            opening_balance=initial_balance,
            account_type=account_type,
        )
        self._session.add(account)
        self._session.commit()
        return {
            "id": account.id,
            "name": account.name,
            "balance": account.opening_balance,
            "account_type": account.account_type,
        }

    def update_account(self, account_id: int, name: str | None = None,
                       balance: float | None = None,
                       account_type: str | None = None) -> dict | None:
        """Aggiorna un conto. Se `balance` viene passato, aggiorna `opening_balance`
        (retrocompatibilità con chiamanti che ancora usano il campo `balance`).
        """
        row = self._session.query(Account).filter(
            Account.id == account_id,
            Account.user_id == self._user_id,
        ).first()
        if not row:
            return None
        if name is not None:
            row.name = name
        if balance is not None:
            row.opening_balance = balance
        if account_type is not None:
            row.account_type = account_type
        self._session.commit()
        return {
            "id": row.id,
            "name": row.name,
            "balance": self._compute_balance(row),
            "account_type": row.account_type,
        }

    def delete_account(self, account_id: int) -> bool:
        """Elimina un conto."""
        row = self._session.query(Account).filter(
            Account.id == account_id,
            Account.user_id == self._user_id,
        ).first()
        if not row:
            return False
        self._session.delete(row)
        self._session.commit()
        return True

    # ------------------------------------------------------------------ monthly balances

    def get_or_create_monthly_balance(self, target_date: date) -> str | None:
        """Postgres non usa Monthly Balance — ritorna sempre None.

        La firma è mantenuta per compatibilità con FinancialStorage.
        I bilanci mensili sono calcolati on-read da `fetch_monthly_balances`.
        """
        return None

    def fetch_monthly_balances(self, start_date: date, end_date: date) -> list[dict]:
        """Aggrega entrate e uscite per mese nell'intervallo (on-read, senza tabella dedicata)."""
        # Entrate per mese
        income_rows = self._session.execute(
            text(
                "SELECT strftime('%Y-%m-01', income_date) AS month, SUM(amount) AS total "
                "FROM incomes "
                "WHERE user_id = :uid AND income_date >= :start AND income_date <= :end "
                "GROUP BY month"
            ),
            {"uid": self._user_id, "start": start_date.isoformat(), "end": end_date.isoformat()},
        ).mappings().all()

        # Uscite per mese
        expense_rows = self._session.execute(
            text(
                "SELECT strftime('%Y-%m-01', expense_date) AS month, SUM(amount) AS total "
                "FROM expenses "
                "WHERE user_id = :uid AND expense_date >= :start AND expense_date <= :end "
                "GROUP BY month"
            ),
            {"uid": self._user_id, "start": start_date.isoformat(), "end": end_date.isoformat()},
        ).mappings().all()

        income_by_month = {r["month"]: r["total"] for r in income_rows}
        expense_by_month = {r["month"]: r["total"] for r in expense_rows}

        from calendar import month_name as _month_name
        all_months = sorted(set(income_by_month) | set(expense_by_month))
        result = []
        for month_str in all_months:
            inc = income_by_month.get(month_str, 0.0)
            exp = expense_by_month.get(month_str, 0.0)
            d = datetime.strptime(month_str, "%Y-%m-%d").date()
            result.append({
                "year": d.year,
                "month": d.month,
                "label": f"{_month_name[d.month]} {d.year}",
                "net_savings": inc - exp,
            })
        return result

    # ------------------------------------------------------------------ subscriptions

    def fetch_subscriptions(self) -> list[dict]:
        """Restituisce tutti gli abbonamenti dell'utente."""
        rows = self._session.query(Subscription).filter(
            Subscription.user_id == self._user_id
        ).all()
        return [
            {
                "id": r.id,
                "name": r.name,
                "amount": r.amount,
                "last_billed": r.last_billed.isoformat() if r.last_billed else None,
                "sub_type": r.sub_type,
                "account_id": r.account_id,
                "category_id": r.category_id,
            }
            for r in rows
        ]

    def create_subscription(
        self,
        name: str,
        amount: float | None = None,
        last_billed: str | None = None,
        sub_type: str | None = None,
        account_id: int | None = None,
        category_id: int | None = None,
    ) -> dict:
        """Crea un abbonamento."""
        parsed_date = None
        if last_billed:
            parsed_date = datetime.strptime(last_billed, "%Y-%m-%d").date()
        subscription = Subscription(
            user_id=self._user_id,
            name=name,
            amount=amount,
            last_billed=parsed_date,
            sub_type=sub_type,
            account_id=account_id,
            category_id=category_id,
        )
        self._session.add(subscription)
        self._session.commit()
        return {
            "id": subscription.id,
            "name": subscription.name,
            "amount": subscription.amount,
            "last_billed": subscription.last_billed.isoformat() if subscription.last_billed else None,
            "sub_type": subscription.sub_type,
            "account_id": subscription.account_id,
            "category_id": subscription.category_id,
        }

    def update_subscription(
        self,
        sub_id: int,
        name: str | None = None,
        amount: float | None = None,
        last_billed: date | None = None,
        sub_type: str | None = None,
        account_id: int | None = None,
        category_id: int | None = None,
    ) -> dict | None:
        """Aggiorna un abbonamento."""
        row = self._session.query(Subscription).filter(
            Subscription.id == sub_id,
            Subscription.user_id == self._user_id,
        ).first()
        if not row:
            return None
        if name is not None:
            row.name = name
        if amount is not None:
            row.amount = amount
        if last_billed is not None:
            row.last_billed = last_billed
        if sub_type is not None:
            row.sub_type = sub_type
        if account_id is not None:
            row.account_id = account_id
        if category_id is not None:
            row.category_id = category_id
        self._session.commit()
        return {
            "id": row.id,
            "name": row.name,
            "amount": row.amount,
            "last_billed": row.last_billed.isoformat() if row.last_billed else None,
            "sub_type": row.sub_type,
            "account_id": row.account_id,
            "category_id": row.category_id,
        }

    def delete_subscription(self, sub_id: int) -> bool:
        """Elimina un abbonamento."""
        row = self._session.query(Subscription).filter(
            Subscription.id == sub_id,
            Subscription.user_id == self._user_id,
        ).first()
        if not row:
            return False
        self._session.delete(row)
        self._session.commit()
        return True

    # ------------------------------------------------------------------ reports

    def save_report(
        self,
        user_id: str,
        report_type: str,
        report_date: date,
        text_content: str,
        report_data: dict | None = None,
    ) -> str:
        """Salva il report nel DB e restituisce il share_token UUID.

        Fa upsert per (user_id, report_type, report_date): se esiste già un report
        per quella combinazione, aggiorna testo e dati mantenendo lo stesso token.
        Per i report mensili report_date è sempre il primo giorno del mese target,
        quindi più piani generati nello stesso mese sovrascrivono lo stesso record.
        """
        existing = self._session.query(SavedReport).filter(
            SavedReport.user_id == user_id,
            SavedReport.report_type == report_type,
            SavedReport.report_date == report_date,
        ).first()

        if existing:
            existing.text_content = text_content
            existing.report_data = report_data
            self._session.commit()
            return existing.share_token

        token = str(uuid.uuid4())
        row = SavedReport(
            user_id=user_id,
            report_type=report_type,
            report_date=report_date,
            share_token=token,
            text_content=text_content,
            report_data=report_data,
        )
        self._session.add(row)
        self._session.commit()
        return token

    def get_report_by_token(self, share_token: str) -> dict | None:
        """Recupera un report tramite share_token pubblico."""
        row = self._session.query(SavedReport).filter(
            SavedReport.share_token == share_token
        ).first()
        if not row:
            return None
        return self._report_to_dict(row)

    def get_reports_for_user(self, user_id: str, limit: int = 24) -> list[dict]:
        """Lista report dell'utente, ordinati per data decrescente."""
        rows = (
            self._session.query(SavedReport)
            .filter(SavedReport.user_id == user_id)
            .order_by(SavedReport.report_date.desc())
            .limit(limit)
            .all()
        )
        return [self._report_to_dict(r) for r in rows]

    @staticmethod
    def _report_to_dict(row: SavedReport) -> dict:
        return {
            "id": row.id,
            "user_id": row.user_id,
            "report_type": row.report_type,
            "report_date": row.report_date.isoformat() if row.report_date else None,
            "share_token": row.share_token,
            "text_content": row.text_content,
            "report_data": row.report_data,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }