"""Helper per eventi d'errore JSON Lines privi di contenuti utente."""

from collections.abc import Mapping
from logging import Logger
from typing import Any


def log_exception(
    logger: Logger | Any,
    *,
    level: str,
    domain: str,
    event: str,
    exception: BaseException,
    chat_id: str | None = None,
    meta: Mapping[str, object] | None = None,
) -> None:
    """Registra un'eccezione senza serializzare testo o input dell'utente."""
    payload = {"error_type": type(exception).__name__, **dict(meta or {})}
    extra: dict[str, object] = {"domain": domain, "event": event, "meta": payload}
    if chat_id is not None:
        extra["chat_id"] = str(chat_id)
    getattr(logger, level)(event, extra=extra, exc_info=True)
