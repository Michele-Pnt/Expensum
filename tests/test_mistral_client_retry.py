"""
tests/test_mistral_client_retry.py — Copertura dedicata per `_is_retryable` e
`_sdk_error_status_code` in src/mistral_client.py.

Queste due funzioni sono usate sia dal retry di tenacity in MistralClient sia dal
fallback multi-modello di ExpenseParser (src/expense_parser.py::_call_mistral).
Nessuna chiamata reale a Mistral: sono funzioni pure su eccezioni sintetiche.
"""

import httpx
import pytest

from src.mistral_client import _is_retryable, _sdk_error_status_code

pytestmark = pytest.mark.unit


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.mistral.ai/v1/chat/completions")
    response = httpx.Response(status_code=status_code, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


class TestIsRetryable:
    @pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
    def test_retryable_http_status_codes(self, status_code):
        assert _is_retryable(_http_status_error(status_code)) is True

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422])
    def test_non_retryable_http_status_codes(self, status_code):
        assert _is_retryable(_http_status_error(status_code)) is False

    def test_connect_error_is_retryable(self):
        assert _is_retryable(httpx.ConnectError("connection refused")) is True

    def test_timeout_exception_is_retryable(self):
        assert _is_retryable(httpx.TimeoutException("timed out")) is True

    def test_generic_connection_and_timeout_errors_are_retryable(self):
        assert _is_retryable(ConnectionError("reset")) is True
        assert _is_retryable(TimeoutError("timed out")) is True

    @pytest.mark.parametrize(
        "message",
        ["429 Too Many Requests", "500 Internal Server Error", "502 Bad Gateway",
         "503 Service Unavailable", "504 Gateway Timeout", "rate limit exceeded",
         "Too many requests, please retry"],
    )
    def test_sdk_error_message_fallback_is_retryable(self, message):
        assert _is_retryable(RuntimeError(message)) is True

    def test_non_retryable_generic_exception(self):
        assert _is_retryable(ValueError("invalid schema")) is False


class TestSdkErrorStatusCode:
    def test_extracts_status_code_when_present(self):
        exc = RuntimeError("SDKError")
        exc.status_code = 502
        assert _sdk_error_status_code(exc) == 502

    def test_returns_none_when_attribute_missing(self):
        assert _sdk_error_status_code(RuntimeError("boom")) is None

    def test_returns_none_for_httpx_errors_without_status_code_attr(self):
        assert _sdk_error_status_code(_http_status_error(503)) is None
