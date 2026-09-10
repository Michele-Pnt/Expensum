"""Contratto di non-esposizione per i log applicativi."""

from unittest.mock import MagicMock

import pytest

from src.application.structured_logging import log_exception


pytestmark = pytest.mark.unit


def test_log_exception_keeps_only_error_type_and_safe_metadata() -> None:
    """Il testo dell'eccezione non arriva nel messaggio né nei metadati."""
    logger = MagicMock()

    log_exception(
        logger,
        level="warning",
        domain="ledger",
        event="usage_finalize_failed",
        exception=RuntimeError("dato utente riservato"),
        chat_id="123",
        meta={"operation": "weekly_plan"},
    )

    logger.warning.assert_called_once_with(
        "usage_finalize_failed",
        extra={
            "domain": "ledger",
            "event": "usage_finalize_failed",
            "chat_id": "123",
            "meta": {"error_type": "RuntimeError", "operation": "weekly_plan"},
        },
        exc_info=True,
    )
