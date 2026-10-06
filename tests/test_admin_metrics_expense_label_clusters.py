"""
tests/test_admin_metrics_expense_label_clusters.py — Test per
src/dashboard/admin_metrics.py::get_expense_label_cluster_stats.

Tier `integration`: usa la fixture condivisa `mock_db_session` (SQLite in-memory)
definita in tests/conftest.py, come tests/test_admin_metrics.py.
"""
from datetime import datetime, timedelta, timezone

import pytest

from src.dashboard import admin_metrics as m
from src.storage.models import Expense, ExpenseLabelCluster
from src.user_store import User

pytestmark = pytest.mark.integration

NOW = datetime.now(timezone.utc).replace(tzinfo=None)


def _seed(store):
    """Scenario noto:
    - cluster A ("coca cola"): 3 spese -> multi-cluster, dentro la finestra 30gg
    - cluster B ("pizza"): 1 spesa -> singleton, dentro la finestra
    - cluster C ("taxi"): 2 spese -> multi-cluster, creato FUORI dalla finestra (60gg fa)
      con un'ulteriore spesa unita dentro la finestra (merge, non nuovo cluster)
    - 1 spesa senza cluster (label_cluster_id NULL, simula pre-backfill)
    """
    with store.Session() as s:
        s.add(User(chat_id="u1", is_active=True, storage_backend="postgres"))
        s.commit()

        cluster_a = ExpenseLabelCluster(
            user_id="u1", category_id=1, anchor_text="coca cola",
            variant_counts={"coca cola": 3}, created_at=NOW - timedelta(days=5),
        )
        cluster_b = ExpenseLabelCluster(
            user_id="u1", category_id=1, anchor_text="pizza",
            variant_counts={"pizza": 1}, created_at=NOW - timedelta(days=2),
        )
        cluster_c = ExpenseLabelCluster(
            user_id="u1", category_id=2, anchor_text="taxi",
            variant_counts={"taxi": 2}, created_at=NOW - timedelta(days=60),
        )
        s.add_all([cluster_a, cluster_b, cluster_c])
        s.commit()

        # Cluster A: 3 spese, tutte create dentro la finestra (nuovo cluster + 2 merge)
        s.add(Expense(user_id="u1", expense_date=NOW.date(), amount=5, name="coca cola",
                      category_id=1, label_cluster_id=cluster_a.id,
                      created_at=NOW - timedelta(days=5)))
        s.add(Expense(user_id="u1", expense_date=NOW.date(), amount=5, name="coca-cola",
                      category_id=1, label_cluster_id=cluster_a.id,
                      created_at=NOW - timedelta(days=3)))
        s.add(Expense(user_id="u1", expense_date=NOW.date(), amount=5, name="Coca Cola",
                      category_id=1, label_cluster_id=cluster_a.id,
                      created_at=NOW - timedelta(days=1)))

        # Cluster B: 1 spesa (singleton), dentro la finestra
        s.add(Expense(user_id="u1", expense_date=NOW.date(), amount=8, name="pizza",
                      category_id=1, label_cluster_id=cluster_b.id,
                      created_at=NOW - timedelta(days=2)))

        # Cluster C: 1 spesa fuori dalla finestra (creazione cluster) + 1 dentro (merge)
        s.add(Expense(user_id="u1", expense_date=NOW.date(), amount=12, name="taxi",
                      category_id=2, label_cluster_id=cluster_c.id,
                      created_at=NOW - timedelta(days=60)))
        s.add(Expense(user_id="u1", expense_date=NOW.date(), amount=12, name="taxi aeroporto",
                      category_id=2, label_cluster_id=cluster_c.id,
                      created_at=NOW - timedelta(days=4)))

        # 1 spesa senza cluster (pre-backfill)
        s.add(Expense(user_id="u1", expense_date=NOW.date(), amount=3, name="varie",
                      category_id=None, label_cluster_id=None,
                      created_at=NOW - timedelta(days=1)))

        s.commit()


class TestGetExpenseLabelClusterStats:
    def test_counts_totals_and_unlabeled(self, mock_db_session):
        _seed(mock_db_session)
        with mock_db_session.Session() as s:
            stats = m.get_expense_label_cluster_stats(s, days=30)

        assert stats["total_clusters"] == 3
        assert stats["labeled_expenses"] == 6
        assert stats["unlabeled_expenses"] == 1

    def test_singleton_vs_multi_clusters(self, mock_db_session):
        _seed(mock_db_session)
        with mock_db_session.Session() as s:
            stats = m.get_expense_label_cluster_stats(s, days=30)

        # A (3) e C (2) sono multi; B (1) è singleton
        assert stats["singleton_clusters"] == 1
        assert stats["multi_clusters"] == 2

    def test_avg_cluster_size(self, mock_db_session):
        _seed(mock_db_session)
        with mock_db_session.Session() as s:
            stats = m.get_expense_label_cluster_stats(s, days=30)

        # 6 spese etichettate / 3 cluster = 2.0
        assert stats["avg_cluster_size"] == 2.0

    def test_new_clusters_and_merges_in_period(self, mock_db_session):
        _seed(mock_db_session)
        with mock_db_session.Session() as s:
            stats = m.get_expense_label_cluster_stats(s, days=30)

        # Nuovi cluster nella finestra 30gg: A (5gg fa) e B (2gg fa). C è a 60gg, fuori.
        assert stats["new_clusters_period"] == 2
        # Spese con cluster create nella finestra: A(3) + B(1) + C(1, la "taxi aeroporto"
        # a 4gg) = 5 assegnazioni totali nel periodo; merges = assegnazioni - nuovi cluster
        assert stats["merges_period"] == 5 - 2

    def test_top_clusters_sorted_by_size(self, mock_db_session):
        _seed(mock_db_session)
        with mock_db_session.Session() as s:
            stats = m.get_expense_label_cluster_stats(s, days=30)

        top = stats["top_clusters"]
        assert top[0]["anchor_text"] == "coca cola"
        assert top[0]["size"] == 3
        anchors = {t["anchor_text"] for t in top}
        assert anchors == {"coca cola", "pizza", "taxi"}

    def test_empty_dataset_returns_zeroed_stats(self, mock_db_session):
        with mock_db_session.Session() as s:
            s.add(User(chat_id="empty_user", is_active=True, storage_backend="postgres"))
            s.commit()
            stats = m.get_expense_label_cluster_stats(s, days=30)

        assert stats["total_clusters"] == 0
        assert stats["labeled_expenses"] == 0
        assert stats["unlabeled_expenses"] == 0
        assert stats["avg_cluster_size"] is None
        assert stats["top_clusters"] == []
