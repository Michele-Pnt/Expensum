"""
tests/test_postgres_storage.py — Test per PostgresStorage su schema 3NF.

Usa SQLite in-memory: nessuna dipendenza da DB reale.
- `Account.opening_balance` è il campo persistito; `balance` è calcolato on-read.
- `MonthlyBalance` non esiste: `fetch_monthly_balances` aggrega da income/expense.
- `create_expense` risolve category_name → category_id al volo.
"""

import pytest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.user_store import Base, User
from src.storage.models import Account, UserCategory, Expense, Income, Subscription, SavedReport
from src.storage.postgres_storage import PostgresStorage

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_engine():
    """Engine SQLite in-memory condiviso per tutto il modulo."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """Schema azzerato e utente di test reinserito a ogni test."""
    Base.metadata.drop_all(db_engine)
    Base.metadata.create_all(db_engine)
    Session = sessionmaker(bind=db_engine)
    session = Session()

    session.add(User(chat_id="test_user_1", username="testuser", is_active=True))
    session.commit()

    yield session
    session.close()


@pytest.fixture
def storage(db_session):
    """PostgresStorage collegato all'utente di test."""
    return PostgresStorage(session=db_session, user_id="test_user_1")


# ---------------------------------------------------------------------------
# 1. get_category_names
# ---------------------------------------------------------------------------

class TestGetCategoryNames:
    def test_returns_empty_list_when_no_categories(self, storage):
        assert storage.get_category_names() == []

    def test_returns_names_for_own_user(self, db_session, storage):
        db_session.add(UserCategory(user_id="test_user_1", name="Cibo"))
        db_session.add(UserCategory(user_id="test_user_1", name="Trasporti"))
        db_session.commit()

        names = storage.get_category_names()
        assert set(names) == {"Cibo", "Trasporti"}

    def test_does_not_return_other_users_categories(self, db_session, storage):
        db_session.add(User(chat_id="other_user", is_active=True))
        db_session.add(UserCategory(user_id="other_user", name="Categoria Aliena"))
        db_session.commit()

        assert storage.get_category_names() == []


# ---------------------------------------------------------------------------
# 2. create_expense — risolve category_name → category_id
# ---------------------------------------------------------------------------

class TestCreateExpense:
    def test_returns_dict_with_expected_keys(self, db_session, storage):
        db_session.add(Account(user_id="test_user_1", name="Conto", opening_balance=500.0))
        db_session.commit()
        acc = db_session.query(Account).filter_by(user_id="test_user_1").first()

        result = storage.create_expense(
            expense_date=date(2026, 4, 10),
            amount=25.50,
            name="Pizza",
            category_name="Cibo",
            account_id=str(acc.id),
        )
        assert result["amount"] == 25.50
        assert result["name"] == "Pizza"
        assert result["category"] == "Cibo"
        assert result["date"] == date(2026, 4, 10)
        assert "id" in result

    def test_creates_category_if_missing(self, db_session, storage):
        """create_expense deve creare la categoria al volo se non esiste."""
        result = storage.create_expense(
            expense_date=date(2026, 4, 1),
            amount=10.0,
            name="Caffè",
            category_name="Bar",
            account_id=None,
        )
        assert result["name"] == "Caffè"
        # La categoria deve essere stata creata
        cats = storage.get_category_names()
        assert "Bar" in cats

    def test_persists_to_db(self, db_session, storage):
        storage.create_expense(
            expense_date=date(2026, 4, 1),
            amount=10.0,
            name="Spesa",
            category_name="Supermercato",
            account_id=None,
        )
        rows = db_session.query(Expense).filter_by(user_id="test_user_1").all()
        assert any(r.name == "Spesa" for r in rows)


# ---------------------------------------------------------------------------
# 3. create_income — con e senza income_type
# ---------------------------------------------------------------------------

class TestCreateIncome:
    def test_returns_dict_with_expected_keys(self, db_session, storage):
        db_session.add(Account(user_id="test_user_1", name="Conto", opening_balance=500.0))
        db_session.commit()
        acc = db_session.query(Account).filter_by(user_id="test_user_1").first()

        result = storage.create_income(
            income_date=date(2026, 4, 1),
            amount=1500.0,
            name="Stipendio aprile",
            account_id=str(acc.id),
            income_type="Stipendio",
        )
        assert result["amount"] == 1500.0
        assert result["name"] == "Stipendio aprile"
        assert result["income_type"] == "Stipendio"
        assert result["date"] == date(2026, 4, 1)
        assert "id" in result

    def test_income_type_nullable(self, db_session, storage):
        db_session.add(Account(user_id="test_user_1", name="Conto", opening_balance=500.0))
        db_session.commit()
        acc = db_session.query(Account).filter_by(user_id="test_user_1").first()

        result = storage.create_income(
            income_date=date(2026, 4, 5),
            amount=50.0,
            name="Rimborso generico",
            account_id=str(acc.id),
        )
        assert result["income_type"] is None

    def test_persists_income_type_to_db(self, db_session, storage):
        db_session.add(Account(user_id="test_user_1", name="Conto", opening_balance=500.0))
        db_session.commit()
        acc = db_session.query(Account).filter_by(user_id="test_user_1").first()

        storage.create_income(
            income_date=date(2026, 4, 2),
            amount=200.0,
            name="Bonus",
            account_id=str(acc.id),
            income_type="Bonus",
        )
        row = db_session.query(Income).filter_by(user_id="test_user_1", name="Bonus").first()
        assert row is not None
        assert row.income_type == "Bonus"


