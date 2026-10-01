"""Atomic beta-capacity and activation tests."""

from datetime import timedelta

import pytest

from src.registration_service import RegistrationCapacityReached, RegistrationService
from src.user_store import PlanChange, RegistrationCapacity, User


pytestmark = pytest.mark.integration

CONSENTS = {
    "privacy_policy_version": "2026-10-01",
    "tos_version": "2026-10-01",
    "age_attestation": True,
}


def _service(store) -> RegistrationService:
    return RegistrationService(store)


def _seed_active_users(store, count: int) -> None:
    """Fill the active-account part of the beta capacity."""
    for index in range(count):
        store.add_user(
            chat_id=f"existing_{index}",
            email=f"existing_{index}@example.test",
            registration_status="active",
            registration_source="telegram",
        )


def test_existing_users_and_pending_reservations_fill_capacity(mock_db_session):
    """A pending reservation occupies the final beta slot."""
    store = mock_db_session
    service = _service(store)
    _seed_active_users(store, 49)

    service.reserve("first@example.test", "A", "B", "ValidPass123!", CONSENTS)

    with pytest.raises(RegistrationCapacityReached):
        service.reserve("second@example.test", "C", "D", "ValidPass123!", CONSENTS)


def test_expired_pending_registration_releases_capacity(mock_db_session):
    """An expired pending user no longer occupies a beta slot."""
    store = mock_db_session
    service = _service(store)
    _seed_active_users(store, 49)
    first = service.reserve("old@example.test", "A", "B", "ValidPass123!", CONSENTS)

    with store.Session() as session:
        pending = session.get(User, first.user.chat_id)
        pending.beta_slot_reserved_until = pending.beta_slot_reserved_until - timedelta(hours=25)
        session.commit()

    second = service.reserve("new@example.test", "C", "D", "ValidPass123!", CONSENTS)

    assert second.user.email == "new@example.test"


def test_expired_pending_user_can_register_again_with_same_email(mock_db_session):
    """A stale pending record is removed before checking email uniqueness."""
    store = mock_db_session
    service = _service(store)
    first = service.reserve("same@example.test", "A", "B", "ValidPass123!", CONSENTS)

    with store.Session() as session:
        pending = session.get(User, first.user.chat_id)
        pending.beta_slot_reserved_until = pending.beta_slot_reserved_until - timedelta(hours=25)
        session.commit()

    second = service.reserve("same@example.test", "A", "B", "NewValidPass123!", CONSENTS)

    assert second.user.chat_id != first.user.chat_id
    assert second.raw_token != first.raw_token


def test_activation_verifies_user_and_grants_beta_pro(mock_db_session, monkeypatch):
    """Activation is the only point where a pending account consumes a slot."""
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-token-secret")
    store = mock_db_session
    service = _service(store)
    pending = service.reserve("activate@example.test", "A", "B", "ValidPass123!", CONSENTS)

    activated = service.activate(pending.raw_token)

    assert activated is not None
    assert activated.registration_status == "active"
    assert activated.email_verified_at is not None
    assert store.get_user_plan(activated.chat_id)["plan_type"] == "pro"
    with store.Session() as session:
        plan_change = session.query(PlanChange).filter_by(chat_id=activated.chat_id).one()
    assert plan_change.reason == "beta_default"
    assert service.activate(pending.raw_token) is None


def test_capacity_row_is_created_with_fixed_limit(mock_db_session):
    """The service bootstraps the fixed 50-account capacity row."""
    service = _service(mock_db_session)

    service.reserve("capacity@example.test", "A", "B", "ValidPass123!", CONSENTS)

    with mock_db_session.Session() as session:
        capacity = session.get(RegistrationCapacity, 1)
    assert capacity.max_accounts == 50
