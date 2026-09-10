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
from src.expense_label_normalizer import assign_label_cluster, resync_cluster as _resync_cluster
from src.loan_calculator import calculate_installment, split_current_payment
from src.storage.base import FinancialStorage
from src.storage.models import (
    Account, UserCategory, UserCategoryNotionLink, CategoryCandidate, Expense,
    ExpenseLabelCluster, ExpenseLabelOverride, Income, UserIncomeCategory,
    UserIncomeCategoryNotionLink,
    Subscription, SavedReport, Transfer, SavingsGoal, SavingsGoalEvaluation,
    Loan, LoanMonthlyCharge, MortgageSimulation,
)
from src.storage import rls  # registra il listener RLS e fornisce bind_user
from config import Config

# Nomi fissi delle categorie condivise generate dal tracking mutui/finanziamenti
# (vedi src/storage/models.py::Loan). Non in DEFAULT_CATEGORIES: create al volo
# alla prima spesa generata, non retroattive per utenti esistenti.
_LOAN_INTEREST_CATEGORY = "Interessi"
_LOAN_COSTS_CATEGORY = "Mutui/finanziamenti"

_MONTHLY_BALANCE_QUERIES_BY_DIALECT = {
    "postgresql": (
        text(
            "SELECT TO_CHAR(DATE_TRUNC('month', income_date), 'YYYY-MM-DD') AS month, "
            "SUM(amount) AS total FROM incomes "
            "WHERE user_id = :uid AND income_date >= :start AND income_date <= :end "
            "GROUP BY month"
        ),
        text(
            "SELECT TO_CHAR(DATE_TRUNC('month', expense_date), 'YYYY-MM-DD') AS month, "
            "SUM(amount) AS total FROM expenses "
            "WHERE user_id = :uid AND expense_date >= :start AND expense_date <= :end "
            "GROUP BY month"
        ),
    ),
    "sqlite": (
        text(
            "SELECT strftime('%Y-%m-01', income_date) AS month, SUM(amount) AS total "
            "FROM incomes WHERE user_id = :uid AND income_date >= :start AND income_date <= :end "
            "GROUP BY month"
        ),
        text(
            "SELECT strftime('%Y-%m-01', expense_date) AS month, SUM(amount) AS total "
            "FROM expenses WHERE user_id = :uid AND expense_date >= :start AND expense_date <= :end "
            "GROUP BY month"
        ),
    ),
}


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

    def close(self) -> None:
        """Chiude la sessione SQLAlchemy associata allo storage."""
        self._session.close()

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
        if cat is None and category_name == _LOAN_COSTS_CATEGORY:
            legacy = self._session.query(UserCategory).filter(
                UserCategory.user_id == self._user_id,
                func.lower(UserCategory.name) == "costi mutuo/finanziamento",
            ).first()
            if legacy:
                legacy.name = _LOAN_COSTS_CATEGORY
                cat = legacy
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

    def _resolve_income_category_id(self, name: str | None) -> int:
        """Resolve an income category inside the current tenant and reactivate it.

        The return value is never null: missing legacy values map to ``Altra
        entrata`` and a historical custom name becomes a user-owned category.
        """
        from src.income_categories import normalize_income_category_name

        resolved_name = normalize_income_category_name(name)
        category = self._session.query(UserIncomeCategory).filter(
            UserIncomeCategory.user_id == self._user_id,
            func.lower(UserIncomeCategory.name) == resolved_name.casefold(),
        ).first()
        if category is not None:
            if category.archived_at is not None:
                category.archived_at = None
            return category.id
        category = UserIncomeCategory(user_id=self._user_id, name=resolved_name)
        self._session.add(category)
        self._session.flush()
        return category.id

    def _owned_income_category(self, category_id: int) -> UserIncomeCategory:
        """Return a category only when it is owned by the active tenant."""
        category = self._session.query(UserIncomeCategory).filter(
            UserIncomeCategory.id == category_id,
            UserIncomeCategory.user_id == self._user_id,
        ).first()
        if category is None:
            raise ValueError("Income category not found")
        return category

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
            "id": category.id,
            "name": category.name,
            "monthly_budget": _d(category.monthly_budget) if category.monthly_budget is not None else None,
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
            "id": row.id,
            "name": row.name,
            "monthly_budget": _d(row.monthly_budget) if row.monthly_budget is not None else None,
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

        # Anche i cluster di normalizzazione e le regole di correzione manuale sono
        # stato interno (non dati dell'utente) ma hanno una FK RESTRICT verso
        # user_categories: senza riassegnarli la cancellazione fallirebbe. Nessuna
        # fusione automatica dei cluster che finiscono nella stessa categoria —
        # l'utente ha "Unisci" per deciderlo lui.
        self._session.query(ExpenseLabelCluster).filter(
            ExpenseLabelCluster.user_id == self._user_id,
            ExpenseLabelCluster.category_id == cat_id,
        ).update({"category_id": target.id}, synchronize_session=False)
        # Le regole spostate possono collidere sull'indice unico con una regola già
        # presente nella categoria di destinazione: quella di destinazione vince.
        moving = (
            self._session.query(ExpenseLabelOverride)
            .filter(
                ExpenseLabelOverride.user_id == self._user_id,
                ExpenseLabelOverride.category_id == cat_id,
            )
            .all()
        )
        if moving:
            existing_texts = {
                row[0]
                for row in self._session.query(ExpenseLabelOverride.normalized_text).filter(
                    ExpenseLabelOverride.user_id == self._user_id,
                    ExpenseLabelOverride.category_id == target.id,
                )
            }
            for override in moving:
                if override.normalized_text in existing_texts:
                    self._session.delete(override)
                else:
                    override.category_id = target.id
                    existing_texts.add(override.normalized_text)
            self._session.flush()

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

    # ---------------------------------------------------------- income categories

    def _income_categories_query(self, include_archived: bool = False):
        """Base tenant-scoped query for income categories."""
        query = self._session.query(UserIncomeCategory).filter(
            UserIncomeCategory.user_id == self._user_id
        )
        return query

    @staticmethod
    def _income_category_dto(
        category: UserIncomeCategory, link: UserIncomeCategoryNotionLink | None,
    ) -> dict:
        """Serialize an income category without exposing adapter-specific ids."""
        return {
            "id": category.id,
            "name": category.name,
            "monthly_budget": _d(category.monthly_budget) if category.monthly_budget is not None else None,
            "description": category.description,
            "description_summary": category.description_summary,
            "average": _d(link.average) if link and link.average is not None else 0.0,
            "archived": category.archived_at is not None,
        }

    def get_income_categories(self, include_archived: bool = False) -> list[dict]:
        """Return user-owned income categories, including cached local averages."""
        query = self._session.query(UserIncomeCategory, UserIncomeCategoryNotionLink).outerjoin(
            UserIncomeCategoryNotionLink,
            UserIncomeCategoryNotionLink.category_id == UserIncomeCategory.id,
        ).filter(UserIncomeCategory.user_id == self._user_id)
        result = [self._income_category_dto(category, link) for category, link in query.all()]
        self._commit()
        return result

    def get_income_category_names(self, include_archived: bool = False) -> list[str]:
        """Return income category names selectable by the current user."""
        names = [row.name for row in self._income_categories_query(include_archived).all()]
        self._commit()
        return names

    def create_income_category(
        self, name: str, monthly_budget: float | None = None,
        description: str | None = None, description_summary: str | None = None,
    ) -> dict:
        """Create one tenant-owned income category."""
        from src.income_categories import normalize_income_category_name

        normalized_name = normalize_income_category_name(name)
        duplicate = self._income_categories_query(True).filter(
            func.lower(UserIncomeCategory.name) == normalized_name.casefold()
        ).first()
        if duplicate is not None:
            raise ValueError("Income category already exists")
        category = UserIncomeCategory(
            user_id=self._user_id, name=normalized_name,
            monthly_budget=monthly_budget, description=description,
            description_summary=description_summary,
        )
        self._session.add(category)
        self._commit()
        return self._income_category_dto(category, None)

    def update_income_category(self, category_id: int, **fields) -> dict | None:
        """Update an income category only when it belongs to this user."""
        from src.income_categories import normalize_income_category_name

        category = self._income_categories_query(True).filter(
            UserIncomeCategory.id == category_id
        ).first()
        if category is None:
            self._commit()
            return None
        if fields.get("name") is not None:
            normalized_name = normalize_income_category_name(fields["name"])
            duplicate = self._income_categories_query(True).filter(
                UserIncomeCategory.id != category.id,
                func.lower(UserIncomeCategory.name) == normalized_name.casefold(),
            ).first()
            if duplicate is not None:
                raise ValueError("Income category already exists")
            self._session.query(Income).filter(
                Income.user_id == self._user_id,
                Income.income_category_id == category.id,
            ).update({"income_type": normalized_name}, synchronize_session=False)
            category.name = normalized_name
        if "monthly_budget" in fields and fields["monthly_budget"] is not None:
            category.monthly_budget = fields["monthly_budget"]
        for field in ("description", "description_summary"):
            if field in fields:
                setattr(category, field, fields[field])
        link = self._session.query(UserIncomeCategoryNotionLink).filter(
            UserIncomeCategoryNotionLink.category_id == category.id
        ).first()
        self._commit()
        return self._income_category_dto(category, link)

    def delete_income_category(self, category_id: int) -> dict | None:
        """Delete an income category after moving linked incomes to ``Altra entrata``."""
        category = self._income_categories_query(True).filter(
            UserIncomeCategory.id == category_id
        ).first()
        if category is None:
            self._commit()
            return None
        if category.name.casefold() == "altra entrata":
            raise ValueError("La categoria «Altra entrata» non può essere eliminata")

        fallback = self._income_categories_query(True).filter(
            func.lower(UserIncomeCategory.name) == "altra entrata"
        ).first()
        if fallback is None:
            fallback = UserIncomeCategory(user_id=self._user_id, name="Altra entrata")
            self._session.add(fallback)
            self._session.flush()
        reassigned = self._session.query(Income).filter(
            Income.user_id == self._user_id,
            Income.income_category_id == category.id,
        ).update(
            {"income_category_id": fallback.id, "income_type": fallback.name},
            synchronize_session=False,
        )
        link = self._session.query(UserIncomeCategoryNotionLink).filter(
            UserIncomeCategoryNotionLink.category_id == category.id
        ).first()
        if link is not None:
            self._session.delete(link)
            # I mapper non dichiarano una relationship tra cache Notion e
            # categoria: forza quindi l'ordine FK anche su PostgreSQL/RLS.
            # Il flush resta nella stessa transazione e il successivo commit
            # annulla entrambe le operazioni se la cancellazione fallisce.
            self._session.flush()
        self._session.delete(category)
        self._commit()
        return {"incomes": reassigned}

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

        label_cluster = assign_label_cluster(
            self._session, self._user_id, name, resolved_category_id
        )

        expense = Expense(
            user_id=self._user_id,
            expense_date=expense_date,
            amount=amount,
            name=name,
            category_name=category_name,   # bridge legacy, non usato applicativamente
            category_id=resolved_category_id,
            account_id=acc_id_int,
            label_cluster_id=label_cluster.cluster_id,
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
        """Restituisce tutte le spese nell'intervallo.

        `normalized_name` è l'etichetta di raggruppamento (ancora del cluster
        `expense_label_clusters`): i chiamanti che raggruppano per "voce di spesa"
        (es. `/api/analytics/top-merchants`) devono usare questo campo, non `name`,
        che resta la descrizione originale dell'utente mostrata nelle liste di
        movimenti. Fallback a `name` per le spese non ancora processate
        (`label_cluster_id IS NULL`, prima del backfill).

        `label_cluster_id` e `category_id` sono esposti perché la UI possa offrire la
        correzione manuale del raggruppamento partendo da una riga del grafico.
        """
        rows = self._session.query(Expense, UserCategory, ExpenseLabelCluster).outerjoin(
            UserCategory, UserCategory.id == Expense.category_id
        ).outerjoin(
            ExpenseLabelCluster, ExpenseLabelCluster.id == Expense.label_cluster_id
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
                "normalized_name": cluster.anchor_text if cluster else exp.name,
                "label_cluster_id": exp.label_cluster_id,
                "category": cat.name if cat else (exp.category_name or ""),
                "category_id": exp.category_id,
                "account_id": exp.account_id,
                "created_at": exp.created_at.isoformat() if exp.created_at else None,
            }
            for exp, cat, cluster in rows
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
        income_category_id: int | None = None,
        income_category_name: str | None = None,
        income_type: str | None = None,
    ) -> dict:
        """Crea un'entrata. Il saldo del conto è calcolato on-read, non persistito."""
        try:
            acc_id_int = int(account_id) if account_id is not None else None
        except (ValueError, TypeError):
            acc_id_int = None

        category = self._owned_income_category(int(income_category_id)) if income_category_id else None
        resolved_category_id = category.id if category is not None else self._resolve_income_category_id(
            income_category_name if income_category_name is not None else income_type
        )
        category = category or self._session.get(UserIncomeCategory, resolved_category_id)
        resolved_name = category.name if category is not None else "Altra entrata"
        income = Income(
            user_id=self._user_id,
            income_date=income_date,
            amount=amount,
            name=name,
            account_id=acc_id_int,
            income_type=resolved_name,
            income_category_id=resolved_category_id,
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
            "income_category_id": income.income_category_id,
            "income_category": resolved_name,
        }

    def fetch_income(self, start_date: date, end_date: date) -> list[dict]:
        """Restituisce tutte le entrate nell'intervallo."""
        rows = self._session.query(Income, UserIncomeCategory).outerjoin(
            UserIncomeCategory, UserIncomeCategory.id == Income.income_category_id,
        ).filter(
            Income.user_id == self._user_id,
            Income.income_date >= start_date,
            Income.income_date <= end_date,
        ).all()
        result = [
            {
                "id": income.id,
                "date": income.income_date,
                "amount": _d(income.amount),
                "name": income.name,
                "account_id": income.account_id,
                "income_type": income.income_type,
                "income_category_id": income.income_category_id,
                "income_category": category.name if category else income.income_type,
            }
            for income, category in rows
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

    def update_transfer(self, transfer_id: int, **kwargs) -> dict | None:
        """Aggiorna un trasferimento (name, amount, date, from_account_id, to_account_id)."""
        row = self._session.query(Transfer).filter(
            Transfer.id == transfer_id,
            Transfer.user_id == self._user_id,
        ).first()
        if not row:
            self._commit()
            return None
        new_from = int(kwargs["from_account_id"]) if kwargs.get("from_account_id") is not None else row.from_account_id
        new_to = int(kwargs["to_account_id"]) if kwargs.get("to_account_id") is not None else row.to_account_id
        if new_from == new_to:
            self._commit()
            raise ValueError("Il conto di origine e di destinazione devono essere diversi")
        if "name" in kwargs and kwargs["name"] is not None:
            row.name = kwargs["name"]
        if "amount" in kwargs and kwargs["amount"] is not None:
            row.amount = abs(float(kwargs["amount"]))
        if "date" in kwargs and kwargs["date"] is not None:
            row.transfer_date = kwargs["date"]
        row.from_account_id = new_from
        row.to_account_id = new_to
        self._commit()
        return {
            "id": row.id,
            "date": row.transfer_date,
            "amount": _d(row.amount),
            "from_account_id": row.from_account_id,
            "to_account_id": row.to_account_id,
            "name": row.name,
        }

    def delete_transfer(self, transfer_id: int) -> bool:
        """Elimina un trasferimento."""
        row = self._session.query(Transfer).filter(
            Transfer.id == transfer_id,
            Transfer.user_id == self._user_id,
        ).first()
        if not row:
            self._commit()
            return False
        self._session.delete(row)
        self._commit()
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
        from calendar import month_name as _month_name

        dialect = self._session.get_bind().dialect.name
        income_query, expense_query = _MONTHLY_BALANCE_QUERIES_BY_DIALECT.get(
            dialect, _MONTHLY_BALANCE_QUERIES_BY_DIALECT["sqlite"]
        )

        income_rows = self._session.execute(
            income_query,
            {"uid": self._user_id, "start": start_date.isoformat(), "end": end_date.isoformat()},
        ).mappings().all()

        expense_rows = self._session.execute(
            expense_query,
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
                "cadence": r.cadence,
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
        cadence: str | None = None,
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
            cadence=cadence,
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
            "cadence": subscription.cadence,
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
        """Aggiorna una spesa (name, amount, date, category_id, account_id).

        Se `name` o `category_id` cambiano, il cluster di normalizzazione va
        ricalcolato: il guardrail di categoria dipende da `category_id` (una
        spesa spostata in un'altra categoria non deve restare agganciata
        all'ancora della categoria vecchia), e ovviamente un `name` diverso può
        assomigliare a un'ancora diversa. Non modifica mai il cluster vecchio
        (resta con gli altri membri, corretto: quella spesa non c'è più lì).
        """
        row = self._session.query(Expense).filter(
            Expense.id == expense_id,
            Expense.user_id == self._user_id,
        ).first()
        if not row:
            self._commit()
            return None
        recluster = "name" in kwargs and kwargs["name"] is not None or "category_id" in kwargs
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
        if recluster:
            previous_cluster_id = row.label_cluster_id
            label_cluster = assign_label_cluster(self._session, self._user_id, row.name, row.category_id)
            row.label_cluster_id = label_cluster.cluster_id
            # Il cluster di partenza ha perso questa spesa: senza riallineare i
            # conteggi la sua etichetta resterebbe quella di una grafia che non ha
            # più spese, e il grafico mostrerebbe un nome che l'utente non ritrova.
            if previous_cluster_id and previous_cluster_id != label_cluster.cluster_id:
                self._session.flush()
                _resync_cluster(self._session, self._user_id, previous_cluster_id)
        self._commit()
        return {"id": row.id, "name": row.name, "amount": float(row.amount)}

    def delete_expense(self, expense_id: int) -> bool:
        """Elimina una spesa e riallinea il cluster che la conteneva."""
        row = self._session.query(Expense).filter(
            Expense.id == expense_id,
            Expense.user_id == self._user_id,
        ).first()
        if not row:
            self._commit()
            return False
        cluster_id = row.label_cluster_id
        self._session.delete(row)
        # Senza riallineare i conteggi, l'etichetta del gruppo può restare quella di
        # una grafia che non ha più spese: il grafico mostrerebbe un nome che
        # l'utente non ritrova più tra i suoi movimenti.
        if cluster_id:
            self._session.flush()
            _resync_cluster(self._session, self._user_id, cluster_id)
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
        income_category_id: int | None = None,
        income_type: str | None = None,
        account_id: int | None = None,
        sort_by: str = "date",
        sort_dir: str = "desc",
    ) -> tuple[list[dict], int]:
        """Restituisce entrate paginate nell'intervallo con totale righe."""
        base_q = self._session.query(Income, UserIncomeCategory, Account).outerjoin(
            UserIncomeCategory, UserIncomeCategory.id == Income.income_category_id,
        ).outerjoin(
            Account, Account.id == Income.account_id,
        ).filter(
            Income.user_id == self._user_id,
            Income.income_date >= start_date,
            Income.income_date <= end_date,
        )
        if search:
            base_q = base_q.filter(Income.name.ilike(f"%{search}%"))
        if income_category_id is not None:
            base_q = base_q.filter(Income.income_category_id == income_category_id)
        elif income_type:
            # Compatibility alias for old API clients while income_type remains.
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
        result = [
            {
                "id": income.id,
                "date": income.income_date.isoformat(),
                "name": income.name,
                "amount": float(income.amount),
                "income_type": income.income_type,
                "income_category_id": income.income_category_id,
                "income_category": category.name if category else income.income_type,
                "account": account.name if account else "",
                "account_id": income.account_id,
            }
            for income, category, account in rows
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
        category_id = kwargs.get("income_category_id")
        category_name = kwargs.get("income_category_name")
        if category_name is None and "income_type" in kwargs:
            category_name = kwargs["income_type"]
        if category_id is not None:
            row.income_category_id = self._owned_income_category(int(category_id)).id
            category = self._session.get(UserIncomeCategory, row.income_category_id)
            row.income_type = category.name if category is not None else "Altra entrata"
        elif category_name is not None:
            row.income_category_id = self._resolve_income_category_id(category_name)
            category = self._session.get(UserIncomeCategory, row.income_category_id)
            row.income_type = category.name if category is not None else "Altra entrata"
        if "account_id" in kwargs:
            row.account_id = kwargs["account_id"]
        self._commit()
        category = self._session.get(UserIncomeCategory, row.income_category_id)
        return {
            "id": row.id, "name": row.name, "amount": float(row.amount),
            "income_type": row.income_type, "income_category_id": row.income_category_id,
            "income_category": category.name if category else row.income_type,
        }

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
            "emergency_fund_months": row.emergency_fund_months,
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
        emergency_fund_months: int | None = None,
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
            emergency_fund_months=emergency_fund_months,
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
        if "account_id" in fields:
            row.account_id = fields["account_id"]
        if "emergency_fund_months" in fields and fields["emergency_fund_months"] is not None:
            row.emergency_fund_months = fields["emergency_fund_months"]
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

    # ------------------------------------------------------------------ loans

    # ------------------------------------------------------------------ mortgage simulations

    @staticmethod
    def _mortgage_simulation_to_dict(row: MortgageSimulation) -> dict:
        """Serializza una bozza senza esporre mai dati di altri utenti."""
        return {
            "id": row.id,
            "name": row.name,
            "input_snapshot": row.input_snapshot,
            "result_snapshot": row.result_snapshot,
            "status": row.status,
            "converted_loan_id": row.converted_loan_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def create_mortgage_simulation(
        self, name: str, input_snapshot: dict, result_snapshot: dict,
    ) -> dict:
        """Salva una bozza di simulazione senza creare mutui o movimenti."""
        row = MortgageSimulation(
            user_id=self._user_id,
            name=name,
            input_snapshot=input_snapshot,
            result_snapshot=result_snapshot,
        )
        self._session.add(row)
        self._commit()
        return self._mortgage_simulation_to_dict(row)

    def fetch_mortgage_simulations(self) -> list[dict]:
        """Elenca le bozze dell'utente, dalla più recente."""
        rows = self._session.query(MortgageSimulation).filter(
            MortgageSimulation.user_id == self._user_id,
        ).order_by(MortgageSimulation.created_at.desc()).all()
        result = [self._mortgage_simulation_to_dict(row) for row in rows]
        self._commit()
        return result

    def get_mortgage_simulation(self, simulation_id: int) -> dict | None:
        """Legge una sola bozza, applicando l'isolamento per user_id."""
        row = self._session.query(MortgageSimulation).filter(
            MortgageSimulation.id == simulation_id,
            MortgageSimulation.user_id == self._user_id,
        ).first()
        self._commit()
        return self._mortgage_simulation_to_dict(row) if row else None

    def update_mortgage_simulation(
        self, simulation_id: int, name: str, input_snapshot: dict, result_snapshot: dict,
    ) -> dict | None:
        """Aggiorna una bozza appartenente all'utente corrente."""
        row = self._session.query(MortgageSimulation).filter(
            MortgageSimulation.id == simulation_id,
            MortgageSimulation.user_id == self._user_id,
            MortgageSimulation.status == "active",
        ).first()
        if row is None:
            return None
        row.name, row.input_snapshot, row.result_snapshot = name, input_snapshot, result_snapshot
        self._commit()
        return self._mortgage_simulation_to_dict(row)

    def duplicate_mortgage_simulation(self, simulation_id: int) -> dict | None:
        """Duplica una bozza dell'utente corrente con un nuovo identificativo."""
        row = self.get_mortgage_simulation(simulation_id)
        if row is None or row["status"] != "active":
            return None
        return self.create_mortgage_simulation(
            f"{row['name']} (copia)", dict(row["input_snapshot"]), dict(row["result_snapshot"]),
        )

    def convert_mortgage_simulation(self, simulation_id: int, loan_fields: dict) -> dict | None:
        """Crea un Loan dalla bozza attiva e la archivia nella stessa transazione."""
        row = self._session.query(MortgageSimulation).filter(
            MortgageSimulation.id == simulation_id,
            MortgageSimulation.user_id == self._user_id,
            MortgageSimulation.status == "active",
        ).with_for_update().first()
        if row is None:
            return None
        try:
            # La conversione è deliberatamente priva di spese retroattive: una
            # bozza non deve mai produrre movimenti storici al solo passaggio a
            # contratto reale. Le spese future verranno registrate dal job mensile.
            loan = self._create_loan(**loan_fields, record_origination_fee=False)
            row.status = "archived"
            row.converted_loan_id = loan.id
            self._commit()
        except Exception:
            self._session.rollback()
            raise
        return self._loan_to_dict(loan)

    def delete_mortgage_simulation(self, simulation_id: int) -> bool:
        """Elimina una bozza dell'utente corrente."""
        row = self._session.query(MortgageSimulation).filter(
            MortgageSimulation.id == simulation_id,
            MortgageSimulation.user_id == self._user_id,
            MortgageSimulation.status == "active",
        ).first()
        if not row:
            self._commit()
            return False
        self._session.delete(row)
        self._commit()
        return True

    def apply_category_budgets(self, proposals: list[dict]) -> list[dict] | None:
        """Aggiorna tutti i budget solo se ogni categoria appartiene all'utente."""
        ids = [int(item["category_id"]) for item in proposals]
        rows = self._session.query(UserCategory).filter(
            UserCategory.user_id == self._user_id,
            UserCategory.id.in_(ids),
        ).all()
        if len(rows) != len(ids):
            self._session.rollback()
            return None
        by_id = {row.id: row for row in rows}
        for proposal in proposals:
            by_id[int(proposal["category_id"])].monthly_budget = proposal["proposed_budget"]
        self._commit()
        return [
            {"id": row.id, "name": row.name, "monthly_budget": _d(row.monthly_budget)}
            for row in rows
        ]

    @staticmethod
    def _loan_to_dict(row: Loan) -> dict:
        return {
            "id": row.id,
            "name": row.name,
            "loan_type": row.loan_type,
            "principal_amount": _d(row.principal_amount),
            "disbursement_date": row.disbursement_date.isoformat() if row.disbursement_date else None,
            "duration_months": row.duration_months,
            "account_id": row.account_id,
            "rate_type": row.rate_type,
            "tan": _d(row.tan),
            "taeg": _d(row.taeg) if row.taeg is not None else None,
            "spread": _d(row.spread) if row.spread is not None else None,
            "euribor_current": _d(row.euribor_current) if row.euribor_current is not None else None,
            "euribor_tenor": row.euribor_tenor,
            "review_frequency": row.review_frequency,
            "next_review_date": row.next_review_date.isoformat() if row.next_review_date else None,
            "origination_fee": _d(row.origination_fee) if row.origination_fee is not None else None,
            "monthly_fee": _d(row.monthly_fee) if row.monthly_fee is not None else None,
            "payment_cadence": row.payment_cadence or "monthly",
            "current_installment": _d(row.current_installment),
            "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    def _create_loan(
        self,
        name: str,
        loan_type: str,
        principal_amount: float,
        disbursement_date: date,
        duration_months: int,
        rate_type: str,
        tan: float,
        taeg: float | None = None,
        spread: float | None = None,
        euribor_current: float | None = None,
        euribor_tenor: str | None = None,
        review_frequency: str | None = None,
        next_review_date: date | None = None,
        account_id: int | None = None,
        origination_fee: float | None = None,
        monthly_fee: float | None = None,
        record_origination_fee: bool = True,
        payment_cadence: str = "monthly",
    ) -> Loan:
        """Costruisce un loan senza fare commit, per operazioni atomiche interne."""
        installment = calculate_installment(
            Decimal(str(principal_amount)), Decimal(str(tan)), duration_months, payment_cadence
        )
        loan = Loan(
            user_id=self._user_id,
            name=name,
            loan_type=loan_type,
            principal_amount=principal_amount,
            disbursement_date=disbursement_date,
            duration_months=duration_months,
            account_id=account_id,
            rate_type=rate_type,
            tan=tan,
            taeg=taeg,
            spread=spread,
            euribor_current=euribor_current,
            euribor_tenor=euribor_tenor,
            review_frequency=review_frequency,
            next_review_date=next_review_date,
            origination_fee=origination_fee,
            monthly_fee=monthly_fee,
            payment_cadence=payment_cadence,
            current_installment=installment,
        )
        self._session.add(loan)
        self._session.flush()

        # L'erogazione è un'entrata reale sul conto scelto. Il nome marcato e
        # il controllo prima dell'inserimento rendono l'operazione idempotente
        # anche se la richiesta di creazione viene ripetuta.
        if account_id is not None:
            disbursement_name = f"Erogazione mutuo: {name}"
            already_disbursed = self._session.query(Income.id).filter(
                Income.user_id == self._user_id,
                Income.account_id == account_id,
                Income.income_date == disbursement_date,
                Income.amount == principal_amount,
                Income.name == disbursement_name,
                Income.income_type == "Erogazione mutuo",
            ).first()
            if already_disbursed is None:
                self._session.add(Income(
                    user_id=self._user_id,
                    income_date=disbursement_date,
                    amount=principal_amount,
                    name=disbursement_name,
                    account_id=account_id,
                    income_type="Erogazione mutuo",
                ))

        # La rata viene trattata come uscita ricorrente, così il budget la
        # considera automaticamente. La categoria viene creata se necessario.
        costs_category_id = self._resolve_category_id(_LOAN_COSTS_CATEGORY)
        self._session.add(Subscription(
            user_id=self._user_id,
            name=f"Rata mutuo: {name}",
            amount=float(installment) + float(monthly_fee or 0) * {
                "monthly": 1, "quarterly": 3, "semiannual": 6, "yearly": 12,
            }.get(payment_cadence, 1),
            last_billed=disbursement_date,
            sub_type="mutuo",
            cadence=payment_cadence,
            account_id=account_id,
            category_id=costs_category_id,
        ))

        if origination_fee and record_origination_fee:
            self._session.add(Expense(
                user_id=self._user_id,
                expense_date=disbursement_date,
                amount=origination_fee,
                name=f"Istruttoria: {name}",
                category_id=costs_category_id,
                account_id=account_id,
                loan_id=loan.id,
            ))

        return loan

    def create_loan(
        self,
        name: str,
        loan_type: str,
        principal_amount: float,
        disbursement_date: date,
        duration_months: int,
        rate_type: str,
        tan: float,
        taeg: float | None = None,
        spread: float | None = None,
        euribor_current: float | None = None,
        euribor_tenor: str | None = None,
        review_frequency: str | None = None,
        next_review_date: date | None = None,
        account_id: int | None = None,
        origination_fee: float | None = None,
        monthly_fee: float | None = None,
        payment_cadence: str = "monthly",
    ) -> dict:
        """Crea un loan e, se previsto, registra il costo istruttoria una tantum."""
        loan = self._create_loan(
            name=name,
            loan_type=loan_type,
            principal_amount=principal_amount,
            disbursement_date=disbursement_date,
            duration_months=duration_months,
            rate_type=rate_type,
            tan=tan,
            taeg=taeg,
            spread=spread,
            euribor_current=euribor_current,
            euribor_tenor=euribor_tenor,
            review_frequency=review_frequency,
            next_review_date=next_review_date,
            account_id=account_id,
            origination_fee=origination_fee,
            monthly_fee=monthly_fee,
            payment_cadence=payment_cadence,
        )
        self._commit()
        return self._loan_to_dict(loan)

    def fetch_loans(self, status: str | None = None) -> list[dict]:
        """Restituisce i loan dell'utente, opzionalmente filtrati per stato.

        Ogni dict include `residual_balance` (saldo residuo attuale, dall'ultimo
        `LoanMonthlyCharge` o dal capitale iniziale se ancora nessun addebito) —
        serve alla card dashboard per "% estinto"/"residuo" senza una query separata.
        """
        q = self._session.query(Loan).filter(Loan.user_id == self._user_id)
        if status is not None:
            q = q.filter(Loan.status == status)
        rows = q.order_by(Loan.created_at.desc()).all()
        result = []
        for r in rows:
            view = self._loan_to_dict(r)
            residual, _elapsed = self._loan_residual_and_elapsed(r)
            view["residual_balance"] = _d(residual)
            view.update(self._loan_remaining_summary(r))
            result.append(view)
        self._commit()
        return result

    def _loan_residual_and_elapsed(self, loan: Loan) -> tuple[Decimal, int]:
        """Saldo residuo e numero di mesi già addebitati, dall'ultimo `LoanMonthlyCharge`."""
        last_charge = (
            self._session.query(LoanMonthlyCharge)
            .filter(LoanMonthlyCharge.loan_id == loan.id)
            .order_by(LoanMonthlyCharge.period_month.desc())
            .first()
        )
        elapsed = (
            self._session.query(func.count(LoanMonthlyCharge.id))
            .filter(LoanMonthlyCharge.loan_id == loan.id)
            .scalar() or 0
        )
        if last_charge:
            return Decimal(str(last_charge.residual_balance)), elapsed
        return Decimal(str(loan.principal_amount)), elapsed

    def _loan_remaining_summary(self, loan: Loan) -> dict:
        """Restituisce gli indicatori futuri del piano dal suo stato corrente."""
        from src.loan_calculator import summarize_remaining_loan

        residual, elapsed = self._loan_residual_and_elapsed(loan)
        remaining_months = max(loan.duration_months - elapsed, 1)
        last_charge = (
            self._session.query(LoanMonthlyCharge)
            .filter(LoanMonthlyCharge.loan_id == loan.id)
            .order_by(LoanMonthlyCharge.period_month.desc())
            .first()
        )
        summary = summarize_remaining_loan(
            residual,
            Decimal(str(loan.tan)),
            remaining_months,
            last_charge.period_month if last_charge else loan.disbursement_date,
        )
        return {
            "remaining_months": summary["remaining_months"],
            "estimated_end_date": summary["estimated_end_date"].isoformat(),
            "remaining_interest": _d(summary["remaining_interest"]),
            "next_principal": _d(summary["next_principal"]),
            "next_interest": _d(summary["next_interest"]),
        }

    def update_loan(self, loan_id: int, **fields) -> dict | None:
        """Aggiorna un loan. Se `tan` cambia su un loan variabile, ricalcola la rata
        corrente (`current_installment`) sul saldo residuo e sulla durata restante —
        il modello "classico" di tasso variabile: rata varia, durata fissa.
        """
        row = self._session.query(Loan).filter(
            Loan.id == loan_id,
            Loan.user_id == self._user_id,
        ).first()
        if not row:
            self._commit()
            return None

        simple_fields = (
            "name", "loan_type", "principal_amount", "disbursement_date", "duration_months",
            "account_id", "rate_type", "spread", "euribor_current", "euribor_tenor",
            "review_frequency", "next_review_date", "taeg", "origination_fee", "monthly_fee", "status",
        )
        for field in simple_fields:
            if field in fields and fields[field] is not None:
                setattr(row, field, fields[field])

        if "tan" in fields and fields["tan"] is not None:
            row.tan = fields["tan"]

        if any(field in fields and fields[field] is not None for field in (
            "tan", "principal_amount", "duration_months", "rate_type",
        )):
            if row.rate_type == "variabile":
                residual, elapsed = self._loan_residual_and_elapsed(row)
                remaining_months = max(row.duration_months - elapsed, 1)
                row.current_installment = calculate_installment(
                    residual, Decimal(str(row.tan)), remaining_months,
                    row.payment_cadence or "monthly",
                )
            else:
                # Un tasso fisso corretto è un dato contrattuale errato: il piano
                # di riferimento viene ricostruito dall'origine, senza riscrivere
                # le spese storiche già contabilizzate.
                row.current_installment = calculate_installment(
                    Decimal(str(row.principal_amount)), Decimal(str(row.tan)), row.duration_months,
                    row.payment_cadence or "monthly",
                )

        row.updated_at = datetime.utcnow()
        self._commit()
        return self._loan_to_dict(row)

    def delete_loan(self, loan_id: int) -> bool:
        """Elimina un loan preservando le spese già registrate nello storico."""
        row = self._session.query(Loan).filter(
            Loan.id == loan_id,
            Loan.user_id == self._user_id,
        ).first()
        if not row:
            self._commit()
            return False
        self._session.query(LoanMonthlyCharge).filter(LoanMonthlyCharge.loan_id == loan_id).delete()
        self._session.query(Expense).filter(
            Expense.loan_id == loan_id,
            Expense.user_id == self._user_id,
        ).update({Expense.loan_id: None}, synchronize_session=False)
        # Se il mutuo nasce da una simulazione, elimina solo quella simulazione
        # collegata. Le altre simulazioni dell'utente restano intatte.
        self._session.query(MortgageSimulation).filter(
            MortgageSimulation.converted_loan_id == loan_id,
            MortgageSimulation.user_id == self._user_id,
        ).delete(synchronize_session=False)
        self._session.delete(row)
        self._commit()
        return True

    def close_loan(self, loan_id: int, closure_date: date, **inputs: object) -> dict | None:
        """Chiude un mutuo alla data indicata e interrompe la rata automatica.

        Le spese già registrate restano nello storico; l'abbonamento generato
        automaticamente viene rimosso per evitare nuovi addebiti.
        """
        row = self._session.query(Loan).filter(
            Loan.id == loan_id, Loan.user_id == self._user_id,
        ).first()
        if not row:
            self._commit()
            return None
        residual, elapsed = self._loan_residual_and_elapsed(row)
        # I valori forniti dall'utente prevalgono sulla stima automatica del conteggio.
        if inputs.get("residual_principal") not in (None, ""):
            residual = Decimal(str(inputs["residual_principal"]))
        from src.loan_calculator import build_amortization_schedule
        remaining = build_amortization_schedule(
            residual, Decimal(str(row.tan)),
            max(row.duration_months - elapsed, 1), row.payment_cadence or "monthly",
        )
        future_interest = sum((item["interest"] for item in remaining), Decimal("0"))
        response = self._loan_to_dict(row)
        response.update({
            "closure_date": closure_date.isoformat(),
            "remaining_installments": len(remaining),
            "remaining_principal": _d(residual),
            "applied_tan": _d(row.tan),
            "avoided_future_interest": _d(future_interest),
            "accrued_interest": float(inputs.get("accrued_interest") or 0),
            "overdue_installments": float(inputs.get("overdue_installments") or 0),
            "administrative_costs": float(inputs.get("administrative_costs") or 0),
            "insurance_refund": float(inputs.get("insurance_refund") or 0),
            "indicative_settlement_total": _d(residual + Decimal(str(inputs.get("accrued_interest") or 0)) + Decimal(str(inputs.get("overdue_installments") or 0)) + Decimal(str(inputs.get("administrative_costs") or 0)) - Decimal(str(inputs.get("insurance_refund") or 0))),
        })
        row.status = "closed"
        row.updated_at = datetime.utcnow()
        self._session.query(Subscription).filter(
            Subscription.user_id == self._user_id,
            Subscription.name == f"Rata mutuo: {row.name}",
            Subscription.sub_type == "mutuo",
        ).delete(synchronize_session=False)
        self._commit()
        return response

    def partially_repay_loan(
        self, loan_id: int, repayment_date: date, amount: float, mode: str,
    ) -> dict | None:
        """Registra un rimborso parziale e ricalcola rata oppure durata."""
        if amount <= 0 or mode not in ("reduce_payment", "reduce_term"):
            raise ValueError("Importo o modalità non validi")
        row = self._session.query(Loan).filter(
            Loan.id == loan_id, Loan.user_id == self._user_id, Loan.status == "active",
        ).first()
        if row is None:
            return None
        residual, elapsed = self._loan_residual_and_elapsed(row)
        repayment = Decimal(str(amount))
        if repayment >= residual:
            return self.close_loan(loan_id, repayment_date)
        category_id = self._resolve_category_id(_LOAN_COSTS_CATEGORY)
        marker = f"Rimborso parziale mutuo: {row.name}"
        self._session.add(Expense(
            user_id=self._user_id, expense_date=repayment_date, amount=repayment,
            name=marker, category_id=category_id, account_id=row.account_id, loan_id=row.id,
        ))
        new_residual = residual - repayment
        from src.loan_calculator import build_amortization_schedule, calculate_installment
        remaining_months = max(row.duration_months - elapsed, 1)
        if mode == "reduce_payment":
            row.current_installment = calculate_installment(
                new_residual, Decimal(str(row.tan)), remaining_months,
                row.payment_cadence or "monthly",
            )
        else:
            schedule = build_amortization_schedule(
                new_residual, Decimal(str(row.tan)), remaining_months,
                row.payment_cadence or "monthly",
            )
            row.duration_months = elapsed + len(schedule) if elapsed else len(schedule)
            row.current_installment = schedule[0]["installment"]
        row.updated_at = datetime.utcnow()
        self._commit()
        result = self._loan_to_dict(row)
        result.update({"repayment_amount": _d(repayment), "remaining_principal": _d(new_residual), "repayment_mode": mode})
        return result

    def record_loan_monthly_charge(self, loan_id: int, period_month: date) -> dict | None:
        """Calcola e registra interessi (+ spese incasso rata) del mese per un loan attivo.

        Idempotente: None se il loan non esiste/non è attivo o se `period_month` è
        già stato addebitato (`uq_loan_monthly_charges_loan_period`).
        """
        loan = self._session.query(Loan).filter(
            Loan.id == loan_id,
            Loan.user_id == self._user_id,
            Loan.status == "active",
        ).first()
        if not loan:
            self._commit()
            return None

        already = self._session.query(LoanMonthlyCharge).filter(
            LoanMonthlyCharge.loan_id == loan_id,
            LoanMonthlyCharge.period_month == period_month,
        ).first()
        if already:
            self._commit()
            return None

        residual_before, _ = self._loan_residual_and_elapsed(loan)
        principal_component, interest_component = split_current_payment(
            residual_before, Decimal(str(loan.tan)), Decimal(str(loan.current_installment))
        )
        residual_after = max(residual_before - principal_component, Decimal("0"))

        interest_category_id = self._resolve_category_id(_LOAN_INTEREST_CATEGORY)
        self._session.add(Expense(
            user_id=self._user_id,
            expense_date=period_month,
            amount=interest_component,
            name=f"Interessi: {loan.name}",
            category_id=interest_category_id,
            account_id=loan.account_id,
            loan_id=loan.id,
        ))

        fee_amount = None
        if loan.monthly_fee:
            fee_amount = loan.monthly_fee
            costs_category_id = self._resolve_category_id(_LOAN_COSTS_CATEGORY)
            self._session.add(Expense(
                user_id=self._user_id,
                expense_date=period_month,
                amount=fee_amount,
                name=f"Spese incasso rata: {loan.name}",
                category_id=costs_category_id,
                account_id=loan.account_id,
                loan_id=loan.id,
            ))

        charge = LoanMonthlyCharge(
            loan_id=loan.id,
            user_id=self._user_id,
            period_month=period_month,
            interest_amount=interest_component,
            fee_amount=fee_amount,
            residual_balance=residual_after,
        )
        self._session.add(charge)

        if residual_after <= 0:
            loan.status = "closed"
        loan.updated_at = datetime.utcnow()

        self._commit()
        return {
            "loan_id": loan.id,
            "period_month": period_month.isoformat(),
            "interest_amount": _d(interest_component),
            "fee_amount": _d(fee_amount) if fee_amount is not None else None,
            "residual_balance": _d(residual_after),
        }

    def fetch_loan_schedule(self, loan_id: int) -> list[dict]:
        """Piano di ammortamento completo del loan (calcolato on-read, non persistito).

        Per un loan variabile riflette la rata *attuale*: non è predittivo delle
        revisioni future (che dipendono dall'Euribor, non prevedibile).
        """
        from src.loan_calculator import build_amortization_schedule

        loan = self._session.query(Loan).filter(
            Loan.id == loan_id,
            Loan.user_id == self._user_id,
        ).first()
        if not loan:
            self._commit()
            return []
        residual, elapsed = self._loan_residual_and_elapsed(loan)
        remaining_months = max(loan.duration_months - elapsed, 1)
        schedule = build_amortization_schedule(
            residual, Decimal(str(loan.tan)), remaining_months, loan.payment_cadence or "monthly"
        )
        self._commit()
        return [
            {
                "period": item["period"] + elapsed,
                "installment": _d(item["installment"]),
                "interest": _d(item["interest"]),
                "principal": _d(item["principal"]),
                "residual_balance": _d(item["residual_balance"]),
            }
            for item in schedule
        ]