# ---------------------------------------------------------------------------
# 4. fetch_all_transactions
# ---------------------------------------------------------------------------

class TestFetchAllTransactions:
    def test_returns_transactions_in_range(self, db_session, storage):
        db_session.add(Expense(
            user_id="test_user_1", expense_date=date(2026, 4, 5),
            amount=30.0, name="Spesa", category_name="Cibo",
        ))
        db_session.add(Expense(
            user_id="test_user_1", expense_date=date(2026, 3, 1),
            amount=10.0, name="Fuori range", category_name="Bar",
        ))
        db_session.commit()

        results = storage.fetch_all_transactions(date(2026, 4, 1), date(2026, 4, 30))
        assert len(results) == 1
        assert results[0]["name"] == "Spesa"

    def test_returns_empty_when_no_match(self, storage):
        assert storage.fetch_all_transactions(date(2026, 4, 1), date(2026, 4, 30)) == []


# ---------------------------------------------------------------------------
# 5. fetch_monthly_balances — on-read, aggrega da income/expense
# ---------------------------------------------------------------------------

class TestFetchMonthlyBalances:
    def test_aggregates_income_and_expense(self, db_session, storage):
        """fetch_monthly_balances aggrega on-read invece di leggere da MonthlyBalance."""
        db_session.add(Account(user_id="test_user_1", name="Conto", opening_balance=0.0))
        db_session.commit()
        acc = db_session.query(Account).filter_by(user_id="test_user_1").first()

        db_session.add(Income(
            user_id="test_user_1", income_date=date(2026, 4, 5),
            amount=2000.0, name="Stipendio", account_id=acc.id
        ))
        db_session.add(Expense(
            user_id="test_user_1", expense_date=date(2026, 4, 10),
            amount=1200.0, name="Affitto", category_name="Casa", account_id=acc.id
        ))
        db_session.commit()

        results = storage.fetch_monthly_balances(date(2026, 4, 1), date(2026, 4, 30))
        assert len(results) == 1
        assert results[0]["year"] == 2026
        assert results[0]["month"] == 4
        assert results[0]["label"] == "April 2026"
        assert results[0]["net_savings"] == 800.0

    def test_returns_empty_when_no_data(self, storage):
        assert storage.fetch_monthly_balances(date(2026, 1, 1), date(2026, 1, 31)) == []

    def test_get_or_create_monthly_balance_returns_none(self, storage):
        """Postgres non usa MonthlyBalance: ritorna sempre None."""
        assert storage.get_or_create_monthly_balance(date(2026, 4, 1)) is None


# ---------------------------------------------------------------------------
# 6. fetch_income
# ---------------------------------------------------------------------------

class TestFetchIncome:
    def test_returns_income_in_range(self, db_session, storage):
        db_session.add(Account(user_id="test_user_1", name="Conto", opening_balance=0.0))
        db_session.commit()
        acc = db_session.query(Account).filter_by(user_id="test_user_1").first()

        db_session.add(Income(
            user_id="test_user_1", income_date=date(2026, 4, 1),
            amount=1500.0, name="Stipendio", income_type="Stipendio", account_id=acc.id
        ))
        db_session.add(Income(
            user_id="test_user_1", income_date=date(2026, 2, 1),
            amount=50.0, name="Regalo", income_type="Regalo", account_id=acc.id
        ))
        db_session.commit()

        results = storage.fetch_income(date(2026, 4, 1), date(2026, 4, 30))
        assert len(results) == 1
        assert results[0]["name"] == "Stipendio"

    def test_income_type_present_in_result(self, db_session, storage):
        db_session.add(Account(user_id="test_user_1", name="Conto", opening_balance=0.0))
        db_session.commit()
        acc = db_session.query(Account).filter_by(user_id="test_user_1").first()

        db_session.add(Income(
            user_id="test_user_1", income_date=date(2026, 4, 10),
            amount=200.0, name="Bonus", income_type="Bonus", account_id=acc.id
        ))
        db_session.commit()

        results = storage.fetch_income(date(2026, 4, 1), date(2026, 4, 30))
        found = next((r for r in results if r["name"] == "Bonus"), None)
        assert found is not None
        assert found["income_type"] == "Bonus"

    def test_income_type_none_in_result(self, db_session, storage):
        db_session.add(Account(user_id="test_user_1", name="Conto", opening_balance=0.0))
        db_session.commit()
        acc = db_session.query(Account).filter_by(user_id="test_user_1").first()

        db_session.add(Income(
            user_id="test_user_1", income_date=date(2026, 4, 3),
            amount=30.0, name="Rimborso", income_type=None, account_id=acc.id
        ))
        db_session.commit()

        results = storage.fetch_income(date(2026, 4, 1), date(2026, 4, 30))
        found = next((r for r in results if r["name"] == "Rimborso"), None)
        assert found is not None
        assert found["income_type"] is None


