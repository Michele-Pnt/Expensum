"""One-time token lifecycle tests."""

from datetime import timedelta

import pytest

from src.auth_tokens import consume_auth_token, issue_auth_token
from src.user_store import AuthToken


pytestmark = pytest.mark.integration


def test_token_is_stored_as_digest_and_consumed_once(mock_db_session, monkeypatch):
    """A raw token is never persisted and a consumed token cannot be replayed."""
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-token-secret")
    store = mock_db_session
    store.add_user(chat_id="u1")

    raw = issue_auth_token(store, "u1", "email_verification", timedelta(hours=24))
    with store.Session() as session:
        digests = {row.token_digest for row in session.query(AuthToken).all()}

    assert raw not in digests
    assert consume_auth_token(store, raw, "email_verification") == "u1"
    assert consume_auth_token(store, raw, "email_verification") is None


def test_expired_token_cannot_be_consumed(mock_db_session, monkeypatch):
    """An expired reset token is rejected even when its digest is valid."""
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-token-secret")
    store = mock_db_session
    store.add_user(chat_id="u1")

    raw = issue_auth_token(store, "u1", "password_reset", timedelta(seconds=-1))

    assert consume_auth_token(store, raw, "password_reset") is None


def test_reissuing_token_invalidates_previous_live_token(mock_db_session, monkeypatch):
    """Only the newest token for one user and purpose remains usable."""
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-token-secret")
    store = mock_db_session
    store.add_user(chat_id="u1")

    first = issue_auth_token(store, "u1", "email_verification", timedelta(hours=24))
    second = issue_auth_token(store, "u1", "email_verification", timedelta(hours=24))

    assert consume_auth_token(store, first, "email_verification") is None
    assert consume_auth_token(store, second, "email_verification") == "u1"
