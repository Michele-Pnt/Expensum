"""Configuration and materialization of user-owned recurring incomes."""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.storage import rls
from src.storage.models import Income, RecurringIncomeRule
from src.storage.postgres_storage import PostgresStorage
from src.user_store import User


CADENCES = frozenset({"monthly"})


def get_or_create_account(storage, name: str, currency: str) -> dict:
    """Reuse a same-name account case-insensitively or create a checking account."""
    normalized = name.strip()
    if not normalized:
        raise ValueError("Account name is required")
    for account in storage.fetch_accounts():
        if account.get("name", "").strip().casefold() == normalized.casefold():
            return account
    return storage.create_account(
        normalized,
        initial_balance=0.0,
        currency=currency,
        account_type="checking",
    )


def _next_payday(payday_day: int, today: date | None = None) -> date:
    """Return the next monthly date, clamping the day to the month length."""
    today = today or date.today()
    year, month = today.year, today.month
    if today.day > payday_day:
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return date(year, month, min(payday_day, monthrange(year, month)[1]))


def create_recurring_income_rule(
    store,
    user_id: str,
    *,
    name: str,
    amount: Decimal | float,
    cadence: str,
    payday_day: int,
    account_id: int,
    income_category_id: int | None,
) -> RecurringIncomeRule:
    """Persist a validated recurring-income rule without creating an income."""
    amount = Decimal(str(amount))
    if amount <= 0:
        raise ValueError("Income amount must be positive")
    if cadence not in CADENCES:
        raise ValueError("Unsupported income cadence")
    if not 1 <= payday_day <= 31:
        raise ValueError("Payday must be between 1 and 31")
    with store.Session() as session:
        rls.bind_user(session, user_id)
        rule = RecurringIncomeRule(
            user_id=str(user_id), name=name.strip() or "Stipendio", amount=amount,
            cadence=cadence, payday_day=payday_day,
            next_due_date=_next_payday(payday_day), account_id=account_id,
            income_category_id=income_category_id,
        )
        session.add(rule)
        session.commit()
        return rule


@dataclass
class SalaryConfiguration:
    """Result of salary setup, including the reused or newly created account."""

    account_id: int
    rule_id: int


class RecurringIncomeService:
    """Coordinate backend-agnostic account setup and recurring salary rules."""

    def __init__(self, store, storage, user_id: str, currency: str = "EUR") -> None:
        """Initialize service with the user store and financial storage adapter."""
        self.store = store
        self.storage = storage
        self.user_id = user_id
        self.currency = currency

    def configure_salary(
        self,
        *,
        account_name: str,
        income_name: str,
        amount: Decimal | float,
        cadence: str,
        payday_day: int,
    ) -> SalaryConfiguration:
        """Reuse/create the account and persist its recurring income rule."""
        account = get_or_create_account(self.storage, account_name, self.currency)
        categories = self.storage.get_income_categories()
        category = next(
            (row for row in categories
             if row.get("name", "").casefold() == "stipendio"),
            None,
        )
        if category is None:
            category = self.storage.create_income_category("Stipendio")
        rule = create_recurring_income_rule(
            self.store,
            self.user_id,
            name=income_name,
            amount=amount,
            cadence=cadence,
            payday_day=payday_day,
            account_id=int(account["id"]),
            income_category_id=category.get("id"),
        )
        return SalaryConfiguration(account_id=int(account["id"]), rule_id=rule.id)


@dataclass(frozen=True)
class RecurringIncomeSummary:
    """Counts produced by one due-income materialization pass."""

    created: int = 0
    skipped: int = 0


def _advance_monthly(day: int, current: date) -> date:
    """Advance a monthly payday while clamping short months."""
    year, month = current.year, current.month + 1
    if month == 13:
        year, month = year + 1, 1
    return date(year, month, min(day, monthrange(year, month)[1]))


def process_due_recurring_incomes(store, as_of: date) -> RecurringIncomeSummary:
    """Materialize due rules exactly once using the occurrence unique key."""
    created = skipped = 0
    with store.Session() as session:
        user_ids = [
            row[0]
            for row in session.query(User.chat_id).filter(
                User.storage_backend == "postgres",
                User.is_active.is_(True),
            ).all()
        ]

    # RLS requires one transaction-local tenant binding per user.  Querying all
    # recurring rules in an unbound session would fail closed on PostgreSQL.
    rule_snapshots = []
    for user_id in user_ids:
        with store.Session() as session:
            rls.bind_user(session, user_id)
            rule_snapshots.extend(
                session.query(RecurringIncomeRule).filter(
                    RecurringIncomeRule.user_id == user_id,
                    RecurringIncomeRule.active.is_(True),
                    RecurringIncomeRule.next_due_date <= as_of,
                ).all()
            )
    for rule_snapshot in rule_snapshots:
        with store.Session() as session:
            rls.bind_user(session, rule_snapshot.user_id)
            rule = session.get(RecurringIncomeRule, rule_snapshot.id)
            if rule is None or not rule.active or rule.next_due_date > as_of:
                skipped += 1
                continue
            existing = session.query(Income).filter(
                Income.source_rule_id == rule.id,
                Income.scheduled_for == rule.next_due_date,
            ).first()
            if existing is not None:
                rule.next_due_date = _advance_monthly(rule.payday_day, rule.next_due_date)
                session.commit()
                skipped += 1
                continue
            income = Income(
                user_id=rule.user_id,
                income_date=rule.next_due_date,
                amount=rule.amount,
                name=rule.name,
                account_id=rule.account_id,
                income_category_id=rule.income_category_id,
                source_rule_id=rule.id,
                scheduled_for=rule.next_due_date,
            )
            session.add(income)
            rule.next_due_date = _advance_monthly(rule.payday_day, rule.next_due_date)
            session.commit()
            created += 1
    return RecurringIncomeSummary(created=created, skipped=skipped)
