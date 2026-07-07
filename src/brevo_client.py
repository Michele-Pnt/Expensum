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
def send_transactional_email(to_email: str, subject: str, html_content: str) -> None:
    """Invia una email transazionale 1-a-1 tramite l'API Brevo (stessi server/dominio
    autenticato dell'automazione marketing, nessuna perdita di deliverability).

    Usata per l'invio delle credenziali di accesso ai beta tester
    (administrative provisioning): contenuto dinamico per destinatario, quindi non
    esprimibile con la sola automazione a trigger del pannello Brevo.

    Args:
        html_content: corpo HTML già pronto (nessun dato finanziario dell'utente,
            solo credenziali di accesso appena generate).
    """
    if not Config.BREVO_API_KEY:
        logger.warning(
            "BREVO_API_KEY non configurata, skip send_transactional_email",
            extra={"domain": "dashboard", "event": "brevo_skipped_no_api_key"},
        )
        return

    headers = {
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

    response = requests.post(
        f"{_BASE_URL}/smtp/email",
        headers=headers,
        json=payload,
        timeout=_REQUEST_TIMEOUT,
    )
    if response.status_code >= 400:
        response.raise_for_status()
