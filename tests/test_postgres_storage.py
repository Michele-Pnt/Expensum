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
from src.storage.models import (
    Account, UserCategory, UserIncomeCategory, Expense, Income, Subscription, SavedReport, Transfer,
)
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


class TestDeleteIncomeCategory:
    def test_deletes_category_and_reassigns_linked_incomes_to_fallback(self, db_session, storage):
        """La cancellazione replica il ciclo spese: storico salvo su Altra entrata."""
        account = Account(user_id="test_user_1", name="Conto", opening_balance=0)
        category = UserIncomeCategory(user_id="test_user_1", name="Bonus progetto")
        fallback = UserIncomeCategory(user_id="test_user_1", name="Altra entrata")
        db_session.add_all([account, category, fallback])
        db_session.flush()
        income = Income(
            user_id="test_user_1", income_date=date(2026, 9, 1), amount=100,
            name="Premio", account_id=account.id, income_type="Bonus progetto",
            income_category_id=category.id,
        )
        db_session.add(income)
        db_session.commit()

        result = storage.delete_income_category(category.id)

        assert result == {"incomes": 1}
        assert db_session.get(UserIncomeCategory, category.id) is None
        assert db_session.get(Income, income.id).income_category_id == fallback.id
        assert db_session.get(Income, income.id).income_type == "Altra entrata"

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


# ---------------------------------------------------------------------------
# 2b. create_subscription — risolve category_name → category_id (usato da
#     src/subscription_detector.py, che non conosce id interni del backend)
# ---------------------------------------------------------------------------

class TestCreateSubscription:
    def test_resolves_category_name_to_id(self, db_session, storage):
        db_session.add(UserCategory(user_id="test_user_1", name="Abbonamenti"))
        db_session.commit()
        cat = db_session.query(UserCategory).filter_by(user_id="test_user_1").first()

        result = storage.create_subscription(
            "Netflix", amount=9.99, sub_type="monthly", category_name="Abbonamenti",
        )
        assert result["category_id"] == cat.id
        assert result["amount"] == 9.99
        assert result["sub_type"] == "monthly"

    def test_explicit_category_id_wins_over_category_name(self, db_session, storage):
        db_session.add(UserCategory(user_id="test_user_1", name="Abbonamenti"))
        db_session.commit()

        result = storage.create_subscription(
            "Netflix", category_id=999, category_name="Abbonamenti",
        )
        assert result["category_id"] == 999

    def test_unknown_category_name_gets_created_on_the_fly(self, storage):
        """Stesso comportamento di create_expense: _resolve_category_id crea la
        categoria al volo se non esiste, non lascia mai un riferimento a vuoto."""
        result = storage.create_subscription("Netflix", category_name="Categoria Fantasma")
        assert result["category_id"] is not None
        assert "Categoria Fantasma" in storage.get_category_names()


# ---------------------------------------------------------------------------
# 3. create_category / update_category / get_categories — description
# ---------------------------------------------------------------------------