# ---------------------------------------------------------------------------
# 7. fetch_accounts — saldo calcolato on-read
# ---------------------------------------------------------------------------

class TestFetchAccounts:
    def test_returns_accounts_for_own_user(self, db_session, storage):
        db_session.add(Account(user_id="test_user_1", name="Conto Corrente", opening_balance=500.0))
        db_session.add(Account(user_id="test_user_1", name="Revolut", opening_balance=200.0))
        db_session.commit()

        results = storage.fetch_accounts()
        assert len(results) == 2
        names = {r["name"] for r in results}
        assert names == {"Conto Corrente", "Revolut"}

    def test_balance_computed_on_read(self, db_session, storage):
        """Il saldo è opening_balance + entrate - uscite, non un campo persistito."""
        db_session.add(Account(user_id="test_user_1", name="Savings", opening_balance=1000.0))
        db_session.commit()
        acc = db_session.query(Account).filter_by(name="Savings").first()

        db_session.add(Income(user_id="test_user_1", income_date=date(2026, 4, 1),
                               amount=500.0, name="Stipendio", account_id=acc.id))
        db_session.add(Expense(user_id="test_user_1", expense_date=date(2026, 4, 2),
                                amount=200.0, name="Affitto", account_id=acc.id))
        db_session.commit()

        result = next(r for r in storage.fetch_accounts() if r["name"] == "Savings")
        assert result["current_balance"] == 1000.0 + 500.0 - 200.0

    def test_account_dict_keys(self, db_session, storage):
        db_session.add(Account(user_id="test_user_1", name="Test", opening_balance=0.0))
        db_session.commit()

        result = next(r for r in storage.fetch_accounts() if r["name"] == "Test")
        assert "id" in result
        assert "name" in result
        assert "current_balance" in result
        assert "opening_balance" in result

    def test_returns_empty_when_no_accounts(self, storage):
        assert storage.fetch_accounts() == []

    def test_does_not_return_other_users_accounts(self, db_session, storage):
        db_session.add(User(chat_id="other_user4", is_active=True))
        db_session.add(Account(user_id="other_user4", name="Conto Alieno", opening_balance=99.0))
        db_session.commit()

        assert storage.fetch_accounts() == []


# ---------------------------------------------------------------------------
# 7. save_report (upsert)
# ---------------------------------------------------------------------------

class TestSaveReport:
    def test_creates_new_report_and_returns_token(self, storage):
        token = storage.save_report(
            user_id="test_user_1",
            report_type="monthly",
            report_date=date(2026, 6, 1),
            text_content="Piano Giugno",
            report_data={"spent_by_cat": {"Cibo": 100.0}},
        )
        assert token != ""

    def test_upsert_same_month_updates_data(self, storage, db_session):
        storage.save_report(
            user_id="test_user_1",
            report_type="monthly",
            report_date=date(2026, 7, 1),
            text_content="Piano Luglio v1",
            report_data={"spent_by_cat": {"Cibo": 100.0}},
        )
        token2 = storage.save_report(
            user_id="test_user_1",
            report_type="monthly",
            report_date=date(2026, 7, 1),
            text_content="Piano Luglio v2",
            report_data={"spent_by_cat": {"Cibo": 200.0}},
        )
        rows = db_session.query(SavedReport).filter(
            SavedReport.user_id == "test_user_1",
            SavedReport.report_date == date(2026, 7, 1),
        ).all()
        assert len(rows) == 1
        assert rows[0].text_content == "Piano Luglio v2"
        assert rows[0].report_data["spent_by_cat"]["Cibo"] == 200.0
        assert rows[0].share_token == token2

    def test_upsert_preserves_token(self, storage, db_session):
        token1 = storage.save_report(
            user_id="test_user_1",
            report_type="monthly",
            report_date=date(2026, 8, 1),
            text_content="Piano Agosto v1",
            report_data=None,
        )
        token2 = storage.save_report(
            user_id="test_user_1",
            report_type="monthly",
            report_date=date(2026, 8, 1),
            text_content="Piano Agosto v2",
            report_data={"spent_by_cat": {"Trasporti": 50.0}},
        )
        assert token1 == token2

    def test_different_months_create_separate_rows(self, storage, db_session):
        storage.save_report(
            user_id="test_user_1",
            report_type="monthly",
            report_date=date(2026, 9, 1),
            text_content="Piano Settembre",
            report_data=None,
        )
        storage.save_report(
            user_id="test_user_1",
            report_type="monthly",
            report_date=date(2026, 10, 1),
            text_content="Piano Ottobre",
            report_data=None,
        )
        rows = db_session.query(SavedReport).filter(
            SavedReport.user_id == "test_user_1",
            SavedReport.report_type == "monthly",
        ).all()
        assert len(rows) >= 2

        assert storage.fetch_accounts() == []
