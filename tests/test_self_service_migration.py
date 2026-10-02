"""Schema and data-backfill contracts for self-service registration."""

from datetime import date, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.storage.models import Account, Income, RecurringIncomeRule
from src.user_store import Base, User


pytestmark = pytest.mark.integration


def _alembic_config(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Config:
    """Return an Alembic config bound to a temporary migration database."""
    monkeypatch.setenv("MIGRATION_DATABASE_URL", database_url)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    return Config(str(Path(__file__).parents[1] / "alembic.ini"))


@pytest.fixture
def db_session():
    """Create a current-model SQLite database for constraint tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(User(chat_id="u1", email="u1@example.test", is_active=True))
    session.commit()
    yield session
    session.close()
    engine.dispose()


def test_existing_users_are_backfilled_active_and_verified(tmp_path, monkeypatch):
    """The migration preserves existing accounts and marks them verified."""
    database = tmp_path / "registration-migration.db"
    url = f"sqlite:///{database}"
    config = _alembic_config(url, monkeypatch)

    with create_engine(url).begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE users ("
                "chat_id VARCHAR PRIMARY KEY, email VARCHAR, created_at DATETIME, "
                "is_active BOOLEAN, notion_api_key VARCHAR)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE tally_leads ("
                "id INTEGER PRIMARY KEY, tally_submission_id VARCHAR, email VARCHAR, referral_code VARCHAR, "
                "referred_by_code VARCHAR)"
            )
        )
        connection.execute(
            text("CREATE TABLE accounts (id INTEGER PRIMARY KEY, user_id VARCHAR NOT NULL)")
        )
        connection.execute(
            text(
                "CREATE TABLE user_income_categories ("
                "id INTEGER PRIMARY KEY, user_id VARCHAR NOT NULL)"
            )
        )
        connection.execute(
            text("CREATE TABLE incomes (id INTEGER PRIMARY KEY, user_id VARCHAR NOT NULL)")
        )
    command.stamp(config, "t2u3v4w5x6y7")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (chat_id, email, created_at, is_active) "
                "VALUES (:chat_id, :email, :created_at, 1)"
            ),
            {
                "chat_id": "web_legacy",
                "email": "legacy@example.test",
                "created_at": datetime(2026, 9, 1, 12, 0),
            },
        )
        connection.execute(
            text(
                "INSERT INTO tally_leads "
                "(tally_submission_id, email, referral_code, referred_by_code) "
                "VALUES ('owner-old-submission', 'owner@example.test', 'OLDOWNER42', NULL), "
                "('owner-submission', 'owner@example.test', 'OWNER42', NULL), "
                "('friend-submission', 'friend@example.test', NULL, 'OWNER42')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO users (chat_id, email, created_at, is_active) "
                "VALUES ('owner', 'owner@example.test', :created_at, 1), "
                "('friend', 'friend@example.test', :created_at, 1)"
            ),
            {"created_at": datetime(2026, 9, 2, 12, 0)},
        )
    engine.dispose()

    command.upgrade(config, "u3v4w5x6y7z8")
    with create_engine(url).connect() as connection:
        legacy = connection.execute(
            text(
                "SELECT registration_status, registration_source, email_verified_at "
                "FROM users WHERE chat_id = 'web_legacy'"
            )
        ).one()
        friend, owner = connection.execute(
            text(
                "SELECT referral_code, referred_by_code FROM users "
                "WHERE chat_id IN ('owner', 'friend') ORDER BY chat_id"
            )
        ).all()

    assert legacy.registration_status == "active"
    assert legacy.registration_source == "legacy_beta"
    assert str(legacy.email_verified_at) == "2026-09-01 12:00:00"
    assert owner == ("OWNER42", None)
    assert friend == (None, "OWNER42")


def test_recurring_income_occurrence_is_unique(db_session):
    """A retry cannot create two incomes for one rule and scheduled date."""
    account = Account(user_id="u1", name="Conto principale")
    db_session.add(account)
    db_session.flush()
    rule = RecurringIncomeRule(
        user_id="u1",
        name="Stipendio",
        amount=1800,
        cadence="monthly",
        payday_day=27,
        next_due_date=date(2026, 10, 27),
        account_id=account.id,
    )
    db_session.add(rule)
    db_session.flush()
    first = Income(
        user_id="u1",
        income_date=date(2026, 10, 27),
        amount=1800,
        name="Stipendio",
        account_id=account.id,
        source_rule_id=rule.id,
        scheduled_for=date(2026, 10, 27),
    )
    duplicate = Income(
        user_id="u1",
        income_date=date(2026, 10, 27),
        amount=1800,
        name="Stipendio",
        account_id=account.id,
        source_rule_id=rule.id,
        scheduled_for=date(2026, 10, 27),
    )
    db_session.add(first)
    db_session.commit()
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_new_schema_contains_tenant_quality_and_auth_tables(db_session):
    """All new tables are registered in the shared SQLAlchemy metadata."""
    table_names = set(inspect(db_session.bind).get_table_names())
    assert {
        "registration_capacity",
        "auth_tokens",
        "user_profiles",
        "user_profile_goals",
        "consent_events",
        "marketing_sync_tasks",
        "recurring_income_rules",
        "ai_improvement_samples",
    }.issubset(table_names)
