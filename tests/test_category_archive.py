"""
tests/test_category_archive.py — Archiviazione e cancellazione delle categorie.

Copre i due comportamenti nuovi e le due trappole del vincolo di unicità:
- una categoria archiviata sparisce da dove si *sceglie* una categoria ma resta
  nelle letture di storico;
- registrare una spesa col nome di una categoria archiviata la riattiva invece di
  creare un duplicato (che violerebbe uq_user_categories_user_name);
- la cancellazione riassegna spese, abbonamenti e obiettivi in una sola transazione
  invece di fallire con ForeignKeyViolation.

SQLite in-memory, stesso pattern di tests/test_postgres_storage.py.
"""

import pytest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.user_store import Base, User
from src.storage.models import (
    Account, UserCategory, Expense, Subscription, SavingsGoal, CategoryCandidate,
)
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
    session = sessionmaker(bind=db_engine)()
    session.add(User(chat_id="u1", username="tester", is_active=True))
    session.commit()
    yield session
    session.close()


@pytest.fixture
def storage(db_session):
    return PostgresStorage(session=db_session, user_id="u1")


def _category(storage, name):
    return storage.create_category(name)["id"]


class TestArchiveHidesFromChoices:
    def test_archived_category_is_hidden_by_default(self, storage):
        cat_id = _category(storage, "Ristoranti")
        _category(storage, "Spesa")

        storage.set_category_archived(cat_id, True)

        assert storage.get_category_names() == ["Spesa"]
        assert [c["name"] for c in storage.get_categories()] == ["Spesa"]

    def test_archived_category_visible_when_requested(self, storage):
        cat_id = _category(storage, "Ristoranti")
        storage.set_category_archived(cat_id, True)

        names = storage.get_category_names(include_archived=True)
        assert names == ["Ristoranti"]

        full = storage.fetch_categories_full(include_archived=True)
        assert full[0]["archived"] is True
        assert full[0]["archived_at"] is not None

    def test_unarchive_restores_visibility(self, storage):
        cat_id = _category(storage, "Ristoranti")
        storage.set_category_archived(cat_id, True)
        storage.set_category_archived(cat_id, False)

        assert storage.get_category_names() == ["Ristoranti"]

    def test_archiving_preserves_existing_expenses(self, storage):
        """Lo storico non si tocca: è la differenza rispetto alla cancellazione."""
        cat_id = _category(storage, "Ristoranti")
        storage.create_expense(date(2026, 5, 1), 30.0, "Pizza", "Ristoranti", None)

        storage.set_category_archived(cat_id, True)

        expenses = storage.fetch_all_transactions(date(2026, 1, 1), date(2026, 12, 31))
        assert len(expenses) == 1
        assert expenses[0]["category"] == "Ristoranti"

    def test_set_archived_on_missing_category_returns_none(self, storage):
        assert storage.set_category_archived(9999, True) is None


class TestArchivedNameCollision:
    def test_expense_on_archived_category_reactivates_it(self, storage):
        """La trappola: creare un duplicato violerebbe lo unique constraint."""
        cat_id = _category(storage, "Ristoranti")
        storage.set_category_archived(cat_id, True)

        storage.create_expense(date(2026, 5, 1), 30.0, "Pizza", "Ristoranti", None)

        assert storage.get_category_names() == ["Ristoranti"]
        all_cats = storage.fetch_categories_full(include_archived=True)
        assert len(all_cats) == 1, "nessun duplicato creato"
        assert all_cats[0]["archived"] is False
        assert all_cats[0]["id"] == cat_id

    def test_reactivation_is_case_insensitive(self, storage):
        cat_id = _category(storage, "Ristoranti")
        storage.set_category_archived(cat_id, True)

        storage.create_expense(date(2026, 5, 1), 30.0, "Pizza", "ristoranti", None)

        assert len(storage.fetch_categories_full(include_archived=True)) == 1


