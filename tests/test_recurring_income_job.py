"""Idempotent recurring-income materialization contracts."""

from datetime import date
from decimal import Decimal

import pytest

from src.recurring_income_service import process_due_recurring_incomes
from src.storage.models import Account, Income, RecurringIncomeRule, UserIncomeCategory


pytestmark = pytest.mark.integration


def _rule(store, amount=1800):
    """Seed one due monthly rule with its tenant-owned dependencies."""
    store.add_user(chat_id="due-user", storage_backend="postgres")
    with store.Session() as session:
        account = Account(user_id="due-user", name="Conto", opening_balance=0)
        category = session.query(UserIncomeCategory).filter_by(
            user_id="due-user", name="Stipendio"
        ).first()
        if category is None:
            category = UserIncomeCategory(user_id="due-user", name="Stipendio")
        session.add(account)
        session.flush()
        rule = RecurringIncomeRule(
            user_id="due-user", name="Stipendio", amount=Decimal(str(amount)),
            cadence="monthly", payday_day=27, next_due_date=date(2026, 10, 27),
            account_id=account.id, income_category_id=category.id,
        )
        session.add(rule)
        session.commit()
        return rule.id


def test_monthly_rule_materializes_once_on_exact_day(mock_db_session):
    """Retrying the same scheduler date creates one occurrence only."""
    rule_id = _rule(mock_db_session)

    first = process_due_recurring_incomes(mock_db_session, date(2026, 10, 27))
    second = process_due_recurring_incomes(mock_db_session, date(2026, 10, 27))

    assert first.created == 1
    assert second.created == 0
    with mock_db_session.Session() as session:
        assert session.query(Income).filter_by(source_rule_id=rule_id).count() == 1


def test_editing_rule_does_not_rewrite_historical_income(mock_db_session):
    """Changing a rule after materialization leaves the old income untouched."""
    rule_id = _rule(mock_db_session)
    process_due_recurring_incomes(mock_db_session, date(2026, 10, 27))
    with mock_db_session.Session() as session:
        session.get(RecurringIncomeRule, rule_id).amount = Decimal("1900")
        session.commit()
        income = session.query(Income).filter_by(source_rule_id=rule_id).one()
        assert income.amount == Decimal("1800.00")
