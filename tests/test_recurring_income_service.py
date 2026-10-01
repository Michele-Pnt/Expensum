"""Recurring salary configuration contracts."""

from decimal import Decimal

import pytest

from src.recurring_income_service import RecurringIncomeService


pytestmark = pytest.mark.integration


class FakeStorage:
    """Small financial-storage double for account/category contract tests."""

    def __init__(self):
        self.accounts = []
        self.categories = []

    def fetch_accounts(self):
        return self.accounts

    def create_account(self, name, initial_balance=0.0, *, currency="EUR", account_type="checking"):
        row = {
            "id": len(self.accounts) + 1,
            "name": name,
            "opening_balance": initial_balance,
            "currency": currency,
            "account_type": account_type,
        }
        self.accounts.append(row)
        return row

    def get_income_categories(self):
        return self.categories

    def create_income_category(self, name):
        row = {"id": len(self.categories) + 1, "name": name}
        self.categories.append(row)
        return row


def test_job_onboarding_reuses_account_case_insensitively(mock_db_session):
    """Salary setup does not create duplicate accounts for casing differences."""
    mock_db_session.add_user(chat_id="salary-user", storage_backend="postgres")
    storage = FakeStorage()
    existing = storage.create_account("Intesa", 0)
    service = RecurringIncomeService(mock_db_session, storage, "salary-user")

    result = service.configure_salary(
        account_name=" intesa ", income_name="Stipendio", amount=1800,
        cadence="monthly", payday_day=27,
    )

    assert result.account_id == existing["id"]
    assert len(storage.fetch_accounts()) == 1


def test_salary_rule_uses_user_currency_and_checking_defaults(mock_db_session):
    """New salary accounts use zero balance, EUR and checking defaults."""
    mock_db_session.add_user(chat_id="salary-defaults", storage_backend="postgres")
    storage = FakeStorage()
    service = RecurringIncomeService(mock_db_session, storage, "salary-defaults")

    service.configure_salary(
        account_name="Conto principale", income_name="Stipendio",
        amount=Decimal("1800"), cadence="monthly", payday_day=27,
    )

    account = storage.fetch_accounts()[0]
    assert account["opening_balance"] == 0
    assert account["currency"] == "EUR"
    assert account["account_type"] == "checking"