class TestCategoryUsage:
    def test_counts_dependents(self, storage, db_session):
        cat_id = _category(storage, "Ristoranti")
        storage.create_expense(date(2026, 5, 1), 30.0, "Pizza", "Ristoranti", None)
        storage.create_expense(date(2026, 5, 2), 12.0, "Bar", "Ristoranti", None)
        db_session.add(Subscription(user_id="u1", name="Netflix", category_id=cat_id))
        db_session.add(SavingsGoal(user_id="u1", goal_type="category_spending_reduction",
                                   name="Meno ristoranti", target_amount=100, category_id=cat_id))
        db_session.commit()

        assert storage.get_category_usage(cat_id) == {
            "expenses": 2, "subscriptions": 1, "goals": 1,
        }

    def test_returns_none_for_missing_category(self, storage):
        assert storage.get_category_usage(9999) is None


class TestDeleteWithReassignment:
    def test_reassigns_expenses_to_fallback(self, storage):
        cat_id = _category(storage, "Ristoranti")
        _category(storage, "Altro")
        storage.create_expense(date(2026, 5, 1), 30.0, "Pizza", "Ristoranti", None)

        result = storage.delete_category(cat_id)

        assert result == {"expenses": 1, "subscriptions": 0, "goals": 0}
        expenses = storage.fetch_all_transactions(date(2026, 1, 1), date(2026, 12, 31))
        assert expenses[0]["category"] == "Altro"
        assert "Ristoranti" not in storage.get_category_names(include_archived=True)

    def test_creates_fallback_when_missing(self, storage):
        cat_id = _category(storage, "Ristoranti")
        storage.create_expense(date(2026, 5, 1), 30.0, "Pizza", "Ristoranti", None)

        storage.delete_category(cat_id)

        assert storage.get_category_names() == ["Altro"]

    def test_reassigns_to_explicit_target(self, storage):
        source = _category(storage, "Ristoranti")
        target = _category(storage, "Svago")
        storage.create_expense(date(2026, 5, 1), 30.0, "Pizza", "Ristoranti", None)

        storage.delete_category(source, reassign_to=target)

        expenses = storage.fetch_all_transactions(date(2026, 1, 1), date(2026, 12, 31))
        assert expenses[0]["category"] == "Svago"

    def test_reassigns_subscriptions_goals_and_candidates(self, storage, db_session):
        cat_id = _category(storage, "Ristoranti")
        target = _category(storage, "Svago")
        db_session.add(Subscription(user_id="u1", name="Netflix", category_id=cat_id))
        db_session.add(SavingsGoal(user_id="u1", goal_type="category_spending_reduction",
                                   name="Meno ristoranti", target_amount=100, category_id=cat_id))
        db_session.add(CategoryCandidate(user_id="u1", normalized_name="pizzeria",
                                         display_name="Pizzeria",
                                         fallback_category_id=cat_id))
        db_session.commit()

        result = storage.delete_category(cat_id, reassign_to=target)

        assert result == {"expenses": 0, "subscriptions": 1, "goals": 1}
        assert db_session.query(Subscription).one().category_id == target
        assert db_session.query(SavingsGoal).one().category_id == target
        # I candidati seguono senza comparire nel conteggio: sono stato del matcher.
        assert db_session.query(CategoryCandidate).one().fallback_category_id == target

    def test_rejects_reassignment_to_itself(self, storage):
        cat_id = _category(storage, "Ristoranti")
        with pytest.raises(ValueError):
            storage.delete_category(cat_id, reassign_to=cat_id)

    def test_rejects_unknown_target(self, storage):
        cat_id = _category(storage, "Ristoranti")
        with pytest.raises(ValueError):
            storage.delete_category(cat_id, reassign_to=9999)

    def test_returns_none_for_missing_category(self, storage):
        assert storage.delete_category(9999) is None

    def test_deleting_fallback_itself_moves_records_to_a_new_one(self, storage):
        """Caso limite: la categoria da cancellare è proprio "Altro"."""
        cat_id = _category(storage, "Altro")
        storage.create_expense(date(2026, 5, 1), 30.0, "Varie", "Altro", None)

        result = storage.delete_category(cat_id)

        assert result["expenses"] == 1
        remaining = storage.get_category_names()
        assert len(remaining) == 1
        expenses = storage.fetch_all_transactions(date(2026, 1, 1), date(2026, 12, 31))
        assert expenses[0]["category"] == remaining[0]
