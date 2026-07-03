"""Wrapper server-side per l'invio di eventi di prodotto a PostHog, GA4 e Meta.

Tutti gli eventi (bot Telegram e webapp) passano da qui: nessuno script di
terze parti viene mai caricato nel browser, il frontend chiama solo
/api/track (same-origin) che inoltra qui. Questo evita di dover concedere a
PostHog/Google/Meta il permesso di eseguire script nella pagina via CSP.

Regole GDPR:
- distinct_id deve essere sempre il chat_id (pseudonimo numerico) o un id
  anonimo generato lato client, mai email o nome
- Non includere mai amount, category_name, merchant nelle properties
- Non includere mai il contenuto di feedback o notifiche nelle properties
"""
import logging
import os

import posthog as _ph
import requests

logger = logging.getLogger(__name__)

_api_key: str = os.environ.get("POSTHOG_API_KEY", "")
_host: str = os.environ.get("POSTHOG_HOST", "https://eu.i.posthog.com")

if _api_key:
    _ph.project_api_key = _api_key
    _ph.host = _host
else:
    _ph.disabled = True
    logger.debug("[analytics] POSTHOG_API_KEY non impostata — tracking disabilitato")

_ga4_measurement_id: str = os.environ.get("GA4_MEASUREMENT_ID", "")
_ga4_api_secret: str = os.environ.get("GA4_API_SECRET", "")
_ga4_endpoint = "https://www.google-analytics.com/mp/collect"

_meta_pixel_id: str = os.environ.get("META_PIXEL_ID", "")
_meta_access_token: str = os.environ.get("META_ACCESS_TOKEN", "")
_meta_endpoint_tmpl = "https://graph.facebook.com/v21.0/{pixel_id}/events"

_REQUEST_TIMEOUT = 5


def track(distinct_id: str, event: str, properties: dict | None = None) -> None:
    """Emette un evento PostHog. Fire-and-forget, non blocca mai il flusso principale."""
    if not _api_key:
        return
    try:
        _ph.capture(distinct_id=distinct_id, event=event, properties=properties or {})
    except Exception as exc:
        logger.debug("[analytics] capture fallito per '%s': %s", event, exc)


def identify(distinct_id: str, properties: dict | None = None) -> None:
    """Associa proprietà al profilo utente in PostHog (no PII)."""
    if not _api_key:
        return
    try:
        _ph.identify(distinct_id=distinct_id, properties=properties or {})
    except Exception as exc:
        logger.debug("[analytics] identify fallito per '%s': %s", distinct_id, exc)


def track_ga4(client_id: str, event: str, properties: dict | None = None) -> None:
    """Emette un evento a GA4 via Measurement Protocol (server-to-server, no gtag.js)."""
    if not (_ga4_measurement_id and _ga4_api_secret):
        return
    try:
        requests.post(
            _ga4_endpoint,
            params={"measurement_id": _ga4_measurement_id, "api_secret": _ga4_api_secret},
            json={
                "client_id": client_id,
                "events": [{"name": event, "params": properties or {}}],
            },
            timeout=_REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.debug("[analytics] GA4 capture fallito per '%s': %s", event, exc)


def track_meta(event: str, event_id: str, properties: dict | None = None) -> None:
    """Emette un evento a Meta via Conversions API (server-to-server, no fbevents.js).

    Niente dati identificativi utente (email/telefono/IP) inviati: solo evento
    e properties custom, coerente con le regole GDPR del modulo.
    """
    if not (_meta_pixel_id and _meta_access_token):
        return
    try:
        requests.post(
            _meta_endpoint_tmpl.format(pixel_id=_meta_pixel_id),
            params={"access_token": _meta_access_token},
            json={
                "data": [{
                    "event_name": event,
                    "event_id": event_id,
                    "action_source": "website",
                    "custom_data": properties or {},
                }],
            },
            timeout=_REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.debug("[analytics] Meta CAPI capture fallito per '%s': %s", event, exc)
