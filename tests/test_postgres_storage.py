"""
tests/test_postgres_storage.py — Test per PostgresStorage e la colonna income_type.

Usa SQLite in-memory per tutti i test: nessuna dipendenza da DB reale.
Copre tutti i 7 metodi astratti di FinancialStorage.
"""

import pytest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.user_store import Base, User
from src.storage.models import Account, UserCategory, Expense, Income, MonthlyBalance
from src.storage.postgres_storage import PostgresStorage


# ---------------------------------------------------------------------------
# Fixture: engine + session SQLite in-memory, azzerato per ogni test
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
    """Session SQLite in-memory con tutte le tabelle create da zero."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Utente di test — necessario per soddisfare le FK constraint delle tabelle finanziarie
    user = User(chat_id="test_user_1", username="testuser", is_active=True)
    session.add(user)
    session.commit()

    yield session

    session.close()
    engine.dispose()


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
        # Secondo utente
        db_session.add(User(chat_id="other_user", is_active=True))
        db_session.add(UserCategory(user_id="other_user", name="Categoria Aliena"))
        db_session.commit()

        assert storage.get_category_names() == []


# ---------------------------------------------------------------------------
# 2. create_expense
# ---------------------------------------------------------------------------

class TestCreateExpense:
    def test_returns_dict_with_expected_keys(self, storage):
        result = storage.create_expense(
            expense_date=date(2026, 4, 10),
            amount=25.50,
            name="Pizza",
            category_name="Cibo",
            account_id="acc_123",
        )
        assert result["amount"] == 25.50
        assert result["name"] == "Pizza"
        assert result["category"] == "Cibo"
        assert result["account_id"] == "acc_123"
        assert result["date"] == date(2026, 4, 10)
        assert "id" in result

    def test_persists_to_db(self, db_session, storage):
        storage.create_expense(
            expense_date=date(2026, 4, 1),
            amount=10.0,
            name="Caffè",
            category_name="Bar",
            account_id="acc_1",
        )
        rows = db_session.query(Expense).filter_by(user_id="test_user_1").all()
        assert len(rows) == 1
        assert rows[0].name == "Caffè"


# ---------------------------------------------------------------------------
# 3. create_income — con e senza income_type
# ---------------------------------------------------------------------------

class TestCreateIncome:
    def test_returns_dict_with_expected_keys(self, storage):
        result = storage.create_income(
            income_date=date(2026, 4, 1),
            amount=1500.0,
            name="Stipendio aprile",
            account_id="acc_123",
            income_type="Stipendio",
        )
        assert result["amount"] == 1500.0
        assert result["name"] == "Stipendio aprile"
        assert result["account_id"] == "acc_123"
        assert result["income_type"] == "Stipendio"
        assert result["date"] == date(2026, 4, 1)
        assert "id" in result

    def test_income_type_nullable(self, storage):
        """income_type può essere None (entrata senza tipo specificato)."""
        result = storage.create_income(
            income_date=date(2026, 4, 5),
            amount=50.0,
            name="Rimborso generico",
            account_id="acc_123",
        )
        assert result["income_type"] is None

    def test_persists_income_type_to_db(self, db_session, storage):
        storage.create_income(
            income_date=date(2026, 4, 2),
            amount=200.0,
            name="Bonus",
            account_id="acc_1",
            income_type="Bonus",
        )
        row = db_session.query(Income).filter_by(user_id="test_user_1").first()
        assert row.income_type == "Bonus"


# ---------------------------------------------------------------------------
# 4. fetch_all_transactions
# ---------------------------------------------------------------------------

class TestFetchAllTransactions:
    def test_returns_transactions_in_range(self, db_session, storage):
        db_session.add(Expense(
            user_id="test_user_1", expense_date=date(2026, 4, 5),
            amount=30.0, name="Spesa", category_name="Cibo", account_id="acc_1",
        ))
        db_session.add(Expense(
            user_id="test_user_1", expense_date=date(2026, 3, 1),
            amount=10.0, name="Fuori range", category_name="Bar", account_id="acc_1",
        ))
        db_session.commit()

        results = storage.fetch_all_transactions(date(2026, 4, 1), date(2026, 4, 30))
        assert len(results) == 1
        assert results[0]["name"] == "Spesa"

    def test_returns_empty_when_no_match(self, storage):
        results = storage.fetch_all_transactions(date(2026, 4, 1), date(2026, 4, 30))
        assert results == []

    def test_does_not_return_other_users_transactions(self, db_session, storage):
        db_session.add(User(chat_id="other_user2", is_active=True))
        db_session.add(Expense(
            user_id="other_user2", expense_date=date(2026, 4, 5),
            amount=99.0, name="Non mia", category_name="Altro", account_id="acc_x",
        ))
        db_session.commit()

        assert storage.fetch_all_transactions(date(2026, 4, 1), date(2026, 4, 30)) == []


# ---------------------------------------------------------------------------
# 5. fetch_monthly_balances
# ---------------------------------------------------------------------------

class TestFetchMonthlyBalances:
    def test_returns_balance_in_range(self, db_session, storage):
        db_session.add(MonthlyBalance(
            user_id="test_user_1", month=date(2026, 4, 1),
            income_total=2000.0, expense_total=1200.0, net_savings=800.0,
        ))
        db_session.add(MonthlyBalance(
            user_id="test_user_1", month=date(2026, 2, 1),
            income_total=1800.0, expense_total=1100.0, net_savings=700.0,
        ))
        db_session.commit()

        results = storage.fetch_monthly_balances(date(2026, 3, 1), date(2026, 4, 30))
        assert len(results) == 1
        assert results[0]["net_savings"] == 800.0
        assert results[0]["income_total"] == 2000.0
        assert results[0]["expense_total"] == 1200.0

    def test_returns_empty_when_no_match(self, storage):
        assert storage.fetch_monthly_balances(date(2026, 1, 1), date(2026, 1, 31)) == []


# ---------------------------------------------------------------------------
# 6. fetch_income — verifica che income_type sia incluso nel risultato
# ---------------------------------------------------------------------------

class TestFetchIncome:
    def test_returns_income_in_range(self, db_session, storage):
        db_session.add(Income(
            user_id="test_user_1", income_date=date(2026, 4, 1),
            amount=1500.0, name="Stipendio", account_id="acc_1", income_type="Stipendio",
        ))
        db_session.add(Income(
            user_id="test_user_1", income_date=date(2026, 2, 1),
            amount=50.0, name="Regalo", account_id="acc_1", income_type="Regalo",
        ))
        db_session.commit()

        results = storage.fetch_income(date(2026, 4, 1), date(2026, 4, 30))
        assert len(results) == 1
        assert results[0]["name"] == "Stipendio"

    def test_income_type_present_in_result(self, db_session, storage):
        """Verifica che income_type sia incluso nel dict restituito da fetch_income."""
        db_session.add(Income(
            user_id="test_user_1", income_date=date(2026, 4, 10),
            amount=200.0, name="Bonus", account_id="acc_1", income_type="Bonus",
        ))
        db_session.commit()

        results = storage.fetch_income(date(2026, 4, 1), date(2026, 4, 30))
        assert len(results) == 1
        assert "income_type" in results[0], "income_type deve essere presente nel dict restituito"
        assert results[0]["income_type"] == "Bonus"

    def test_income_type_none_in_result(self, db_session, storage):
        """income_type=None deve essere restituito correttamente (non omesso)."""
        db_session.add(Income(
            user_id="test_user_1", income_date=date(2026, 4, 3),
            amount=30.0, name="Rimborso", account_id="acc_1", income_type=None,
        ))
        db_session.commit()

        results = storage.fetch_income(date(2026, 4, 1), date(2026, 4, 30))
        assert "income_type" in results[0]
        assert results[0]["income_type"] is None

    def test_does_not_return_other_users_income(self, db_session, storage):
        db_session.add(User(chat_id="other_user3", is_active=True))
        db_session.add(Income(
            user_id="other_user3", income_date=date(2026, 4, 5),
            amount=999.0, name="Non mia", account_id="acc_x", income_type="Stipendio",
        ))
        db_session.commit()

        assert storage.fetch_income(date(2026, 4, 1), date(2026, 4, 30)) == []


# ---------------------------------------------------------------------------
# 7. fetch_accounts
# ---------------------------------------------------------------------------

class TestFetchAccounts:
    def test_returns_accounts_for_own_user(self, db_session, storage):
        db_session.add(Account(user_id="test_user_1", name="Conto Corrente", balance=500.0, currency="EUR"))
        db_session.add(Account(user_id="test_user_1", name="Revolut", balance=200.0, currency="EUR"))
        db_session.commit()

        results = storage.fetch_accounts()
        assert len(results) == 2
        names = {r["name"] for r in results}
        assert names == {"Conto Corrente", "Revolut"}

    def test_account_dict_keys(self, db_session, storage):
        db_session.add(Account(user_id="test_user_1", name="Savings", balance=1000.0, currency="EUR"))
        db_session.commit()

        result = storage.fetch_accounts()[0]
        assert "id" in result
        assert result["name"] == "Savings"
        assert result["balance"] == 1000.0
        assert result["currency"] == "EUR"

    def test_returns_empty_when_no_accounts(self, storage):
        assert storage.fetch_accounts() == []

    def test_does_not_return_other_users_accounts(self, db_session, storage):
        db_session.add(User(chat_id="other_user4", is_active=True))
        db_session.add(Account(user_id="other_user4", name="Conto Alieno", balance=99.0))
        db_session.commit()

        assert storage.fetch_accounts() == []
