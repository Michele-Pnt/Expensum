"""Append-only consent service contracts."""

import pytest

from src.consent_service import ConsentService, InvalidConsentCombination
from src.user_store import ConsentEvent


pytestmark = pytest.mark.integration


def _user(store, chat_id="consent-user"):
    """Create a tenant for consent tests."""
    store.add_user(chat_id=chat_id, storage_backend="postgres")
    return chat_id


def test_latest_consent_event_is_current_state(mock_db_session):
    """Consent history remains append-only while current state is derived."""
    user_id = _user(mock_db_session)
    service = ConsentService(mock_db_session)

    service.record(user_id, "marketing_email", True, "2026-10-01", "onboarding")
    service.record(user_id, "marketing_email", False, "2026-10-01", "settings")

    assert service.current(user_id)["marketing_email"] is False
    assert len(service.history(user_id, "marketing_email")) == 2


def test_algorithm_parent_off_disables_source_consents(mock_db_session):
    """Source-specific AI purposes cannot be enabled without their parent."""
    user_id = _user(mock_db_session)
    service = ConsentService(mock_db_session)

    with pytest.raises(InvalidConsentCombination):
        service.record_batch(
            user_id,
            {"algorithm_improvement": False, "structured_voice_usage": True},
            "onboarding",
        )


def test_record_batch_accept_all_expands_only_known_optional_consents(mock_db_session):
    """Bulk actions are expanded server-side from the fixed allowlist."""
    user_id = _user(mock_db_session)
    service = ConsentService(mock_db_session)

    service.record_batch(user_id, {"accept_all": True}, "onboarding")

    assert set(service.current(user_id)) == set(service.OPTIONAL_CONSENTS)
    assert all(service.current(user_id).values())


def test_unknown_consent_is_rejected(mock_db_session):
    """Clients cannot invent consent purposes."""
    user_id = _user(mock_db_session)

    with pytest.raises(ValueError):
        ConsentService(mock_db_session).record(
            user_id, "unknown", True, "2026-10-01", "settings"
        )


def test_marketing_consent_creates_outbox_task(mock_db_session):
    """Marketing changes create a durable desired-state task."""
    user_id = _user(mock_db_session)
    ConsentService(mock_db_session).record(
        user_id, "marketing_email", True, "2026-10-01", "settings"
    )

    with mock_db_session.Session() as session:
        assert session.query(ConsentEvent).filter_by(user_id=user_id).count() == 1
