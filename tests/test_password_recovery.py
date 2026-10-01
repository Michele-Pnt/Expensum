"""Password recovery route contracts."""

from datetime import timedelta
from unittest.mock import patch

import pytest

from src.auth_tokens import issue_auth_token


pytestmark = pytest.mark.integration


def _seed_user(store, email: str = "known@example.test"):
    """Create an active web user with credentials for recovery tests."""
    chat_id = "recovery-" + email.split("@", 1)[0]
    store.add_user(chat_id=chat_id, storage_backend="postgres")
    store.set_credentials(chat_id, email, "OldValidPass123!")
    return store.get_user_by_email_any_status(email)


def test_forgot_password_response_is_identical_for_known_and_unknown_email(
    client, monkeypatch
):
    """The recovery endpoint does not disclose whether an email is registered."""
    from src.dashboard.app import store

    _seed_user(store)
    monkeypatch.setattr(
        "src.dashboard.blueprints.auth_routes.brevo_client.send_password_reset_email",
        lambda *_args: None,
    )

    known = client.post("/forgot-password", data={"email": "known@example.test"})
    unknown = client.post("/forgot-password", data={"email": "unknown@example.test"})

    assert known.status_code == unknown.status_code == 200
    assert known.get_data(as_text=True) == unknown.get_data(as_text=True)


def test_reset_changes_password_and_invalidates_existing_sessions(client, monkeypatch):
    """A valid reset changes credentials, consumes the token and revokes sessions."""
    from src.dashboard.app import store

    user = _seed_user(store, "reset@example.test")
    old_version = store.get_token_version(user.chat_id)
    token = issue_auth_token(
        store, user.chat_id, "password_reset", timedelta(minutes=30)
    )
    monkeypatch.setattr(
        "src.dashboard.blueprints.auth_routes.brevo_client.send_password_reset_email",
        lambda *_args: None,
    )

    response = client.post(
        f"/reset-password?token={token}",
        data={
            "password": "NewValidPass123!",
            "password_confirm": "NewValidPass123!",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")
    assert store.verify_password("reset@example.test", "NewValidPass123!")
    assert store.get_token_version(user.chat_id) == old_version + 1


def test_forgot_password_sends_a_one_time_link_without_password(client, monkeypatch):
    """The email contains a reset token but never a password."""
    from src.dashboard.app import store

    _seed_user(store, "mail@example.test")
    with patch(
        "src.dashboard.blueprints.auth_routes.brevo_client.send_password_reset_email"
    ) as send_email:
        response = client.post(
            "/forgot-password", data={"email": "mail@example.test"}
        )

    assert response.status_code == 200
    send_email.assert_called_once()
    assert send_email.call_args.args[0] == "mail@example.test"
    assert "OldValidPass123!" not in str(send_email.call_args)
