"""Web registration and email-verification route contracts."""

from unittest.mock import patch

import pytest

from config import Config
from src.registration_service import RegistrationService


pytestmark = pytest.mark.integration


def _registration_form(email: str = "new@example.test") -> dict[str, str]:
    """Return the minimal valid registration payload."""
    return {
        "first_name": "Mario",
        "last_name": "Rossi",
        "email": email,
        "password": "ValidPass123!",
        "password_confirm": "ValidPass123!",
        "privacy_accepted": "on",
        "tos_accepted": "on",
        "age_attested": "on",
    }


def test_register_creates_pending_account_and_sends_verification(client, monkeypatch):
    """Registration reserves a slot but does not log in or grant Pro."""
    from src.dashboard.app import store

    monkeypatch.setattr(Config, "PUBLIC_REGISTRATION_ENABLED", True)
    with patch(
        "src.dashboard.blueprints.auth_routes.brevo_client.send_verification_email"
    ) as send_email:
        response = client.post("/register", data=_registration_form("new@example.test"))

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/check-email")
    user = store.get_user_by_email_any_status("new@example.test")
    assert user.registration_status == "pending_verification"
    assert store.get_user_plan(user.chat_id)["plan_type"] == "free"
    with client.session_transaction() as session:
        assert session.get("chat_id") is None
    send_email.assert_called_once()
    assert send_email.call_args.args[0] == "new@example.test"
    assert "ValidPass123!" not in str(send_email.call_args)


def test_login_rejects_unverified_account_without_enumeration(client, monkeypatch):
    """A pending account receives a generic email-verification message."""
    from src.dashboard.app import store

    monkeypatch.setattr(Config, "PUBLIC_REGISTRATION_ENABLED", True)
    RegistrationService(store).reserve(
        "pending@example.test",
        "Mario",
        "Rossi",
        "ValidPass123!",
        {
            "privacy_policy_version": Config.CURRENT_PRIVACY_POLICY_VERSION,
            "tos_version": Config.CURRENT_TOS_VERSION,
            "age_attestation": True,
        },
    )

    response = client.post(
        "/login",
        data={"email": "pending@example.test", "password": "ValidPass123!"},
    )

    assert response.status_code == 200
    assert "Controlla la tua email" in response.get_data(as_text=True)
    with client.session_transaction() as session:
        assert session.get("chat_id") is None


def test_verify_email_activates_user_and_redirects_to_onboarding(client, monkeypatch):
    """The one-time link activates the account and establishes the web session."""
    from src.dashboard.app import store

    monkeypatch.setattr(Config, "PUBLIC_REGISTRATION_ENABLED", True)
    with patch(
        "src.dashboard.blueprints.auth_routes.brevo_client.send_verification_email"
    ) as send_email:
        client.post("/register", data=_registration_form("verify@example.test"))
        raw_token = send_email.call_args.args[1]

    response = client.get(f"/verify-email?token={raw_token}")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/onboarding")
    user = store.get_user_by_email_any_status("verify@example.test")
    assert user.registration_status == "active"
    assert user.email_verified_at is not None
    with client.session_transaction() as session:
        assert session["chat_id"] == user.chat_id
