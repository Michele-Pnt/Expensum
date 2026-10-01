"""
src/brevo_client.py — Integrazione con Brevo (email marketing / CRM, sede EU).

Due usi distinti, stessa infrastruttura Brevo (dominio mittente autenticato,
stessa deliverability):
- upsert_contact: sincronizza un contatto verso una lista (es. waitlist beta
  via Tally); l'eventuale email di follow-up automatica è configurata nel
  pannello Brevo (Automation), non da questo modulo.
- send_transactional_email: invio diretto 1-a-1 con contenuto dinamico per
  destinatario (es. credenziali beta generate da administrative provisioning),
  triggerato dal nostro codice invece che da un'automazione a evento.
"""

import logging
from html import escape
from urllib.parse import quote

import requests
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from config import Config

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.brevo.com/v3"
_REQUEST_TIMEOUT = 10


class BrevoError(Exception):
    """Errore non recuperabile nella comunicazione con Brevo."""


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, requests.exceptions.Timeout):
        return True
    if isinstance(exc, requests.exceptions.ConnectionError):
        return True
    if isinstance(exc, requests.exceptions.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        return status in (429, 500, 502, 503, 504)
    return False


@retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def upsert_contact(
    email: str,
    attributes: dict | None = None,
    list_ids: list[int] | None = None,
) -> None:
    """Crea o aggiorna un contatto Brevo (idempotente lato Brevo su email).

    Args:
        attributes: attributi Brevo del contatto. Non passare mai dati
            finanziari o contenuto libero dell'utente qui.
        list_ids: liste Brevo a cui aggiungere il contatto (es. la lista
            "Beta Waitlist"). Le automazioni Brevo possono triggerarsi
            sull'ingresso in una lista, senza bisogno di attributi custom.
    """
    if not Config.BREVO_API_KEY:
        logger.warning(
            "BREVO_API_KEY non configurata, skip upsert_contact",
            extra={"domain": "dashboard", "event": "brevo_skipped_no_api_key"},
        )
        return

    headers = {
        "api-key": Config.BREVO_API_KEY,
        "content-type": "application/json",
        "accept": "application/json",
    }
    payload = {
        "email": email,
        "attributes": attributes or {},
        "updateEnabled": True,
    }
    if list_ids:
        payload["listIds"] = list_ids

    response = requests.post(
        f"{_BASE_URL}/contacts",
        headers=headers,
        json=payload,
        timeout=_REQUEST_TIMEOUT,
    )
    if response.status_code >= 400:
        response.raise_for_status()


@retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def send_transactional_email(
    to_email: str,
    subject: str,
    html_content: str,
    headers: dict | None = None,
) -> None:
    """Invia una email transazionale 1-a-1 tramite l'API Brevo (stessi server/dominio
    autenticato dell'automazione marketing, nessuna perdita di deliverability).

    Usata per l'invio delle credenziali di accesso ai beta tester
    (administrative provisioning) e per il drip lifecycle trial (src/trial_lifecycle.py):
    contenuto dinamico per destinatario, quindi non esprimibile con la sola automazione a
    trigger del pannello Brevo.

    Args:
        html_content: corpo HTML già pronto (nessun dato finanziario dell'utente,
            solo credenziali di accesso appena generate o contenuto lifecycle).
        headers: header SMTP opzionali aggiuntivi (es. `List-Unsubscribe` /
            `List-Unsubscribe-Post` per le comunicazioni di marketing/lifecycle,
            RFC 8058 — mostra all'utente il bottone nativo di disiscrizione in Gmail/Outlook).
    """
    if not Config.BREVO_API_KEY:
        logger.warning(
            "BREVO_API_KEY non configurata, skip send_transactional_email",
            extra={"domain": "dashboard", "event": "brevo_skipped_no_api_key"},
        )
        return

    request_headers = {
        "api-key": Config.BREVO_API_KEY,
        "content-type": "application/json",
        "accept": "application/json",
    }
    payload = {
        "sender": {"email": Config.BREVO_SENDER_EMAIL, "name": Config.BREVO_SENDER_NAME},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_content,
    }
    if headers:
        payload["headers"] = headers

    response = requests.post(
        f"{_BASE_URL}/smtp/email",
        headers=request_headers,
        json=payload,
        timeout=_REQUEST_TIMEOUT,
    )
    if response.status_code >= 400:
        response.raise_for_status()


def send_verification_email(to_email: str, raw_token: str) -> None:
    """Send only the one-time verification link, never a password."""
    verification_url = (
        f"{Config.WEBAPP_BASE_URL.rstrip('/')}/verify-email?token={quote(raw_token, safe='')}"
    )
    html_content = (
        "<p>Conferma il tuo indirizzo email per attivare il tuo account Expensum.</p>"
        f'<p><a href="{escape(verification_url, quote=True)}">Verifica email</a></p>'
        "<p>Il link scade tra 24 ore.</p>"
    )
    send_transactional_email(
        to_email,
        "Conferma il tuo account Expensum",
        html_content,
    )
