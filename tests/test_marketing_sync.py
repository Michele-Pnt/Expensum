"""Brevo marketing consent outbox contracts."""

from unittest.mock import patch

import pytest

from src.consent_service import ConsentService
from src.marketing_sync import process_marketing_sync_tasks
from src.user_store import MarketingSyncTask


pytestmark = pytest.mark.integration


def _user(store, email="marketing@example.test"):
    """Create a web user with a syncable email."""
    chat_id = "marketing-" + email.split("@", 1)[0]
    store.add_user(chat_id=chat_id, email=email, storage_backend="postgres")
    return chat_id


def test_queued_marketing_grant_cannot_override_a_later_withdrawal(mock_db_session):
    """A withdrawal supersedes an older queued grant before remote dispatch."""
    user_id = _user(mock_db_session)
    service = ConsentService(mock_db_session)
    service.record(user_id, "marketing_email", True, "2026-10-01", "onboarding")
    service.record(user_id, "marketing_email", False, "2026-10-01", "settings")

    with patch("src.marketing_sync.brevo_client.upsert_contact") as add_contact, patch(
        "src.marketing_sync.brevo_client.remove_contact_from_list"
    ) as remove_contact:
        summary = process_marketing_sync_tasks(mock_db_session)

    assert summary.processed == 2
    add_contact.assert_not_called()
    remove_contact.assert_called_once()


def test_marketing_grant_is_idempotent(mock_db_session):
    """A successful task is not dispatched twice."""
    user_id = _user(mock_db_session, "grant@example.test")
    ConsentService(mock_db_session).record(
        user_id, "marketing_email", True, "2026-10-01", "settings"
    )

    with patch("src.marketing_sync.brevo_client.upsert_contact") as add_contact:
        first = process_marketing_sync_tasks(mock_db_session)
        second = process_marketing_sync_tasks(mock_db_session)

    assert first.succeeded == 1
    assert second.processed == 0
    add_contact.assert_called_once()


def test_marketing_failure_is_retryable_without_provider_body(mock_db_session):
    """Provider failures are stored as a short error code and retried later."""
    user_id = _user(mock_db_session, "failure@example.test")
    ConsentService(mock_db_session).record(
        user_id, "marketing_email", True, "2026-10-01", "settings"
    )

    with patch(
        "src.marketing_sync.brevo_client.upsert_contact",
        side_effect=RuntimeError("provider response body must not persist"),
    ):
        summary = process_marketing_sync_tasks(mock_db_session)

    assert summary.failed == 1
    with mock_db_session.Session() as session:
        task = session.query(MarketingSyncTask).one()
        assert task.status == "pending"
        assert task.attempt_count == 1
        assert task.last_error_code == "RuntimeError"
