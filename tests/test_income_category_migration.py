"""Schema and backfill contracts for income categories."""

from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.storage.models import Account, Income, UserIncomeCategory
from src.user_store import Base, User


pytestmark = pytest.mark.integration


@pytest.fixture
def db_session():
    """A fresh 3NF database used to exercise the model relationship."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([User(chat_id="u1", is_active=True), User(chat_id="u2", is_active=True)])
    session.commit()
    yield session
    session.close()
    engine.dispose()


def test_income_category_is_scoped_by_user(db_session) -> None:
    """The same category name is valid for different tenants only."""
    db_session.add_all([
        UserIncomeCategory(user_id="u1", name="Stipendio"),
        UserIncomeCategory(user_id="u2", name="Stipendio"),
    ])
    db_session.commit()
    assert db_session.query(UserIncomeCategory).count() == 2

    db_session.add(UserIncomeCategory(user_id="u1", name="Stipendio"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_income_category_link_preserves_legacy_income_type_and_amount(db_session) -> None:
    """Adding a category FK changes neither amount nor legacy bridge value."""
    account = Account(user_id="u1", name="Main")
    category = UserIncomeCategory(user_id="u1", name="Stipendio")
    db_session.add_all([account, category])
    db_session.flush()
    income = Income(
        user_id="u1", income_date=date(2026, 9, 1), amount=1500,
        name="Settembre", account_id=account.id, income_type="Stipendio",
        income_category_id=category.id,
    )
    db_session.add(income)
    db_session.commit()

    assert float(income.amount) == 1500.0
    assert income.income_type == "Stipendio"
    assert income.income_category_id == category.id


def test_expansion_migration_round_trip_preserves_legacy_income_rows(tmp_path, monkeypatch) -> None:
    """Upgrade/downgrade/re-upgrade an actual predecessor-shaped SQLite database."""
    database = tmp_path / "predecessor.db"
    url = f"sqlite:///{database}"
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (chat_id VARCHAR PRIMARY KEY)"))
        connection.execute(text(
            "CREATE TABLE incomes (id INTEGER PRIMARY KEY, user_id VARCHAR NOT NULL, "
            "income_date DATE NOT NULL, amount NUMERIC NOT NULL, name VARCHAR NOT NULL, "
            "income_type VARCHAR, account_id INTEGER)"
        ))
        connection.execute(text("INSERT INTO users (chat_id) VALUES ('legacy-user')"))
        connection.execute(text(
            "INSERT INTO incomes (id, user_id, income_date, amount, name, income_type) VALUES "
            "(1, 'legacy-user', '2026-09-01', 100, 'Nullo', NULL), "
            "(2, 'legacy-user', '2026-09-01', 200, 'Bonus', 'bonus'), "
            "(3, 'legacy-user', '2026-09-01', 300, 'Custom', 'Consulenza')"
        ))
    engine.dispose()

    monkeypatch.setenv("MIGRATION_DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.stamp(config, "baad13e21af4")
    command.upgrade(config, "c1a2b3c4d5e6")
    with create_engine(url).connect() as connection:
        rows = connection.execute(text(
            "SELECT income_type, income_category_id, amount FROM incomes ORDER BY id"
        )).all()
        names = connection.execute(text(
            "SELECT name FROM user_income_categories WHERE user_id = 'legacy-user' ORDER BY name"
        )).scalars().all()
    assert [row[0] for row in rows] == [None, "bonus", "Consulenza"]
    assert all(row[1] is not None for row in rows)
    assert sum(float(row[2]) for row in rows) == 600.0
    assert {"Altra entrata", "Bonus lavorativo", "Consulenza"}.issubset(names)

    command.downgrade(config, "baad13e21af4")
    command.upgrade(config, "c1a2b3c4d5e6")
    with create_engine(url).connect() as connection:
        count, amount = connection.execute(text(
            "SELECT count(*), sum(amount) FROM incomes"
        )).one()
        category_count = connection.execute(text(
            "SELECT count(*) FROM user_income_categories WHERE user_id = 'legacy-user'"
        )).scalar_one()
    assert (count, float(amount)) == (3, 600.0)
    assert category_count == len(set(names))


def test_hardening_migration_declares_parent_based_rls_checks() -> None:
    """SQLite cannot exercise RLS; assert the PostgreSQL DDL contract explicitly."""
    source = (Path(__file__).parents[1] / "alembic/versions/"
              "c1a2b3c4d5e6_harden_income_category_isolation.py").read_text()
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "ON user_income_category_notion_links" in source
    assert "EXISTS (SELECT 1 FROM user_income_categories c" in source
    assert "DROP POLICY IF EXISTS tenant_isolation ON incomes" in source
    assert "income_category_id IS NULL OR EXISTS" in source


def _hardening_database(tmp_path, monkeypatch, links: list[tuple[int, str | None, str | None, float | None]]):
    """Build c0 data with two casefold duplicates before executing c1."""
    database = tmp_path / "hardening.db"
    url = f"sqlite:///{database}"
    with create_engine(url).begin() as connection:
        connection.execute(text("CREATE TABLE users (chat_id VARCHAR PRIMARY KEY)"))
        connection.execute(text(
            "CREATE TABLE incomes (id INTEGER PRIMARY KEY, user_id VARCHAR NOT NULL, "
            "income_date DATE NOT NULL, amount NUMERIC NOT NULL, name VARCHAR NOT NULL, "
            "income_type VARCHAR, account_id INTEGER)"
        ))
        connection.execute(text("INSERT INTO users (chat_id) VALUES ('dedup-user')"))
    monkeypatch.setenv("MIGRATION_DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.stamp(config, "baad13e21af4")
    command.upgrade(config, "c0a1b2c3d4e5")
    with create_engine(url).begin() as connection:
        connection.execute(text(
            "INSERT INTO user_income_categories (id, user_id, name) VALUES "
            "(100, 'dedup-user', 'Consulenza'), (101, 'dedup-user', 'consulenza')"
        ))
        connection.execute(text(
            "INSERT INTO incomes (id, user_id, income_date, amount, name, income_type, income_category_id) "
            "VALUES (10, 'dedup-user', '2026-09-01', 50, 'Cliente', 'consulenza', 101)"
        ))
        for category_id, notion_page_id, synced_at, average in links:
            connection.execute(text(
                "INSERT INTO user_income_category_notion_links "
                "(category_id, notion_page_id, synced_at, average) VALUES (:id, :page, :synced, :average)"
            ), {"id": category_id, "page": notion_page_id, "synced": synced_at, "average": average})
    return config, url


def test_hardening_migration_transfers_duplicate_link_and_keeps_income_fk(tmp_path, monkeypatch) -> None:
    """The duplicate's sole Notion cache link moves to the canonical category."""
    config, url = _hardening_database(
        tmp_path, monkeypatch, [(101, "duplicate-page", "2026-09-01 12:00:00", 12.5)],
    )

    command.upgrade(config, "c1a2b3c4d5e6")
    with create_engine(url).connect() as connection:
        link = connection.execute(text(
            "SELECT category_id, notion_page_id, synced_at, average "
            "FROM user_income_category_notion_links"
        )).one()
        income_category_id = connection.execute(text(
            "SELECT income_category_id FROM incomes WHERE id = 10"
        )).scalar_one()
    assert link[0] == 100
    assert link[1] == "duplicate-page"
    assert link[2] is not None
    assert float(link[3]) == 12.5
    assert income_category_id == 100

    command.downgrade(config, "c0a1b2c3d4e5")
    command.upgrade(config, "c1a2b3c4d5e6")
    with create_engine(url).connect() as connection:
        assert connection.execute(text(
            "SELECT notion_page_id FROM user_income_category_notion_links WHERE category_id = 100"
        )).scalar_one() == "duplicate-page"