class TestCategoryDescription:
    def test_create_category_with_description(self, storage):
        result = storage.create_category(
            "Cene/Pranzi", description="spese per uscire a cena o pranzo",
            description_summary="Spese per uscire a cena o pranzo fuori casa",
        )
        assert result["description"] == "spese per uscire a cena o pranzo"
        assert result["description_summary"] == "Spese per uscire a cena o pranzo fuori casa"

    def test_create_category_without_description_defaults_to_none(self, storage):
        result = storage.create_category("Shopping")
        assert result["description"] is None
        assert result["description_summary"] is None

    def test_get_categories_includes_description(self, storage):
        storage.create_category("Fumo", description="sigarette e svapo", description_summary="Sigarette e svapo")
        cats = storage.get_categories()
        fumo = next(c for c in cats if c["name"] == "Fumo")
        assert fumo["description"] == "sigarette e svapo"
        assert fumo["description_summary"] == "Sigarette e svapo"

    def test_update_category_sets_description_and_summary_together(self, storage):
        created = storage.create_category("Cinema")
        updated = storage.update_category(
            created["id"], description="film e popcorn", description_summary="Film e popcorn al cinema",
        )
        assert updated["description"] == "film e popcorn"
        assert updated["description_summary"] == "Film e popcorn al cinema"

    def test_update_category_without_description_leaves_existing_untouched(self, storage):
        created = storage.create_category("Vacanze", description="voli e hotel", description_summary="Voli e hotel")
        updated = storage.update_category(created["id"], monthly_budget=100.0)
        assert updated["description"] == "voli e hotel"
        assert updated["description_summary"] == "Voli e hotel"
        assert updated["monthly_budget"] == 100.0

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
    def test_income_category_id_uses_canonical_owned_category(self, db_session, storage):
        """The structured ID wins over a stale client-side category name."""
        db_session.add(Account(user_id="test_user_1", name="Conto", opening_balance=0))
        db_session.commit()
        account = db_session.query(Account).filter_by(user_id="test_user_1").one()
        category = storage.create_income_category("Consulenza")

        result = storage.create_income(
            date(2026, 9, 1), 100, "Cliente", str(account.id),
            income_category_id=category["id"], income_category_name="Nome obsoleto",
        )

        assert result["income_category_id"] == category["id"]
        assert result["income_category"] == "Consulenza"
        assert result["income_type"] == "Consulenza"

    def test_income_category_id_rejects_another_tenant(self, db_session, storage):
        """An income may never point at a category owned by another tenant."""
        db_session.add_all([
            Account(user_id="test_user_1", name="Conto", opening_balance=0),
            UserIncomeCategory(user_id="test_user_2", name="Riservata"),
        ])
        db_session.commit()
        account = db_session.query(Account).filter_by(user_id="test_user_1").one()
        foreign = db_session.query(UserIncomeCategory).filter_by(user_id="test_user_2").one()

        with pytest.raises(ValueError, match="Income category not found"):
            storage.create_income(
                date(2026, 9, 1), 100, "Cliente", str(account.id),
                income_category_id=foreign.id,
            )

    def test_create_income_resolves_user_category_and_dual_writes_legacy(self, db_session, storage):
        """A new income uses the category FK while keeping the legacy value readable."""
        db_session.add(Account(user_id="test_user_1", name="Conto", opening_balance=0))
        db_session.commit()
        account = db_session.query(Account).filter_by(user_id="test_user_1").one()

        result = storage.create_income(
            date(2026, 9, 1), 1500, "Stipendio settembre", str(account.id),
            income_category_name="Stipendio",
        )

        assert result["income_category"] == "Stipendio"
        assert result["income_category_id"] is not None
        assert result["income_type"] == "Stipendio"

    def test_renaming_income_category_updates_legacy_income_type(self, db_session, storage):
        """Rename keeps the legacy income_type consistent with the canonical FK."""
        category = storage.create_income_category("Freelance")
        account = Account(user_id="test_user_1", name="Conto", opening_balance=0)
        db_session.add(account)
        db_session.flush()
        db_session.add(Income(
            user_id="test_user_1", income_date=date(2026, 9, 1), amount=100,
            name="Consulenza", account_id=account.id, income_type="Freelance",
            income_category_id=category["id"],
        ))
        db_session.commit()

        storage.update_income_category(category["id"], name="Consulenza")

        assert db_session.query(Income).one().income_type == "Consulenza"

    def test_income_category_description_can_be_cleared(self, storage):
        """An empty description removes stale AI context instead of preserving it."""
        category = storage.create_income_category(
            "Progetti", description="Compensi progetto", description_summary="Compensi progetto",
        )

        updated = storage.update_income_category(
            category["id"], description=None, description_summary=None,
        )

        assert updated is not None
        assert updated["description"] is None
        assert updated["description_summary"] is None

    def test_income_category_creation_rejects_case_insensitive_duplicate(self, storage):
        """Case variants must not make resolution choose an arbitrary category."""
        storage.create_income_category("Freelance")
        with pytest.raises(Exception):
            storage.create_income_category("freelance")
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

    def test_missing_income_type_dual_writes_fallback_category(self, db_session, storage):
        db_session.add(Account(user_id="test_user_1", name="Conto", opening_balance=500.0))
        db_session.commit()
        acc = db_session.query(Account).filter_by(user_id="test_user_1").first()

        result = storage.create_income(
            income_date=date(2026, 4, 5),
            amount=50.0,
            name="Rimborso generico",
            account_id=str(acc.id),
        )
        assert result["income_type"] == "Altra entrata"
        assert result["income_category"] == "Altra entrata"

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
        assert row.income_type == "Bonus lavorativo"
        assert row.income_category_id is not None


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

    def test_aggregates_income_only_no_expense(self, db_session, storage):
        """Un mese con solo entrate (nessuna spesa) non deve esplodere su Decimal/float miste."""
        db_session.add(Account(user_id="test_user_1", name="Conto", opening_balance=0.0))
        db_session.commit()
        acc = db_session.query(Account).filter_by(user_id="test_user_1").first()

        db_session.add(Income(
            user_id="test_user_1", income_date=date(2026, 5, 5),
            amount=1500.0, name="Stipendio", account_id=acc.id
        ))
        db_session.commit()

        results = storage.fetch_monthly_balances(date(2026, 5, 1), date(2026, 5, 31))
        assert len(results) == 1
        assert results[0]["net_savings"] == 1500.0

    def test_aggregates_expense_only_no_income(self, db_session, storage):
        """Un mese con sole spese (nessuna entrata) non deve esplodere su Decimal/float miste."""
        db_session.add(Account(user_id="test_user_1", name="Conto", opening_balance=0.0))
        db_session.commit()
        acc = db_session.query(Account).filter_by(user_id="test_user_1").first()

        db_session.add(Expense(
            user_id="test_user_1", expense_date=date(2026, 6, 10),
            amount=300.0, name="Affitto", category_name="Casa", account_id=acc.id
        ))
        db_session.commit()

        results = storage.fetch_monthly_balances(date(2026, 6, 1), date(2026, 6, 30))
        assert len(results) == 1
        assert results[0]["net_savings"] == -300.0

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
# 6b. create_transfer / fetch_transfers
# ---------------------------------------------------------------------------

