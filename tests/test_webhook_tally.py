import json
import threading
import pytest
from unittest.mock import patch

pytestmark = pytest.mark.e2e


def _tally_payload(submission_id="sub_123", email="lead@example.com"):
    return {
        "eventId": "evt_1",
        "eventType": "FORM_RESPONSE",
        "data": {
            "submissionId": submission_id,
            "formId": "44pAAr",
            "fields": [
                {"key": "question_name", "label": "Nome", "type": "INPUT_TEXT", "value": "Mario"},
                {"key": "question_email", "label": "Email", "type": "INPUT_EMAIL", "value": email},
            ],
        },
    }


class _SyncThread(threading.Thread):
    """Sottoclasse di Thread che esegue il target subito in .start(), senza
    aprire un vero thread OS.

    In test, sqlite:///:memory: dà una connessione (quindi un DB) diversa per
    ogni thread OS: eseguire il job di sync su un vero thread separato
    romperebbe i test perché non vedrebbe le tabelle create sul thread
    principale. In produzione DATABASE_URL è PostgreSQL, dove questo non è un
    problema (stessa istanza fisica per ogni connessione). Sottoclassare (invece
    di sostituire interamente threading.Thread) evita di rompere altri usi di
    Thread/Timer nello stesso processo (es. flask-limiter).
    """

    def start(self):
        self.run()


def test_webhook_tally_saves_lead_and_syncs_to_brevo(client):
    from src.dashboard.app import store

    with patch("src.dashboard.app.threading.Thread", _SyncThread), \
         patch("src.dashboard.app.brevo_client.upsert_contact") as mock_upsert, \
         patch("src.dashboard.app.beta_access.grant_beta_access", return_value=None):
        response = client.post(
            "/webhooks/tally",
            data=json.dumps(_tally_payload(submission_id="sub_new", email="new@example.com")),
            content_type="application/json",
        )
        assert response.status_code == 200

    mock_upsert.assert_called_once_with("new@example.com", list_ids=[5])

    lead, is_new = store.save_tally_lead("sub_new", "new@example.com", "{}")
    assert is_new is False
    assert lead.email == "new@example.com"
    assert lead.synced_to_brevo is True


def test_webhook_tally_is_idempotent_on_duplicate_submission(client):
    with patch("src.dashboard.app.threading.Thread", _SyncThread), \
         patch("src.dashboard.app.brevo_client.upsert_contact") as mock_upsert, \
         patch("src.dashboard.app.beta_access.grant_beta_access", return_value=None):
        payload = _tally_payload(submission_id="sub_dup", email="dup@example.com")

        first = client.post("/webhooks/tally", data=json.dumps(payload), content_type="application/json")
        assert first.status_code == 200
        assert mock_upsert.call_count == 1

        # Tally può reinviare lo stesso webhook (retry): stesso submissionId,
        # non deve rifare il sync Brevo una seconda volta.
        second = client.post("/webhooks/tally", data=json.dumps(payload), content_type="application/json")
        assert second.status_code == 200
        assert mock_upsert.call_count == 1


def test_webhook_tally_missing_submission_id_returns_400(client):
    response = client.post(
        "/webhooks/tally",
        data=json.dumps({"data": {"fields": []}}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_webhook_tally_without_email_does_not_sync(client):
    with patch("src.dashboard.app.threading.Thread", _SyncThread), \
         patch("src.dashboard.app.brevo_client.upsert_contact") as mock_upsert:
        payload = _tally_payload(submission_id="sub_noemail")
        payload["data"]["fields"] = [{"key": "q", "label": "Nome", "type": "INPUT_TEXT", "value": "Mario"}]

        response = client.post("/webhooks/tally", data=json.dumps(payload), content_type="application/json")
        assert response.status_code == 200

    mock_upsert.assert_not_called()


def test_webhook_tally_auto_grants_beta_access_when_enabled(client, monkeypatch):
    from src.dashboard import app as app_module

    monkeypatch.setattr(app_module.Config, "AUTO_BETA_ACCESS_ENABLED", True)
    monkeypatch.setattr(app_module.Config, "AUTO_BETA_ACCESS_MAX_ACCOUNTS", 50)

    with patch("src.dashboard.app.threading.Thread", _SyncThread), \
         patch("src.dashboard.app.brevo_client.upsert_contact"), \
         patch("src.dashboard.app.beta_access.grant_beta_access", return_value=("web_abc", "pwd")) as mock_grant, \
         patch("src.dashboard.app.store.mark_tally_lead_beta_access_granted") as mock_mark:
        response = client.post(
            "/webhooks/tally",
            data=json.dumps(_tally_payload(submission_id="sub_auto", email="auto@example.com")),
            content_type="application/json",
        )
        assert response.status_code == 200

    mock_grant.assert_called_once()
    args = mock_grant.call_args.args
    assert args[1] == "auto@example.com"
    assert args[2] == "Mario"
    mock_mark.assert_called_once_with("sub_auto")


def test_webhook_tally_skips_auto_grant_when_disabled(client, monkeypatch):
    from src.dashboard import app as app_module

    monkeypatch.setattr(app_module.Config, "AUTO_BETA_ACCESS_ENABLED", False)

    with patch("src.dashboard.app.threading.Thread", _SyncThread), \
         patch("src.dashboard.app.brevo_client.upsert_contact"), \
         patch("src.dashboard.app.beta_access.grant_beta_access") as mock_grant:
        response = client.post(
            "/webhooks/tally",
            data=json.dumps(_tally_payload(submission_id="sub_off", email="off@example.com")),
            content_type="application/json",
        )
        assert response.status_code == 200

    mock_grant.assert_not_called()


def test_webhook_tally_skips_auto_grant_when_cap_reached(client, monkeypatch):
    from src.dashboard import app as app_module

    monkeypatch.setattr(app_module.Config, "AUTO_BETA_ACCESS_ENABLED", True)
    monkeypatch.setattr(app_module.Config, "AUTO_BETA_ACCESS_MAX_ACCOUNTS", 1)

    with patch("src.dashboard.app.threading.Thread", _SyncThread), \
         patch("src.dashboard.app.brevo_client.upsert_contact"), \
         patch("src.dashboard.app.store.count_beta_accounts_granted", return_value=1), \
         patch("src.dashboard.app.beta_access.grant_beta_access") as mock_grant:
        response = client.post(
            "/webhooks/tally",
            data=json.dumps(_tally_payload(submission_id="sub_cap", email="cap@example.com")),
            content_type="application/json",
        )
        assert response.status_code == 200

    mock_grant.assert_not_called()
