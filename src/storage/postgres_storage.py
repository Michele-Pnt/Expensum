"""
postgres_storage.py — Implementazione FinancialStorage su PostgreSQL/SQLite (schema 3NF).

Invarianti:
- `Account.opening_balance` è il fatto persistito; `current_balance` è calcolato on-read.
- `Expense.category_id` è la FK authoritative; `category_name` è solo un bridge legacy.
- `MonthlyBalance` non esiste per backend Postgres: `fetch_monthly_balances` aggrega on-read.
- `get_or_create_monthly_balance` ritorna sempre None (compatibilità con FinancialStorage).
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, text
from sqlalchemy.orm import Session

import uuid

from src.billing_utils import get_occurrences_in_range
from src.storage.base import FinancialStorage
from src.storage.models import (
    Account, UserCategory, UserCategoryNotionLink, CategoryCandidate, Expense, Income,
    Subscription, SavedReport, Transfer, SavingsGoal, SavingsGoalEvaluation,
)
from src.storage import rls  # registra il listener RLS e fornisce bind_user
from config import Config


def _d(v) -> float:
    """Converte Decimal (o qualsiasi numero) in float. Sicuro su None."""
    if v is None:
        return 0.0
    return float(v)


class PostgresStorage(FinancialStorage):
    """Implementazione di FinancialStorage su PostgreSQL/SQLite via SQLAlchemy."""

    def __init__(self, session: Session, user_id: str) -> None:
        self._session = session
        self._user_id = user_id
        # Alimenta la RLS: ogni transazione di questa sessione imposterà
        # app.user_id = user_id, così su Postgres il DB stesso filtra il tenant.
        # No-op su SQLite. Difesa aggiuntiva oltre al filtro applicativo WHERE user_id.
        rls.bind_user(session, user_id)

    # ------------------------------------------------------------------ helpers

    def _commit(self) -> None:
        """Commit con rollback automatico in caso di errore.

        Senza il rollback, un errore (es. IntegrityError su un vincolo unique)
        lascia la transazione in stato "aborted": ogni query successiva sulla
        stessa sessione fallisce finché non arriva un rollback esplicito. Dato
        che la sessione viene riusata tra richieste (cache in bot.py), questo
        "avvelenava" silenziosamente tutte le operazioni successive dell'utente.
        """
        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

    def _resolve_category_id(self, category_name: str) -> int | None:
        """Risolve category_name -> category_id per l'utente corrente.

        Se la categoria esiste ma è archiviata la **riattiva**: creare un duplicato
        violerebbe `uq_user_categories_user_name` e farebbe fallire il salvataggio
        della spesa. Semanticamente è anche la cosa giusta — se l'utente registra di
        nuovo una spesa lì, quella categoria è tornata in uso.

        Se non esiste affatto, la crea al volo (retrocompatibilità con i flussi che
        passano ancora il nome come stringa).
        """
        cat = self._session.query(UserCategory).filter(
            UserCategory.user_id == self._user_id,
            func.lower(UserCategory.name) == (category_name or "").lower(),
        ).first()
        if cat:
            if cat.archived_at is not None:
                cat.archived_at = None
            return cat.id
        # Crea la categoria al volo per non perdere la spesa
        new_cat = UserCategory(user_id=self._user_id, name=category_name)
        self._session.add(new_cat)
        try:
            self._session.flush()
        except Exception:
            self._session.rollback()
            raise
        return new_cat.id

    def _compute_balance(self, account: Account) -> Decimal:
        """Calcola il saldo corrente: opening_balance + entrate - uscite + trasferimenti in - trasferimenti out."""
        total_income = self._session.query(
            func.coalesce(func.sum(Income.amount), 0)
        ).filter(
            Income.user_id == self._user_id,
            Income.account_id == account.id,
        ).scalar() or 0

        total_expense = self._session.query(
            func.coalesce(func.sum(Expense.amount), 0)
        ).filter(
            Expense.user_id == self._user_id,
            Expense.account_id == account.id,
        ).scalar() or 0

        total_transfer_in = self._session.query(
            func.coalesce(func.sum(Transfer.amount), 0)
        ).filter(
            Transfer.user_id == self._user_id,
            Transfer.to_account_id == account.id,
        ).scalar() or 0

        total_transfer_out = self._session.query(
            func.coalesce(func.sum(Transfer.amount), 0)
        ).filter(
            Transfer.user_id == self._user_id,
            Transfer.from_account_id == account.id,
        ).scalar() or 0

        opening = account.opening_balance if account.opening_balance is not None else Decimal(0)
        return (
            Decimal(str(opening))
            + Decimal(str(total_income))
            - Decimal(str(total_expense))
            + Decimal(str(total_transfer_in))
            - Decimal(str(total_transfer_out))
        )

    # ------------------------------------------------------------------ categories

    def _categories_query(self, include_archived: bool = False):
        """Query base sulle categorie dell'utente, archiviate escluse per default.

        Default fail-safe: chi sceglie una categoria per una nuova spesa non deve
        vedere le archiviate; chi legge storico o aggregati passa esplicitamente
        `include_archived=True`.
        """
        query = self._session.query(UserCategory).filter(
            UserCategory.user_id == self._user_id
        )
        if not include_archived:
            query = query.filter(UserCategory.archived_at.is_(None))
        return query

    def get_category_names(self, include_archived: bool = False) -> list[str]:
        """Ritorna i nomi delle categorie dell'utente (archiviate escluse per default)."""
        names = [r.name for r in self._categories_query(include_archived).all()]
        self._commit()
        return names

    def create_category(
        self, name: str, monthly_budget: float | None = None,
        description: str | None = None, description_summary: str | None = None,
    ) -> dict:
        """Crea una nuova categoria per l'utente."""
        category = UserCategory(
            user_id=self._user_id, name=name, monthly_budget=monthly_budget,
            description=description, description_summary=description_summary,
        )
        self._session.add(category)
        self._commit()
        return {
            "id": category.id, "name": category.name, "monthly_budget": category.monthly_budget,
            "description": category.description, "description_summary": category.description_summary,
        }

    def get_categories(self, include_archived: bool = False) -> list[dict]:
        """id, nome, budget, descrizione e average delle categorie (archiviate escluse per default)."""
        query = self._session.query(UserCategory, UserCategoryNotionLink).outerjoin(
            UserCategoryNotionLink,
            UserCategoryNotionLink.category_id == UserCategory.id,
        ).filter(
            UserCategory.user_id == self._user_id
        )
        if not include_archived:
            query = query.filter(UserCategory.archived_at.is_(None))
        result = [
            {
                "id": cat.id,
                "name": cat.name,
                "monthly_budget": _d(cat.monthly_budget) if cat.monthly_budget is not None else None,
                "description": cat.description,
                "description_summary": cat.description_summary,
                "average": _d(link.average) if link else 0.0,
                "archived": cat.archived_at is not None,
            }
            for cat, link in query.all()
        ]
        self._commit()
        return result

    def update_category(
        self, cat_id: int, name: str | None = None, monthly_budget: float | None = None,
        description: str | None = None, description_summary: str | None = None,
    ) -> dict | None:
        """Aggiorna nome, budget e/o descrizione di una categoria."""
        row = self._session.query(UserCategory).filter(
            UserCategory.id == cat_id,
            UserCategory.user_id == self._user_id,
        ).first()
        if not row:
            self._commit()
            return None
        if name is not None:
            row.name = name
        if monthly_budget is not None:
            row.monthly_budget = monthly_budget
        if description is not None:
            row.description = description
            row.description_summary = description_summary
        self._commit()
        return {
            "id": row.id, "name": row.name, "monthly_budget": row.monthly_budget,
            "description": row.description, "description_summary": row.description_summary,
        }

    def _get_own_category(self, cat_id: int) -> UserCategory | None:
        return self._session.query(UserCategory).filter(
            UserCategory.id == cat_id,
            UserCategory.user_id == self._user_id,
        ).first()

    def get_dismissed_budget_suggestions(self) -> set[int]:
        """Categorie per cui l'utente ha già rifiutato il suggerimento di budget."""
        rows = self._categories_query(include_archived=True).filter(
            UserCategory.budget_suggestion_dismissed_at.isnot(None)
        ).all()
        ids = {r.id for r in rows}
        self._commit()
        return ids

    def dismiss_budget_suggestion(self, cat_id: int) -> bool:
        """Marca il suggerimento di budget come rifiutato. False se la categoria non esiste."""
        row = self._get_own_category(cat_id)
        if not row:
            self._commit()
            return False
        row.budget_suggestion_dismissed_at = datetime.utcnow()
        self._commit()
        return True

    def get_category_usage(self, cat_id: int) -> dict[str, int] | None:
        """Conteggio dei record che dipendono dalla categoria.

        Serve alla UI per chiedere conferma informata ("questa categoria ha 42
        spese, verranno spostate su «Altro»") prima di cancellare. None se la
        categoria non esiste o non è dell'utente.
        """
        if not self._get_own_category(cat_id):
            self._commit()
            return None
        usage = {
            "expenses": self._session.query(Expense).filter(
                Expense.user_id == self._user_id, Expense.category_id == cat_id,
            ).count(),
            "subscriptions": self._session.query(Subscription).filter(
                Subscription.user_id == self._user_id, Subscription.category_id == cat_id,
            ).count(),
            "goals": self._session.query(SavingsGoal).filter(
                SavingsGoal.user_id == self._user_id, SavingsGoal.category_id == cat_id,
            ).count(),
        }
        self._commit()
        return usage

    def set_category_archived(self, cat_id: int, archived: bool) -> dict | None:
        """Archivia o ripristina una categoria. None se non esiste."""
        row = self._get_own_category(cat_id)
        if not row:
            self._commit()
            return None
        row.archived_at = datetime.utcnow() if archived else None
        self._commit()
        return {"id": row.id, "name": row.name, "archived": row.archived_at is not None}

    def delete_category(self, cat_id: int, reassign_to: int | None = None) -> dict | None:
        """Elimina una categoria riassegnando i record dipendenti.

        Le foreign key verso `user_categories` sono RESTRICT: senza riassegnare i
        dipendenti il commit fallisce con ForeignKeyViolation. Tutto avviene in una
        sola transazione — o si riassegna e si cancella, o rollback totale.

        Args:
            cat_id: categoria da eliminare.
            reassign_to: categoria di destinazione. Se None i dipendenti vengono
                spostati sulla categoria di fallback ("Altro"), creata se assente.

        Returns:
            Il conteggio dei record riassegnati, o None se la categoria non esiste.

        Raises:
            ValueError: se `reassign_to` coincide con `cat_id` o non appartiene
                all'utente.
        """
        row = self._get_own_category(cat_id)
        if not row:
            self._commit()
            return None

        if reassign_to is not None:
            if reassign_to == cat_id:
                raise ValueError("La categoria di destinazione non può essere quella da eliminare")
            target = self._get_own_category(reassign_to)
            if not target:
                raise ValueError("Categoria di destinazione inesistente")
        else:
            target = self._ensure_fallback_category(exclude_id=cat_id)

        reassigned = {
            "expenses": self._session.query(Expense).filter(
                Expense.user_id == self._user_id, Expense.category_id == cat_id,
            ).update({"category_id": target.id, "category_name": target.name},
                     synchronize_session=False),
            "subscriptions": self._session.query(Subscription).filter(
                Subscription.user_id == self._user_id, Subscription.category_id == cat_id,
            ).update({"category_id": target.id}, synchronize_session=False),
            "goals": self._session.query(SavingsGoal).filter(
                SavingsGoal.user_id == self._user_id, SavingsGoal.category_id == cat_id,
            ).update({"category_id": target.id}, synchronize_session=False),
        }
        # I candidati non sono dati dell'utente ma stato interno del matcher: si
        # riassegnano al fallback, non si conteggiano nella risposta.
        self._session.query(CategoryCandidate).filter(
            CategoryCandidate.user_id == self._user_id,
            CategoryCandidate.fallback_category_id == cat_id,
        ).update({"fallback_category_id": target.id}, synchronize_session=False)
        self._session.query(CategoryCandidate).filter(
            CategoryCandidate.user_id == self._user_id,
            CategoryCandidate.promoted_category_id == cat_id,
        ).update({"promoted_category_id": target.id}, synchronize_session=False)

        link = self._session.query(UserCategoryNotionLink).filter_by(category_id=cat_id).first()
        if link:
            self._session.delete(link)
        self._session.delete(row)
        self._commit()
        return reassigned

    def _ensure_fallback_category(self, exclude_id: int | None = None) -> UserCategory:
        """Categoria di fallback ("Altro"), creata se non esiste. Mai archiviata."""
        fallback_name = Config.CATEGORY_FALLBACK_NAME
        row = self._session.query(UserCategory).filter(
            UserCategory.user_id == self._user_id,
            func.lower(UserCategory.name) == fallback_name.lower(),
        ).first()
        if row and row.id != exclude_id:
            if row.archived_at is not None:
                row.archived_at = None
            return row
        # Il fallback stesso è la categoria in cancellazione (o non esiste): ne serve
        # una nuova con un nome che non collida con lo unique constraint.
        name = fallback_name if not row else f"{fallback_name} (ripristinata)"
        created = UserCategory(user_id=self._user_id, name=name)
        self._session.add(created)
        self._session.flush()
        return created

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
        self._commit()
        return {
            "id": expense.id,
            "date": expense.expense_date,
            "amount": _d(expense.amount),
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
        result = [
            {
                "id": exp.id,
                "date": exp.expense_date,
                "amount": _d(exp.amount),
                "name": exp.name,
                "category": cat.name if cat else (exp.category_name or ""),
                "account_id": exp.account_id,
                "created_at": exp.created_at.isoformat() if exp.created_at else None,
            }
            for exp, cat in rows
        ]
        self._commit()
        return result

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
        self._commit()
        return {
            "id": income.id,
            "date": income.income_date,
            "amount": _d(income.amount),
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
        result = [
            {
                "id": r.id,
                "date": r.income_date,
                "amount": _d(r.amount),
                "name": r.name,
                "account_id": r.account_id,
                "income_type": r.income_type,
            }
            for r in rows
        ]
        self._commit()
        return result

    # ------------------------------------------------------------------ accounts

    def fetch_accounts(self) -> list[dict]:
        """Restituisce i conti dell'utente con saldo calcolato on-read."""
        rows = self._session.query(Account).filter(
            Account.user_id == self._user_id
        ).all()
        result = [
            {
                "id": r.id,
                "name": r.name,
                "current_balance": _d(self._compute_balance(r)),
                "opening_balance": _d(r.opening_balance),
                "currency": r.currency,
                "account_type": r.account_type,
            }
            for r in rows
        ]
        self._commit()
        return result

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
        self._commit()
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
            self._commit()
            return None
        if name is not None:
            row.name = name
        if balance is not None:
            row.opening_balance = balance
        if account_type is not None:
            row.account_type = account_type
        self._commit()
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
            self._commit()
            return False
        self._session.delete(row)
        self._commit()
        return True

    # ------------------------------------------------------------------ transfers

    def create_transfer(
        self,
        transfer_date: date,
        amount: float,
        from_account_id: str,
        to_account_id: str,
        name: str | None = None,
    ) -> dict:
        """Crea un trasferimento tra due conti dello stesso utente."""
        from_id_int = int(from_account_id)
        to_id_int = int(to_account_id)
        if from_id_int == to_id_int:
            raise ValueError("Il conto di origine e di destinazione devono essere diversi")

        transfer = Transfer(
            user_id=self._user_id,
            from_account_id=from_id_int,
            to_account_id=to_id_int,
            amount=abs(float(amount)),
            transfer_date=transfer_date,
            name=name,
        )
        self._session.add(transfer)
        self._commit()
        return {
            "id": transfer.id,
            "date": transfer.transfer_date,
            "amount": _d(transfer.amount),
            "from_account_id": transfer.from_account_id,
            "to_account_id": transfer.to_account_id,
            "name": transfer.name,
        }

    def fetch_transfers(self, start_date: date, end_date: date) -> list[dict]:
        """Restituisce tutti i trasferimenti nell'intervallo."""
        rows = self._session.query(Transfer).filter(
            Transfer.user_id == self._user_id,
            Transfer.transfer_date >= start_date,
            Transfer.transfer_date <= end_date,
        ).all()
        result = [
            {
                "id": r.id,
                "date": r.transfer_date,
                "amount": _d(r.amount),
                "from_account_id": r.from_account_id,
                "to_account_id": r.to_account_id,
                "name": r.name,
            }
            for r in rows
        ]
        self._commit()
        return result

    # ------------------------------------------------------------------ monthly balances

    def get_or_create_monthly_balance(self, target_date: date) -> str | None:
        """Postgres non usa Monthly Balance — ritorna sempre None.

        La firma è mantenuta per compatibilità con FinancialStorage.
        I bilanci mensili sono calcolati on-read da `fetch_monthly_balances`.
        """
        return None

    def _month_trunc_sql(self, date_col: str) -> str:
        """Ritorna l'espressione SQL per troncare una data al primo del mese, dialect-aware."""
        dialect = self._session.get_bind().dialect.name
        if dialect == "postgresql":
            return f"TO_CHAR(DATE_TRUNC('month', {date_col}), 'YYYY-MM-DD')"
        return f"strftime('%Y-%m-01', {date_col})"

    def fetch_monthly_balances(self, start_date: date, end_date: date) -> list[dict]:
        """Aggrega entrate e uscite per mese nell'intervallo (on-read, senza tabella dedicata)."""
        from calendar import month_name as _month_name

        inc_month = self._month_trunc_sql("income_date")
        exp_month = self._month_trunc_sql("expense_date")

        income_rows = self._session.execute(
            text(
                f"SELECT {inc_month} AS month, SUM(amount) AS total "
                "FROM incomes "
                "WHERE user_id = :uid AND income_date >= :start AND income_date <= :end "
                "GROUP BY month"
            ),
            {"uid": self._user_id, "start": start_date.isoformat(), "end": end_date.isoformat()},
        ).mappings().all()

        expense_rows = self._session.execute(
            text(
                f"SELECT {exp_month} AS month, SUM(amount) AS total "
                "FROM expenses "
                "WHERE user_id = :uid AND expense_date >= :start AND expense_date <= :end "
                "GROUP BY month"
            ),
            {"uid": self._user_id, "start": start_date.isoformat(), "end": end_date.isoformat()},
        ).mappings().all()

        income_by_month = {r["month"]: r["total"] for r in income_rows}
        expense_by_month = {r["month"]: r["total"] for r in expense_rows}

        all_months = sorted(set(income_by_month) | set(expense_by_month))
        result = []
        for month_str in all_months:
            inc = float(income_by_month.get(month_str) or 0.0)
            exp = float(expense_by_month.get(month_str) or 0.0)
            d = datetime.strptime(month_str, "%Y-%m-%d").date()
            result.append({
                "year": d.year,
                "month": d.month,
                "label": f"{_month_name[d.month]} {d.year}",
                "net_savings": inc - exp,
            })
        self._commit()
        return result

    # ------------------------------------------------------------------ subscriptions

    def fetch_subscriptions(self) -> list[dict]:
        """Restituisce tutti gli abbonamenti dell'utente."""
        rows = self._session.query(Subscription).filter(
            Subscription.user_id == self._user_id
        ).all()
        result = [
            {
                "id": r.id,
                "name": r.name,
                "amount": _d(r.amount),
                "last_billed": r.last_billed.isoformat() if r.last_billed else None,
                "sub_type": r.sub_type,
                "account_id": r.account_id,
                "category_id": r.category_id,
            }
            for r in rows
        ]
        self._commit()
        return result

    def create_subscription(
        self,
        name: str,
        amount: float | None = None,
        last_billed: str | None = None,
        sub_type: str | None = None,
        account_id: int | None = None,
        category_id: int | None = None,
        category_name: str | None = None,
    ) -> dict:
        """Crea un abbonamento.

        `category_name` è l'alternativa backend-agnostica a `category_id` (usata
        da `src/subscription_detector.py`, che non conosce id interni del backend):
        se entrambi sono passati vince `category_id` esplicito.
        """
        parsed_date = None
        if last_billed:
            parsed_date = datetime.strptime(last_billed, "%Y-%m-%d").date()
        resolved_category_id = category_id
        if resolved_category_id is None and category_name:
            resolved_category_id = self._resolve_category_id(category_name)
        subscription = Subscription(
            user_id=self._user_id,
            name=name,
            amount=amount,
            last_billed=parsed_date,
            sub_type=sub_type,
            account_id=account_id,
            category_id=resolved_category_id,
        )
        self._session.add(subscription)
        self._commit()
        return {
            "id": subscription.id,
            "name": subscription.name,
            "amount": _d(subscription.amount),
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
            self._commit()
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
        self._commit()
        return {
            "id": row.id,
            "name": row.name,
            "amount": _d(row.amount),
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
            self._commit()
            return False
        self._session.delete(row)
        self._commit()
        return True

    # ------------------------------------------------------------------ expense CRUD

    def fetch_expenses_paginated(
        self,
        start_date: date,
        end_date: date,
        limit: int = 25,
        offset: int = 0,
        search: str | None = None,
        category_id: int | None = None,
        account_id: int | None = None,
        sort_by: str = "date",
        sort_dir: str = "desc",
    ) -> tuple[list[dict], int]:
        """Restituisce spese paginate nell'intervallo con totale righe."""
        base_q = (
            self._session.query(Expense, UserCategory, Account)
            .outerjoin(UserCategory, UserCategory.id == Expense.category_id)
            .outerjoin(Account, Account.id == Expense.account_id)
            .filter(
                Expense.user_id == self._user_id,
                Expense.expense_date >= start_date,
                Expense.expense_date <= end_date,
            )
        )
        if search:
            base_q = base_q.filter(Expense.name.ilike(f"%{search}%"))
        if category_id is not None:
            base_q = base_q.filter(Expense.category_id == category_id)
        if account_id is not None:
            base_q = base_q.filter(Expense.account_id == account_id)
        _sort_cols = {
            "date": Expense.expense_date,
            "amount": Expense.amount,
            "name": Expense.name,
        }
        sort_col = _sort_cols.get(sort_by, Expense.expense_date)
        order = sort_col.asc() if sort_dir == "asc" else sort_col.desc()
        total = base_q.count()
        rows = base_q.order_by(order).limit(limit).offset(offset).all()
        result = [
            {
                "id": exp.id,
                "date": exp.expense_date.isoformat(),
                "name": exp.name,
                "amount": float(exp.amount),
                "category": cat.name if cat else (exp.category_name or ""),
                "category_id": exp.category_id,
                "account": acc.name if acc else "",
                "account_id": exp.account_id,
            }
            for exp, cat, acc in rows
        ]
        self._commit()
        return result, total

    def update_expense(self, expense_id: int, **kwargs) -> dict | None:
        """Aggiorna una spesa (name, amount, date, category_id, account_id)."""
        row = self._session.query(Expense).filter(
            Expense.id == expense_id,
            Expense.user_id == self._user_id,
        ).first()
        if not row:
            self._commit()
            return None
        if "name" in kwargs and kwargs["name"] is not None:
            row.name = kwargs["name"]
        if "amount" in kwargs and kwargs["amount"] is not None:
            row.amount = kwargs["amount"]
        if "date" in kwargs and kwargs["date"] is not None:
            row.expense_date = kwargs["date"]
        if "category_id" in kwargs:
            row.category_id = kwargs["category_id"]
        if "account_id" in kwargs:
            row.account_id = kwargs["account_id"]
        self._commit()
        return {"id": row.id, "name": row.name, "amount": float(row.amount)}

    def delete_expense(self, expense_id: int) -> bool:
        """Elimina una spesa."""
        row = self._session.query(Expense).filter(
            Expense.id == expense_id,
            Expense.user_id == self._user_id,
        ).first()
        if not row:
            self._commit()
            return False
        self._session.delete(row)
        self._commit()
        return True

    # ------------------------------------------------------------------ income CRUD

    def fetch_incomes_paginated(
        self,
        start_date: date,
        end_date: date,
        limit: int = 25,
        offset: int = 0,
        search: str | None = None,
        income_type: str | None = None,
        account_id: int | None = None,
        sort_by: str = "date",
        sort_dir: str = "desc",
    ) -> tuple[list[dict], int]:
        """Restituisce entrate paginate nell'intervallo con totale righe."""
        base_q = self._session.query(Income).filter(
            Income.user_id == self._user_id,
            Income.income_date >= start_date,
            Income.income_date <= end_date,
        )
        if search:
            base_q = base_q.filter(Income.name.ilike(f"%{search}%"))
        if income_type:
            base_q = base_q.filter(Income.income_type == income_type)
        if account_id is not None:
            base_q = base_q.filter(Income.account_id == account_id)
        _sort_cols = {
            "date": Income.income_date,
            "amount": Income.amount,
            "name": Income.name,
        }
        sort_col = _sort_cols.get(sort_by, Income.income_date)
        order = sort_col.asc() if sort_dir == "asc" else sort_col.desc()
        total = base_q.count()
        rows = base_q.order_by(order).limit(limit).offset(offset).all()
        acc_map = {a["id"]: a["name"] for a in self.fetch_accounts()}
        result = [
            {
                "id": r.id,
                "date": r.income_date.isoformat(),
                "name": r.name,
                "amount": float(r.amount),
                "income_type": r.income_type,
                "account": acc_map.get(r.account_id, ""),
                "account_id": r.account_id,
            }
            for r in rows
        ]
        self._commit()
        return result, total

    def update_income(self, income_id: int, **kwargs) -> dict | None:
        """Aggiorna un'entrata (name, amount, date, income_type, account_id)."""
        row = self._session.query(Income).filter(
            Income.id == income_id,
            Income.user_id == self._user_id,
        ).first()
        if not row:
            self._commit()
            return None
        if "name" in kwargs and kwargs["name"] is not None:
            row.name = kwargs["name"]
        if "amount" in kwargs and kwargs["amount"] is not None:
            row.amount = kwargs["amount"]
        if "date" in kwargs and kwargs["date"] is not None:
            row.income_date = kwargs["date"]
        if "income_type" in kwargs:
            row.income_type = kwargs["income_type"]
        if "account_id" in kwargs:
            row.account_id = kwargs["account_id"]
        self._commit()
        return {"id": row.id, "name": row.name, "amount": float(row.amount)}

    def delete_income(self, income_id: int) -> bool:
        """Elimina un'entrata."""
        row = self._session.query(Income).filter(
            Income.id == income_id,
            Income.user_id == self._user_id,
        ).first()
        if not row:
            self._commit()
            return False
        self._session.delete(row)
        self._commit()
        return True

    def delete_expenses_by_prefix(self, prefix: str) -> int:
        """Cancella tutte le spese il cui nome inizia con `prefix`. Ritorna il conteggio."""
        rows = self._session.query(Expense).filter(
            Expense.user_id == self._user_id,
            Expense.name.like(f"{prefix}%"),
        ).all()
        count = len(rows)
        for row in rows:
            self._session.delete(row)
        self._commit()
        return count

    def fetch_subscriptions_with_account_name(self) -> list[dict]:
        """Restituisce abbonamenti con nome conto risolto."""
        subs = self.fetch_subscriptions()
        acc_map = {a["id"]: a["name"] for a in self.fetch_accounts()}
        for s in subs:
            s["account_name"] = acc_map.get(s.get("account_id"), "") or ""
        return subs

    def fetch_calendar_month(self, start_date: date, end_date: date) -> dict:
        """Spese reali + occorrenze di abbonamento proiettate nell'intervallo, per la vista calendario.

        Le spese sono la fonte di verità (ledger); le occorrenze di abbonamento sono
        proiettate on-read a partire da `last_billed`/`sub_type` (nessuna riga persistita
        per un addebito non ancora avvenuto), quindi possono includere date passate se
        l'utente non ha ancora registrato/aggiornato l'abbonamento.
        """
        expenses = self.fetch_all_transactions(start_date, end_date)
        subs = self.fetch_subscriptions()

        subscription_occurrences = []
        for sub in subs:
            for occ_date in get_occurrences_in_range(
                sub.get("last_billed"), sub.get("sub_type"), start_date, end_date
            ):
                subscription_occurrences.append({
                    "subscription_id": sub["id"],
                    "date": occ_date.isoformat(),
                    "amount": sub["amount"],
                    "name": sub["name"],
                })

        return {"expenses": expenses, "subscription_occurrences": subscription_occurrences}


    def fetch_categories_full(self, include_archived: bool = True) -> list[dict]:
        """Categorie con id, name, monthly_budget (float) e descrizione.

        Alimenta la schermata di gestione categorie, che mostra anche le archiviate
        (in una sezione separata, con l'azione di ripristino): qui il default è
        quindi `True`, al contrario delle letture usate per *scegliere* una categoria.
        """
        rows = self._categories_query(include_archived).all()
        result = [
            {
                "id": r.id,
                "name": r.name,
                "monthly_budget": float(r.monthly_budget) if r.monthly_budget is not None else None,
                "description": r.description,
                "description_summary": r.description_summary,
                "archived": r.archived_at is not None,
                "archived_at": r.archived_at.isoformat() if r.archived_at else None,
            }
            for r in rows
        ]
        self._commit()
        return result

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
            self._commit()
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
        self._commit()
        return token

    def get_report_by_token(self, share_token: str) -> dict | None:
        """Recupera un report tramite share_token pubblico."""
        row = self._session.query(SavedReport).filter(
            SavedReport.share_token == share_token
        ).first()
        if not row:
            self._commit()
            return None
        result = self._report_to_dict(row)
        self._commit()
        return result

    def get_reports_for_user(self, user_id: str, limit: int = 24) -> list[dict]:
        """Lista report dell'utente, ordinati per data decrescente."""
        rows = (
            self._session.query(SavedReport)
            .filter(SavedReport.user_id == user_id)
            .order_by(SavedReport.report_date.desc())
            .limit(limit)
            .all()
        )
        result = [self._report_to_dict(r) for r in rows]
        self._commit()
        return result

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

    # ------------------------------------------------------------------ savings goals

    @staticmethod
    def _goal_to_dict(row: SavingsGoal) -> dict:
        return {
            "id": row.id,
            "goal_type": row.goal_type,
            "name": row.name,
            "target_amount": _d(row.target_amount),
            "current_snapshot": _d(row.current_snapshot) if row.current_snapshot is not None else None,
            "account_id": row.account_id,
            "category_id": row.category_id,
            "start_date": row.start_date.isoformat() if row.start_date else None,
            "target_date": row.target_date.isoformat() if row.target_date else None,
            "status": row.status,
            "last_evaluated_at": row.last_evaluated_at.isoformat() if row.last_evaluated_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        }

    def create_savings_goal(
        self,
        goal_type: str,
        name: str,
        target_amount: float,
        account_id: int | None = None,
        category_id: int | None = None,
        start_date: date | None = None,
        target_date: date | None = None,
    ) -> dict:
        """Crea un obiettivo di risparmio per l'utente corrente."""
        goal = SavingsGoal(
            user_id=self._user_id,
            goal_type=goal_type,
            name=name,
            target_amount=target_amount,
            account_id=account_id,
            category_id=category_id,
            start_date=start_date or date.today(),
            target_date=target_date,
        )
        self._session.add(goal)
        self._commit()
        return self._goal_to_dict(goal)

    def fetch_savings_goals(self, status: str | None = None) -> list[dict]:
        """Restituisce gli obiettivi dell'utente, opzionalmente filtrati per stato."""
        q = self._session.query(SavingsGoal).filter(SavingsGoal.user_id == self._user_id)
        if status is not None:
            q = q.filter(SavingsGoal.status == status)
        rows = q.order_by(SavingsGoal.created_at.desc()).all()
        result = [self._goal_to_dict(r) for r in rows]
        self._commit()
        return result

    def update_savings_goal(self, goal_id: int, **fields) -> dict | None:
        """Aggiorna name/target_amount/target_date/status di un obiettivo."""
        row = self._session.query(SavingsGoal).filter(
            SavingsGoal.id == goal_id,
            SavingsGoal.user_id == self._user_id,
        ).first()
        if not row:
            self._commit()
            return None
        if "name" in fields and fields["name"] is not None:
            row.name = fields["name"]
        if "target_amount" in fields and fields["target_amount"] is not None:
            row.target_amount = fields["target_amount"]
        if "target_date" in fields:
            row.target_date = fields["target_date"]
        if "status" in fields and fields["status"] is not None:
            row.status = fields["status"]
        if "current_snapshot" in fields:
            row.current_snapshot = fields["current_snapshot"]
        if "last_evaluated_at" in fields:
            row.last_evaluated_at = fields["last_evaluated_at"]
        if "completed_at" in fields:
            row.completed_at = fields["completed_at"]
        row.updated_at = datetime.utcnow()
        self._commit()
        return self._goal_to_dict(row)

    def delete_savings_goal(self, goal_id: int) -> bool:
        """Elimina un obiettivo e lo storico evaluation collegato (cascade FK)."""
        row = self._session.query(SavingsGoal).filter(
            SavingsGoal.id == goal_id,
            SavingsGoal.user_id == self._user_id,
        ).first()
        if not row:
            self._commit()
            return False
        self._session.query(SavingsGoalEvaluation).filter(
            SavingsGoalEvaluation.goal_id == goal_id
        ).delete()
        self._session.delete(row)
        self._commit()
        return True

    def save_savings_goal_evaluation(
        self,
        goal_id: int,
        period_month: date,
        progress_pct: float,
        score_label: str,
        eta_date: date | None,
    ) -> None:
        """Upsert della valutazione mensile per (goal_id, period_month)."""
        existing = self._session.query(SavingsGoalEvaluation).filter(
            SavingsGoalEvaluation.goal_id == goal_id,
            SavingsGoalEvaluation.period_month == period_month,
        ).first()
        if existing:
            existing.progress_pct = progress_pct
            existing.score_label = score_label
            existing.eta_date = eta_date
            self._commit()
            return
        row = SavingsGoalEvaluation(
            goal_id=goal_id,
            user_id=self._user_id,
            period_month=period_month,
            progress_pct=progress_pct,
            score_label=score_label,
            eta_date=eta_date,
        )
        self._session.add(row)
        self._commit()

    def fetch_savings_goal_evaluations(self, goal_id: int, limit: int = 12) -> list[dict]:
        """Restituisce lo storico delle valutazioni mensili di un obiettivo (più recenti prima)."""
        rows = (
            self._session.query(SavingsGoalEvaluation)
            .filter(SavingsGoalEvaluation.goal_id == goal_id, SavingsGoalEvaluation.user_id == self._user_id)
            .order_by(SavingsGoalEvaluation.period_month.desc())
            .limit(limit)
            .all()
        )
        result = [
            {
                "period_month": r.period_month.isoformat(),
                "progress_pct": _d(r.progress_pct),
                "score_label": r.score_label,
                "eta_date": r.eta_date.isoformat() if r.eta_date else None,
            }
            for r in rows
        ]
        self._commit()
        return result