class TestCreateTransfer:
    def test_creates_transfer_and_updates_both_balances(self, db_session, storage):
        db_session.add(Account(user_id="test_user_1", name="Corrente", opening_balance=1000.0))
        db_session.add(Account(user_id="test_user_1", name="Risparmio", opening_balance=200.0))
        db_session.commit()
        corrente = db_session.query(Account).filter_by(name="Corrente").first()
        risparmio = db_session.query(Account).filter_by(name="Risparmio").first()

        storage.create_transfer(
            transfer_date=date(2026, 4, 1),
            amount=300.0,
            from_account_id=corrente.id,
            to_account_id=risparmio.id,
            name="Giroconto",
        )

        accounts = {a["name"]: a["current_balance"] for a in storage.fetch_accounts()}
        assert accounts["Corrente"] == 1000.0 - 300.0
        assert accounts["Risparmio"] == 200.0 + 300.0

    def test_rejects_same_account(self, db_session, storage):
        db_session.add(Account(user_id="test_user_1", name="Solo", opening_balance=100.0))
        db_session.commit()
        acc = db_session.query(Account).filter_by(name="Solo").first()

        with pytest.raises(ValueError):
            storage.create_transfer(
                transfer_date=date(2026, 4, 1),
                amount=50.0,
                from_account_id=acc.id,
                to_account_id=acc.id,
            )

    def test_amount_is_stored_positive(self, db_session, storage):
        db_session.add(Account(user_id="test_user_1", name="A", opening_balance=0.0))
        db_session.add(Account(user_id="test_user_1", name="B", opening_balance=0.0))
        db_session.commit()
        a = db_session.query(Account).filter_by(name="A").first()
        b = db_session.query(Account).filter_by(name="B").first()

        result = storage.create_transfer(
            transfer_date=date(2026, 4, 1), amount=-75.0, from_account_id=a.id, to_account_id=b.id,
        )
        assert result["amount"] == 75.0


class TestFetchTransfers:
    def test_returns_transfers_in_range(self, db_session, storage):
        db_session.add(Account(user_id="test_user_1", name="A", opening_balance=0.0))
        db_session.add(Account(user_id="test_user_1", name="B", opening_balance=0.0))
        db_session.commit()
        a = db_session.query(Account).filter_by(name="A").first()
        b = db_session.query(Account).filter_by(name="B").first()

        storage.create_transfer(date(2026, 4, 15), 100.0, a.id, b.id)

        results = storage.fetch_transfers(date(2026, 4, 1), date(2026, 4, 30))
        assert len(results) == 1
        assert results[0]["amount"] == 100.0
        assert results[0]["from_account_id"] == a.id
        assert results[0]["to_account_id"] == b.id

    def test_does_not_return_other_users_transfers(self, db_session, storage):
        db_session.add(User(chat_id="other_user5", is_active=True))
        db_session.add(Account(user_id="other_user5", name="Alieno1", opening_balance=0.0))
        db_session.add(Account(user_id="other_user5", name="Alieno2", opening_balance=0.0))
        db_session.commit()
        a = db_session.query(Account).filter_by(name="Alieno1").first()
        b = db_session.query(Account).filter_by(name="Alieno2").first()
        db_session.add(Transfer(user_id="other_user5", from_account_id=a.id, to_account_id=b.id,
                                 amount=10.0, transfer_date=date(2026, 4, 1)))
        db_session.commit()

        assert storage.fetch_transfers(date(2026, 4, 1), date(2026, 4, 30)) == []