def test_hardening_migration_merges_compatible_link_metadata(tmp_path, monkeypatch) -> None:
    """Nullable metadata from a duplicate fills missing values on the canonical link."""
    config, url = _hardening_database(tmp_path, monkeypatch, [
        (100, None, "2026-09-01 10:00:00", None),
        (101, "duplicate-page", "2026-09-02 10:00:00", 22.5),
    ])

    command.upgrade(config, "c1a2b3c4d5e6")
    with create_engine(url).connect() as connection:
        page, synced_at, average = connection.execute(text(
            "SELECT notion_page_id, synced_at, average FROM user_income_category_notion_links "
            "WHERE category_id = 100"
        )).one()
    assert page == "duplicate-page"
    assert synced_at is not None
    assert float(average) == 22.5


def test_hardening_migration_keeps_canonical_link_metadata(tmp_path, monkeypatch) -> None:
    """An already-canonical cache row remains unchanged when its duplicate has none."""
    config, url = _hardening_database(
        tmp_path, monkeypatch, [(100, "keep-page", "2026-09-01 10:00:00", 19.5)],
    )

    command.upgrade(config, "c1a2b3c4d5e6")
    with create_engine(url).connect() as connection:
        link = connection.execute(text(
            "SELECT category_id, notion_page_id, synced_at, average "
            "FROM user_income_category_notion_links"
        )).one()
    assert link[0] == 100
    assert link[1] == "keep-page"
    assert link[2] is not None
    assert float(link[3]) == 19.5


def test_hardening_migration_refuses_two_distinct_notion_pages_without_data_loss(tmp_path, monkeypatch) -> None:
    """A real cache conflict stops before deleting either category or link."""
    config, url = _hardening_database(tmp_path, monkeypatch, [
        (100, "keep-page", None, None),
        (101, "duplicate-page", None, None),
    ])

    with pytest.raises(RuntimeError, match="Notion link conflict"):
        command.upgrade(config, "c1a2b3c4d5e6")
    with create_engine(url).connect() as connection:
        assert connection.execute(text(
            "SELECT count(*) FROM user_income_categories WHERE id IN (100, 101)"
        )).scalar_one() == 2
        assert connection.execute(text(
            "SELECT count(*) FROM user_income_category_notion_links WHERE category_id IN (100, 101)"
        )).scalar_one() == 2
        assert connection.execute(text(
            "SELECT income_category_id FROM incomes WHERE id = 10"
        )).scalar_one() == 101
