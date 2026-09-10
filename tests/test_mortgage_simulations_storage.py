"""Persistence tests for mortgage simulation drafts."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.storage.postgres_storage import PostgresStorage
from src.user_store import Base, User


pytestmark = pytest.mark.integration


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db_session = Session()
    db_session.add_all([User(chat_id="owner", is_active=True), User(chat_id="other", is_active=True)])
    db_session.commit()
    yield db_session
    db_session.close()
    engine.dispose()


def test_simulation_draft_is_private_and_does_not_create_a_loan(session) -> None:
    owner = PostgresStorage(session, "owner")
    other = PostgresStorage(session, "other")
    draft = owner.create_mortgage_simulation(
        name="Casa centro",
        input_snapshot={"principal": 200000, "duration_months": 300},
        result_snapshot={"status": "sostenibile"},
    )

    assert draft["name"] == "Casa centro"
    assert owner.fetch_mortgage_simulations()[0]["id"] == draft["id"]
    assert other.fetch_mortgage_simulations() == []
    assert owner.fetch_loans() == []


def test_delete_only_removes_the_owners_draft(session) -> None:
    owner = PostgresStorage(session, "owner")
    draft = owner.create_mortgage_simulation("Bozza", {"x": 1}, {"status": "da_valutare"})

    assert owner.delete_mortgage_simulation(draft["id"]) is True
    assert owner.fetch_mortgage_simulations() == []


def test_duplicate_and_update_keep_a_draft_private(session) -> None:
    owner = PostgresStorage(session, "owner")
    other = PostgresStorage(session, "other")
    draft = owner.create_mortgage_simulation("Bozza", {"principal": 100000}, {"status": "sostenibile"})

    copied = owner.duplicate_mortgage_simulation(draft["id"])
    updated = owner.update_mortgage_simulation(copied["id"], "Copia aggiornata", {"principal": 120000}, {"status": "da_valutare"})

    assert updated["name"] == "Copia aggiornata"
    assert updated["input_snapshot"]["principal"] == 120000
    assert other.get_mortgage_simulation(copied["id"]) is None


def test_convert_archives_draft_and_creates_no_historical_charges(session) -> None:
    owner = PostgresStorage(session, "owner")
    draft = owner.create_mortgage_simulation("Casa", {"principal": 100000}, {"status": "sostenibile"})
    loan = owner.convert_mortgage_simulation(draft["id"], {
        "name": "Casa", "loan_type": "mutuo_casa", "principal_amount": 100000,
        "disbursement_date": date(2026, 1, 1), "duration_months": 240,
        "rate_type": "fisso", "tan": 3.0,
    })

    archived = owner.get_mortgage_simulation(draft["id"])
    assert loan is not None
    assert archived["status"] == "archived"
    assert archived["converted_loan_id"] == loan["id"]
    assert owner.convert_mortgage_simulation(draft["id"], {}) is None
