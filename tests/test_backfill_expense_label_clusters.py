"""
tests/test_backfill_expense_label_clusters.py — Test per
scripts/backfill_expense_label_clusters.py::backfill_user.

Usa SQLite in-memory tramite UserStore (come i test di dashboard/admin_metrics):
`UserStore.Session` è il sessionmaker condiviso che lo script usa in produzione.
"""

from datetime import date

import pytest
from sqlalchemy.orm import sessionmaker

from scripts.backfill_expense_label_clusters import backfill_user
from src.storage.models import Expense, ExpenseLabelCluster
from src.user_store import Base, User, UserStore

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def store():
    """UserStore con engine SQLite in-memory condiviso per tutto il modulo."""
    s = UserStore(db_url="sqlite:///:memory:")
    yield s
    s.engine.dispose()


@pytest.fixture
def db_session(store):
    """Schema azzerato a ogni test; usa lo stesso Session del backfill script."""
    Base.metadata.drop_all(store.engine)
    Base.metadata.create_all(store.engine)
    Session = sessionmaker(bind=store.engine)
    session = Session()
    yield session
    session.close()


def _add_expense(session, chat_id, name, expense_date, category_id=None):
    exp = Expense(
        user_id=chat_id,
        expense_date=expense_date,
        amount=10.0,
        name=name,
        category_id=category_id,
    )
    session.add(exp)
    session.commit()
    return exp


class TestBackfillUser:
    def test_skips_user_not_found(self, store, db_session):
        summary = backfill_user(store, "ghost_user")
        assert summary["skipped"]

    def test_skips_inactive_user(self, store, db_session):
        db_session.add(User(chat_id="inactive_user", is_active=False, storage_backend="postgres"))
        db_session.commit()

        summary = backfill_user(store, "inactive_user")
        assert "inattivo" in summary["skipped"] or "trovato" in summary["skipped"]

    def test_skips_non_postgres_backend(self, store, db_session):
        db_session.add(User(chat_id="notion_user", is_active=True, storage_backend="notion"))
        db_session.commit()

        summary = backfill_user(store, "notion_user")
        assert summary["skipped"] == "backend non-Postgres, feature non applicabile"

    def test_assigns_cluster_to_pending_expenses(self, store, db_session):
        db_session.add(User(chat_id="pg_user", is_active=True, storage_backend="postgres"))
        db_session.commit()
        _add_expense(db_session, "pg_user", "Coca Cola", date(2026, 1, 1))
        _add_expense(db_session, "pg_user", "Coca-Cola", date(2026, 1, 2))
        _add_expense(db_session, "pg_user", "Bicicletta", date(2026, 1, 3))

        summary = backfill_user(store, "pg_user")

        assert summary["expenses_scanned"] == 3
        # "Coca Cola" apre un cluster, "Coca-Cola" si unisce, "Bicicletta" ne apre un altro
        assert summary["clusters_created"] == 2

        expenses = db_session.query(Expense).filter_by(user_id="pg_user").all()
        assert all(e.label_cluster_id is not None for e in expenses)

    def test_second_run_is_idempotent(self, store, db_session):
        """Una seconda esecuzione non deve toccare spese già etichettate né creare
        nuovi cluster: `label_cluster_id IS NULL` è vuoto dopo la prima passata."""
        db_session.add(User(chat_id="pg_user2", is_active=True, storage_backend="postgres"))
        db_session.commit()
        _add_expense(db_session, "pg_user2", "Pizza Margherita", date(2026, 1, 1))
        _add_expense(db_session, "pg_user2", "Taxi aeroporto", date(2026, 1, 2))

        first_summary = backfill_user(store, "pg_user2")
        assert first_summary["expenses_scanned"] == 2
        assert first_summary["clusters_created"] == 2

        clusters_after_first = db_session.query(ExpenseLabelCluster).count()
        label_ids_after_first = {
            e.id: e.label_cluster_id
            for e in db_session.query(Expense).filter_by(user_id="pg_user2").all()
        }

        second_summary = backfill_user(store, "pg_user2")
        assert second_summary["expenses_scanned"] == 0
        assert second_summary["clusters_created"] == 0

        clusters_after_second = db_session.query(ExpenseLabelCluster).count()
        label_ids_after_second = {
            e.id: e.label_cluster_id
            for e in db_session.query(Expense).filter_by(user_id="pg_user2").all()
        }
        assert clusters_after_second == clusters_after_first
        assert label_ids_after_second == label_ids_after_first

    def test_dry_run_does_not_write(self, store, db_session):
        db_session.add(User(chat_id="pg_user3", is_active=True, storage_backend="postgres"))
        db_session.commit()
        _add_expense(db_session, "pg_user3", "Cinema", date(2026, 1, 1))

        summary = backfill_user(store, "pg_user3", dry_run=True)
        assert summary["expenses_scanned"] == 1
        assert summary["clusters_created"] == 0

        expense = db_session.query(Expense).filter_by(user_id="pg_user3").first()
        assert expense.label_cluster_id is None
        assert db_session.query(ExpenseLabelCluster).count() == 0

    def test_respects_category_guardrail_across_expenses(self, store, db_session):
        """Stesso testo, categorie diverse -> due cluster anche nel backfill."""
        db_session.add(User(chat_id="pg_user4", is_active=True, storage_backend="postgres"))
        db_session.commit()
        _add_expense(db_session, "pg_user4", "Coca Cola", date(2026, 1, 1), category_id=1)
        _add_expense(db_session, "pg_user4", "Coca Cola", date(2026, 1, 2), category_id=2)

        summary = backfill_user(store, "pg_user4")
        assert summary["clusters_created"] == 2
