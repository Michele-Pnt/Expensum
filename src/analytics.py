"""Thin wrapper around PostHog Python client for product analytics.

Regole GDPR:
- distinct_id deve essere sempre il chat_id (pseudonimo numerico, mai email o nome)
- Non includere mai amount, category_name, merchant nelle properties
- Non includere mai il contenuto di feedback o notifiche nelle properties
"""
import logging
import os

import posthog as _ph

logger = logging.getLogger(__name__)

_api_key: str = os.environ.get("POSTHOG_API_KEY", "")
_host: str = os.environ.get("POSTHOG_HOST", "https://eu.i.posthog.com")

if _api_key:
    _ph.project_api_key = _api_key
    _ph.host = _host
else:
    _ph.disabled = True
    logger.debug("[analytics] POSTHOG_API_KEY non impostata — tracking disabilitato")


def track(distinct_id: str, event: str, properties: dict | None = None) -> None:
    """Emette un evento PostHog. Fire-and-forget, non blocca mai il flusso principale."""
    if not _api_key:
        return
    try:
        _ph.capture(distinct_id, event, properties or {})
    except Exception as exc:
        logger.debug("[analytics] capture fallito per '%s': %s", event, exc)


def identify(distinct_id: str, properties: dict | None = None) -> None:
    """Associa proprietà al profilo utente in PostHog (no PII)."""
    if not _api_key:
        return
    try:
        _ph.identify(distinct_id, properties or {})
    except Exception as exc:
        logger.debug("[analytics] identify fallito per '%s': %s", distinct_id, exc)