class TestUpdateTransfer:
    def test_updates_amount_and_rebalances_both_accounts(self, db_session, storage):
        db_session.add(Account(user_id="test_user_1", name="Corrente", opening_balance=1000.0))
        db_session.add(Account(user_id="test_user_1", name="Risparmio", opening_balance=200.0))
        db_session.commit()
        corrente = db_session.query(Account).filter_by(name="Corrente").first()
        risparmio = db_session.query(Account).filter_by(name="Risparmio").first()
        created = storage.create_transfer(
            transfer_date=date(2026, 4, 1), amount=300.0,
            from_account_id=corrente.id, to_account_id=risparmio.id, name="Giroconto",
        )

        result = storage.update_transfer(created["id"], amount=500.0)

        assert result["amount"] == 500.0
        accounts = {a["name"]: a["current_balance"] for a in storage.fetch_accounts()}
        assert accounts["Corrente"] == 1000.0 - 500.0
        assert accounts["Risparmio"] == 200.0 + 500.0

    def test_swapping_accounts_updates_balances(self, db_session, storage):
        db_session.add(Account(user_id="test_user_1", name="A", opening_balance=0.0))
        db_session.add(Account(user_id="test_user_1", name="B", opening_balance=0.0))
        db_session.add(Account(user_id="test_user_1", name="C", opening_balance=0.0))
        db_session.commit()
        a = db_session.query(Account).filter_by(name="A").first()
        b = db_session.query(Account).filter_by(name="B").first()
        c = db_session.query(Account).filter_by(name="C").first()
        created = storage.create_transfer(date(2026, 4, 1), 100.0, a.id, b.id)

        storage.update_transfer(created["id"], to_account_id=c.id)

        accounts = {acc["name"]: acc["current_balance"] for acc in storage.fetch_accounts()}
        assert accounts["A"] == -100.0
        assert accounts["B"] == 0.0
        assert accounts["C"] == 100.0

    def test_rejects_same_from_and_to_account(self, db_session, storage):
        db_session.add(Account(user_id="test_user_1", name="A", opening_balance=0.0))
        db_session.add(Account(user_id="test_user_1", name="B", opening_balance=0.0))
        db_session.commit()
        a = db_session.query(Account).filter_by(name="A").first()
        b = db_session.query(Account).filter_by(name="B").first()
        created = storage.create_transfer(date(2026, 4, 1), 100.0, a.id, b.id)

        with pytest.raises(ValueError):
            storage.update_transfer(created["id"], to_account_id=a.id)

    def test_returns_none_for_missing_transfer(self, storage):
        assert storage.update_transfer(999999, amount=10.0) is None

    def test_does_not_update_other_users_transfer(self, db_session, storage):
        db_session.add(User(chat_id="other_user6", is_active=True))
        db_session.add(Account(user_id="other_user6", name="Alieno1", opening_balance=0.0))
        db_session.add(Account(user_id="other_user6", name="Alieno2", opening_balance=0.0))
        db_session.commit()
        a = db_session.query(Account).filter_by(name="Alieno1").first()
        b = db_session.query(Account).filter_by(name="Alieno2").first()
        other_transfer = Transfer(
            user_id="other_user6", from_account_id=a.id, to_account_id=b.id,
            amount=10.0, transfer_date=date(2026, 4, 1),
        )
        db_session.add(other_transfer)
        db_session.commit()

        assert storage.update_transfer(other_transfer.id, amount=999.0) is None


class TestDeleteTransfer:
    def test_deletes_transfer_and_restores_balances(self, db_session, storage):
        db_session.add(Account(user_id="test_user_1", name="Corrente", opening_balance=1000.0))
        db_session.add(Account(user_id="test_user_1", name="Risparmio", opening_balance=200.0))
        db_session.commit()
        corrente = db_session.query(Account).filter_by(name="Corrente").first()
        risparmio = db_session.query(Account).filter_by(name="Risparmio").first()
        created = storage.create_transfer(
            transfer_date=date(2026, 4, 1), amount=300.0,
            from_account_id=corrente.id, to_account_id=risparmio.id,
        )

        assert storage.delete_transfer(created["id"]) is True

        accounts = {a["name"]: a["current_balance"] for a in storage.fetch_accounts()}
        assert accounts["Corrente"] == 1000.0
        assert accounts["Risparmio"] == 200.0

    def test_returns_false_for_missing_transfer(self, storage):
        assert storage.delete_transfer(999999) is False

    def test_does_not_delete_other_users_transfer(self, db_session, storage):
        db_session.add(User(chat_id="other_user7", is_active=True))
        db_session.add(Account(user_id="other_user7", name="Alieno1", opening_balance=0.0))
        db_session.add(Account(user_id="other_user7", name="Alieno2", opening_balance=0.0))
        db_session.commit()
        a = db_session.query(Account).filter_by(name="Alieno1").first()
        b = db_session.query(Account).filter_by(name="Alieno2").first()
        other_transfer = Transfer(
            user_id="other_user7", from_account_id=a.id, to_account_id=b.id,
            amount=10.0, transfer_date=date(2026, 4, 1),
        )
        db_session.add(other_transfer)
        db_session.commit()

        assert storage.delete_transfer(other_transfer.id) is False


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
