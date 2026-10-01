"""End-to-end contract for the self-service account lifecycle."""

from unittest.mock import patch

import pytest

from config import Config


pytestmark = pytest.mark.e2e


def test_registration_onboarding_income_and_password_recovery(client, monkeypatch):
    """A user can complete the web lifecycle without emailed credentials."""
    from src.dashboard.app import store

    email = "lifecycle@example.test"
    monkeypatch.setattr(Config, "PUBLIC_REGISTRATION_ENABLED", True)
    registration = {
        "first_name": "Mario",
        "last_name": "Rossi",
        "email": email,
        "password": "ValidPass123!",
        "password_confirm": "ValidPass123!",
        "privacy_accepted": "on",
        "tos_accepted": "on",
        "age_attested": "on",
    }

    with patch(
        "src.dashboard.blueprints.auth_routes.brevo_client.send_verification_email"
    ) as send_verification:
        response = client.post("/register", data=registration)
        assert response.status_code == 302
        verification_token = send_verification.call_args.args[1]
        assert "ValidPass123!" not in str(send_verification.call_args)

    response = client.get(f"/verify-email?token={verification_token}")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/onboarding")

    response = client.post(
        "/api/onboarding/profile",
        json={
            "goals": [{"code": "budget"}],
            "profile": {"has_job": True},
        },
    )
    assert response.status_code == 200

    response = client.post(
        "/api/onboarding/income",
        json={
            "amount": 2200,
            "payday_day": 27,
            "account_name": "Conto principale",
        },
    )
    assert response.status_code == 200

    user = store.get_user_by_email_any_status(email)
    assert user.registration_status == "active"
    assert store.get_profile_goals(user.chat_id) == ["budget"]

    with patch(
        "src.dashboard.blueprints.auth_routes.brevo_client.send_password_reset_email"
    ) as send_reset:
        response = client.post("/forgot-password", data={"email": email})
        assert response.status_code == 200
        reset_token = send_reset.call_args.args[1]

    response = client.post(
        f"/reset-password?token={reset_token}",
        data={
            "password": "NewValidPass123!",
            "password_confirm": "NewValidPass123!",
        },
    )
    assert response.status_code == 302
    assert store.verify_password(email, "NewValidPass123!")
