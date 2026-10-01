"""Regression tests for the retired Tally account-provisioning channel."""

import base64
import hashlib
import hmac
import json

import pytest


pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def tally_signing_secret(monkeypatch):
    """Use a deterministic signing secret without reading production config."""
    from config import Config

    monkeypatch.setattr(Config, "TALLY_WEBHOOK_SIGNING_SECRET", "test-signing-secret")


def _signed_tally_post(client, payload, secret="test-signing-secret"):
    """Send the exact HMAC body that Tally would sign."""
    body = json.dumps(payload).encode()
    signature = base64.b64encode(
        hmac.new(secret.encode(), body, hashlib.sha256).digest()
    ).decode()
    return client.post(
        "/webhooks/tally",
        data=body,
        content_type="application/json",
        headers={"Tally-Signature": signature},
    )


def _tally_payload(submission_id="sub_123", email="lead@example.com"):
    """Build a representative signed legacy payload."""
    return {
        "eventType": "FORM_RESPONSE",
        "data": {
            "submissionId": submission_id,
            "fields": [
                {"label": "Nome", "type": "INPUT_TEXT", "value": "Mario"},
                {"label": "Email", "type": "INPUT_EMAIL", "value": email},
            ],
        },
    }


def test_signed_tally_request_is_retired_without_storing_lead(client):
    """A valid legacy request cannot create a lead or account anymore."""
    from src.dashboard.app import store
    from src.user_store import TallyLead

    response = _signed_tally_post(
        client, _tally_payload(submission_id="retired_1", email="legacy@example.com")
    )

    assert response.status_code == 410
    with store.Session() as session:
        assert (
            session.query(TallyLead)
            .filter_by(tally_submission_id="retired_1")
            .count()
            == 0
        )
    user = store.get_user_by_email_any_status("legacy@example.com")
    assert user is None


def test_repeated_signed_tally_request_stays_retired(client):
    """Tally retries receive the same retirement response and no side effect."""
    payload = _tally_payload(submission_id="retired_2")

    first = _signed_tally_post(client, payload)
    second = _signed_tally_post(client, payload)

    assert first.status_code == second.status_code == 410


def test_webhook_tally_rejects_invalid_signature(client):
    """An unsigned request cannot reach the retirement response."""
    response = client.post(
        "/webhooks/tally",
        data=json.dumps(_tally_payload(submission_id="forged")),
        content_type="application/json",
        headers={"Tally-Signature": "not-a-valid-signature"},
    )

    assert response.status_code == 401


def test_webhook_tally_is_unavailable_without_signing_secret(client, monkeypatch):
    """A deploy without the legacy secret fails closed."""
    from config import Config

    monkeypatch.setattr(Config, "TALLY_WEBHOOK_SIGNING_SECRET", "")
    response = client.post(
        "/webhooks/tally",
        data=json.dumps(_tally_payload(submission_id="unconfigured")),
        content_type="application/json",
    )

    assert response.status_code == 503
