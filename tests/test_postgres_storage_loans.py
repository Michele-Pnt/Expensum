"""
tests/test_postgres_storage_loans.py — CRUD Loan/LoanMonthlyCharge su PostgresStorage,
SQLite in-memory (stesso pattern di test_postgres_storage_savings_goals.py).
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.user_store import Base, User
from src.storage.postgres_storage import PostgresStorage

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def db_engine():
    engine = create_engine("sqlite:///:memory:", echo=False)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
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
    return PostgresStorage(session=db_session, user_id="test_user_1")


def _create_fixed_loan(storage, **overrides):
    fields = dict(
        name="Mutuo casa",
        loan_type="mutuo_casa",
        principal_amount=200000.0,
        disbursement_date=date(2026, 1, 1),
        duration_months=300,
        rate_type="fisso",
        tan=3.0,
    )
    fields.update(overrides)
    return storage.create_loan(**fields)


class TestCreateAndFetchLoan:
    def test_create_returns_dict_with_computed_installment(self, storage):
        result = _create_fixed_loan(storage)
        assert result["id"] is not None
        assert result["status"] == "active"
        assert result["current_installment"] == pytest.approx(948.42, abs=0.5)

    def test_origination_fee_creates_expense_with_loan_id(self, storage, db_session):
        from src.storage.models import Expense

        loan = _create_fixed_loan(storage, origination_fee=500.0)
        expenses = db_session.query(Expense).filter(Expense.loan_id == loan["id"]).all()
        assert len(expenses) == 1
        assert float(expenses[0].amount) == pytest.approx(500.0)

    def test_no_origination_fee_creates_no_expense(self, storage, db_session):
        from src.storage.models import Expense

        loan = _create_fixed_loan(storage)
        expenses = db_session.query(Expense).filter(Expense.loan_id == loan["id"]).all()
        assert expenses == []

    def test_fetch_only_own_user_loans(self, db_session, storage):
        db_session.add(User(chat_id="other_user", is_active=True))
        db_session.commit()
        _create_fixed_loan(storage, name="Mio")
        PostgresStorage(session=db_session, user_id="other_user").create_loan(
            name="Altrui", loan_type="mutuo_casa", principal_amount=100000.0,
            disbursement_date=date(2026, 1, 1), duration_months=120,
            rate_type="fisso", tan=3.0,
        )
        loans = storage.fetch_loans()
        assert [l["name"] for l in loans] == ["Mio"]

    def test_fetch_includes_remaining_time_and_cost_summary(self, storage):
        loan = _create_fixed_loan(storage, duration_months=12, principal_amount=12000.0, tan=3.0)
        storage.record_loan_monthly_charge(loan["id"], date(2026, 2, 1))

        summary = storage.fetch_loans()[0]
        assert summary["remaining_months"] == 11
        assert summary["estimated_end_date"] == "2027-01-01"
        assert summary["remaining_interest"] > 0
        assert summary["next_principal"] > 0
        assert summary["next_interest"] > 0


class TestUpdateLoan:
    def test_simple_field_update(self, storage):
        loan = _create_fixed_loan(storage)
        updated = storage.update_loan(loan["id"], name="Mutuo ristrutturato")
        assert updated["name"] == "Mutuo ristrutturato"

    def test_tan_change_on_fixed_loan_recalculates_installment(self, storage):
        loan = _create_fixed_loan(storage)
        original_installment = loan["current_installment"]
        updated = storage.update_loan(loan["id"], tan=4.0)
        assert updated["current_installment"] != original_installment

    def test_tan_change_on_variable_loan_recalculates_installment(self, storage):
        loan = _create_fixed_loan(storage, rate_type="variabile", tan=3.0)
        original_installment = loan["current_installment"]
        updated = storage.update_loan(loan["id"], tan=4.0)
        assert updated["tan"] == pytest.approx(4.0)
        assert updated["current_installment"] != original_installment

    def test_update_missing_loan_returns_none(self, storage):
        assert storage.update_loan(9999, name="x") is None


class TestDeleteLoan:
    def test_delete_removes_loan(self, storage):
        loan = _create_fixed_loan(storage)
        assert storage.delete_loan(loan["id"]) is True
        assert storage.fetch_loans() == []

    def test_delete_preserves_linked_expenses_as_history(self, storage, db_session):
        from src.storage.models import Expense

        loan = _create_fixed_loan(storage, origination_fee=500.0)
        expense = db_session.query(Expense).filter(Expense.loan_id == loan["id"]).one()

        assert storage.delete_loan(loan["id"]) is True
        db_session.refresh(expense)
        assert expense.loan_id is None
        assert float(expense.amount) == pytest.approx(500.0)

    def test_delete_missing_loan_returns_false(self, storage):
        assert storage.delete_loan(9999) is False


class TestRecordLoanMonthlyCharge:
    def test_creates_interest_expense_with_loan_id(self, storage, db_session):
        from src.storage.models import Expense

        loan = _create_fixed_loan(storage)
        period = date(2026, 2, 1)
        result = storage.record_loan_monthly_charge(loan["id"], period)
        assert result is not None
        assert result["interest_amount"] == pytest.approx(500.0, abs=1.0)  # 200000 * 3% / 12

        expenses = db_session.query(Expense).filter(Expense.loan_id == loan["id"]).all()
        assert len(expenses) == 1
        assert expenses[0].expense_date == period

    def test_creates_fee_expense_when_monthly_fee_set(self, storage, db_session):
        from src.storage.models import Expense

        loan = _create_fixed_loan(storage, monthly_fee=3.0)
        storage.record_loan_monthly_charge(loan["id"], date(2026, 2, 1))
        expenses = db_session.query(Expense).filter(Expense.loan_id == loan["id"]).all()
        assert len(expenses) == 2
        names = {e.name for e in expenses}
        assert any("Interessi" in n for n in names)
        assert any("Spese incasso rata" in n for n in names)

    def test_idempotent_on_same_period(self, storage):
        loan = _create_fixed_loan(storage)
        period = date(2026, 2, 1)
        first = storage.record_loan_monthly_charge(loan["id"], period)
        second = storage.record_loan_monthly_charge(loan["id"], period)
        assert first is not None
        assert second is None

    def test_no_duplicate_expenses_on_rerun(self, storage, db_session):
        from src.storage.models import Expense

        loan = _create_fixed_loan(storage)
        period = date(2026, 2, 1)
        storage.record_loan_monthly_charge(loan["id"], period)
        storage.record_loan_monthly_charge(loan["id"], period)
        expenses = db_session.query(Expense).filter(Expense.loan_id == loan["id"]).all()
        assert len(expenses) == 1

    def test_residual_balance_decreases_across_months(self, storage):
        loan = _create_fixed_loan(storage)
        r1 = storage.record_loan_monthly_charge(loan["id"], date(2026, 2, 1))
        r2 = storage.record_loan_monthly_charge(loan["id"], date(2026, 3, 1))
        assert r2["residual_balance"] < r1["residual_balance"]

    def test_inactive_loan_not_charged(self, storage):
        loan = _create_fixed_loan(storage)
        storage.update_loan(loan["id"], status="closed")
        result = storage.record_loan_monthly_charge(loan["id"], date(2026, 2, 1))
        assert result is None

    def test_full_amortization_closes_loan(self, storage):
        loan = storage.create_loan(
            name="Prestito breve", loan_type="altro", principal_amount=1000.0,
            disbursement_date=date(2026, 1, 1), duration_months=2,
            rate_type="fisso", tan=3.0,
        )
        storage.record_loan_monthly_charge(loan["id"], date(2026, 2, 1))
        result = storage.record_loan_monthly_charge(loan["id"], date(2026, 3, 1))
        assert result["residual_balance"] == pytest.approx(0.0, abs=0.01)
        refreshed = storage.fetch_loans(status="closed")
        assert len(refreshed) == 1
        assert refreshed[0]["id"] == loan["id"]


class TestFetchLoanSchedule:
    def test_schedule_reflects_remaining_months(self, storage):
        loan = _create_fixed_loan(storage, duration_months=12, principal_amount=12000.0, tan=0.0)
        storage.record_loan_monthly_charge(loan["id"], date(2026, 2, 1))
        schedule = storage.fetch_loan_schedule(loan["id"])
        assert len(schedule) == 11
        assert schedule[0]["period"] == 2
