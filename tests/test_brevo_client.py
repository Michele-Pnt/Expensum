import pytest
import requests
from unittest.mock import patch, MagicMock

from src import brevo_client

pytestmark = pytest.mark.unit


def _mock_response(status_code=201):
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status.side_effect = (
        requests.exceptions.HTTPError(response=resp) if status_code >= 400 else None
    )
    return resp


def test_upsert_contact_calls_brevo_api(monkeypatch):
    monkeypatch.setattr(brevo_client.Config, "BREVO_API_KEY", "test-key")
    with patch("src.brevo_client.requests.post", return_value=_mock_response(201)) as mock_post:
        brevo_client.upsert_contact("lead@example.com", {"BETA_WAITLIST": True})

    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "https://api.brevo.com/v3/contacts"
    assert kwargs["headers"]["api-key"] == "test-key"
    assert kwargs["json"]["email"] == "lead@example.com"
    assert kwargs["json"]["attributes"] == {"BETA_WAITLIST": True}


def test_upsert_contact_passes_list_ids(monkeypatch):
    monkeypatch.setattr(brevo_client.Config, "BREVO_API_KEY", "test-key")
    with patch("src.brevo_client.requests.post", return_value=_mock_response(201)) as mock_post:
        brevo_client.upsert_contact("lead@example.com", list_ids=[5])

    assert mock_post.call_args.kwargs["json"]["listIds"] == [5]


def test_upsert_contact_omits_list_ids_when_not_passed(monkeypatch):
    monkeypatch.setattr(brevo_client.Config, "BREVO_API_KEY", "test-key")
    with patch("src.brevo_client.requests.post", return_value=_mock_response(201)) as mock_post:
        brevo_client.upsert_contact("lead@example.com")

    assert "listIds" not in mock_post.call_args.kwargs["json"]


def test_upsert_contact_skips_without_api_key(monkeypatch):
    monkeypatch.setattr(brevo_client.Config, "BREVO_API_KEY", "")
    with patch("src.brevo_client.requests.post") as mock_post:
        brevo_client.upsert_contact("lead@example.com", {"BETA_WAITLIST": True})

    mock_post.assert_not_called()


def test_upsert_contact_raises_on_client_error(monkeypatch):
    """Un 400 non è retryable (_is_retryable ritorna False): fallisce al primo tentativo, niente sleep."""
    monkeypatch.setattr(brevo_client.Config, "BREVO_API_KEY", "test-key")
    with patch("src.brevo_client.requests.post", return_value=_mock_response(400)):
        with pytest.raises(requests.exceptions.HTTPError):
            brevo_client.upsert_contact("bad-email", {})


def test_send_transactional_email_calls_brevo_api(monkeypatch):
    monkeypatch.setattr(brevo_client.Config, "BREVO_API_KEY", "test-key")
    monkeypatch.setattr(brevo_client.Config, "BREVO_SENDER_EMAIL", "hello@expensum.it")
    monkeypatch.setattr(brevo_client.Config, "BREVO_SENDER_NAME", "Expensum")
    with patch("src.brevo_client.requests.post", return_value=_mock_response(201)) as mock_post:
        brevo_client.send_transactional_email(
            "lead@example.com", "Benvenuto", "<p>ciao</p>"
        )

    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "https://api.brevo.com/v3/smtp/email"
    assert kwargs["headers"]["api-key"] == "test-key"
    assert kwargs["json"]["sender"] == {"email": "hello@expensum.it", "name": "Expensum"}
    assert kwargs["json"]["to"] == [{"email": "lead@example.com"}]
    assert kwargs["json"]["subject"] == "Benvenuto"
    assert kwargs["json"]["htmlContent"] == "<p>ciao</p>"


def test_send_transactional_email_passes_headers(monkeypatch):
    monkeypatch.setattr(brevo_client.Config, "BREVO_API_KEY", "test-key")
    with patch("src.brevo_client.requests.post", return_value=_mock_response(201)) as mock_post:
        brevo_client.send_transactional_email(
            "lead@example.com", "Subject", "<p>x</p>",
            headers={"List-Unsubscribe": "<https://example.com/unsubscribe>"},
        )

    assert mock_post.call_args.kwargs["json"]["headers"] == {
        "List-Unsubscribe": "<https://example.com/unsubscribe>"
    }


def test_send_transactional_email_omits_headers_when_not_passed(monkeypatch):
    monkeypatch.setattr(brevo_client.Config, "BREVO_API_KEY", "test-key")
    with patch("src.brevo_client.requests.post", return_value=_mock_response(201)) as mock_post:
        brevo_client.send_transactional_email("lead@example.com", "Subject", "<p>x</p>")

    assert "headers" not in mock_post.call_args.kwargs["json"]


def test_send_transactional_email_skips_without_api_key(monkeypatch):
    monkeypatch.setattr(brevo_client.Config, "BREVO_API_KEY", "")
    with patch("src.brevo_client.requests.post") as mock_post:
        brevo_client.send_transactional_email("lead@example.com", "Subject", "<p>x</p>")

    mock_post.assert_not_called()


def test_send_transactional_email_raises_on_client_error(monkeypatch):
    monkeypatch.setattr(brevo_client.Config, "BREVO_API_KEY", "test-key")
    with patch("src.brevo_client.requests.post", return_value=_mock_response(400)):
        with pytest.raises(requests.exceptions.HTTPError):
            brevo_client.send_transactional_email("bad", "Subject", "<p>x</p>")


@pytest.mark.parametrize(
    "exc,expected",
    [
        (requests.exceptions.Timeout(), True),
        (requests.exceptions.ConnectionError(), True),
        (ValueError("not a requests error"), False),
    ],
)
def test_is_retryable_matches_transient_errors(exc, expected):
    assert brevo_client._is_retryable(exc) is expected


def test_is_retryable_checks_http_status_code():
    resp_503 = MagicMock(status_code=503)
    resp_400 = MagicMock(status_code=400)
    assert brevo_client._is_retryable(requests.exceptions.HTTPError(response=resp_503)) is True
    assert brevo_client._is_retryable(requests.exceptions.HTTPError(response=resp_400)) is False
