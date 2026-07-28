"""
tests/test_postgres_storage_savings_goals.py — CRUD SavingsGoal/SavingsGoalEvaluation
su PostgresStorage, SQLite in-memory (stesso pattern di test_postgres_storage.py).
"""
import pytest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.user_store import Base, User
from src.storage.models import SavingsGoal, SavingsGoalEvaluation
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


class TestCreateAndFetchSavingsGoal:
    def test_create_returns_dict_with_expected_keys(self, storage):
        result = storage.create_savings_goal(
            goal_type="net_savings", name="Fondo emergenza", target_amount=5000.0,
        )
        assert result["id"] is not None
        assert result["name"] == "Fondo emergenza"
        assert result["status"] == "active"
        assert result["target_amount"] == pytest.approx(5000.0)

    def test_fetch_only_own_user_goals(self, db_session, storage):
        db_session.add(User(chat_id="other_user", is_active=True))
        db_session.commit()
        storage.create_savings_goal(goal_type="net_savings", name="Mio", target_amount=100.0)
        PostgresStorage(session=db_session, user_id="other_user").create_savings_goal(
            goal_type="net_savings", name="Altrui", target_amount=100.0,
        )
        goals = storage.fetch_savings_goals()
        assert [g["name"] for g in goals] == ["Mio"]

    def test_fetch_filters_by_status(self, storage):
        g1 = storage.create_savings_goal(goal_type="net_savings", name="A", target_amount=100.0)
        storage.create_savings_goal(goal_type="net_savings", name="B", target_amount=100.0)
        storage.update_savings_goal(g1["id"], status="completed")

        active = storage.fetch_savings_goals(status="active")
        completed = storage.fetch_savings_goals(status="completed")
        assert [g["name"] for g in active] == ["B"]
        assert [g["name"] for g in completed] == ["A"]


class TestUpdateSavingsGoal:
    def test_returns_none_if_not_found(self, storage):
        assert storage.update_savings_goal(9999, name="x") is None

    def test_updates_fields(self, storage):
        g = storage.create_savings_goal(goal_type="net_savings", name="Orig", target_amount=100.0)
        updated = storage.update_savings_goal(g["id"], name="Nuovo", target_amount=200.0)
        assert updated["name"] == "Nuovo"
        assert updated["target_amount"] == pytest.approx(200.0)

    def test_does_not_update_other_users_goal(self, db_session, storage):
        db_session.add(User(chat_id="other_user_2", is_active=True))
        db_session.commit()
        other_storage = PostgresStorage(session=db_session, user_id="other_user_2")
        g = other_storage.create_savings_goal(goal_type="net_savings", name="Altrui", target_amount=100.0)
        assert storage.update_savings_goal(g["id"], name="Hack") is None


class TestDeleteSavingsGoal:
    def test_delete_removes_goal_and_evaluations(self, db_session, storage):
        g = storage.create_savings_goal(goal_type="net_savings", name="Da cancellare", target_amount=100.0)
        storage.save_savings_goal_evaluation(
            g["id"], period_month=date(2026, 7, 1), progress_pct=50.0,
            score_label="In linea", eta_date=None,
        )
        ok = storage.delete_savings_goal(g["id"])
        assert ok is True
        assert storage.fetch_savings_goals() == []
        assert db_session.query(SavingsGoalEvaluation).filter_by(goal_id=g["id"]).count() == 0

    def test_delete_returns_false_if_not_found(self, storage):
        assert storage.delete_savings_goal(9999) is False


class TestSavingsGoalEvaluations:
    def test_save_and_fetch_evaluation(self, storage):
        g = storage.create_savings_goal(goal_type="net_savings", name="G", target_amount=100.0)
        storage.save_savings_goal_evaluation(
            g["id"], period_month=date(2026, 6, 1), progress_pct=40.0,
            score_label="In ritardo", eta_date=date(2027, 1, 1),
        )
        storage.save_savings_goal_evaluation(
            g["id"], period_month=date(2026, 7, 1), progress_pct=55.0,
            score_label="In linea", eta_date=date(2026, 12, 1),
        )
        history = storage.fetch_savings_goal_evaluations(g["id"])
        assert len(history) == 2
        assert history[0]["period_month"] == "2026-07-01"  # piu' recente prima

    def test_upsert_same_period_updates_in_place(self, storage):
        g = storage.create_savings_goal(goal_type="net_savings", name="G", target_amount=100.0)
        storage.save_savings_goal_evaluation(
            g["id"], period_month=date(2026, 7, 1), progress_pct=10.0,
            score_label="A rischio", eta_date=None,
        )
        storage.save_savings_goal_evaluation(
            g["id"], period_month=date(2026, 7, 1), progress_pct=90.0,
            score_label="In anticipo", eta_date=None,
        )
        history = storage.fetch_savings_goal_evaluations(g["id"])
        assert len(history) == 1
        assert history[0]["progress_pct"] == pytest.approx(90.0)
