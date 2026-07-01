"""
src/breach_notifier.py — Comunicazione di una violazione dei dati agli interessati (Art. 34 GDPR).

Quando una violazione comporta un rischio elevato per i diritti e le libertà degli interessati,
il titolare deve comunicarla "senza ingiustificato ritardo" (Art. 34(1)). Questo helper diffonde
il messaggio a tutti gli utenti attivi tramite il canale Telegram, registra l'esito nel registro
violazioni (`data_breaches.users_notified`) e nell'audit log.

NB: il canale **email** non è ancora operativo — nel codebase non esiste un client email (l'integrazione
Brevo è in roadmap, cfr. the email integration roadmap). Finché non viene integrato, la comunicazione
ufficiale agli interessati passa da Telegram + pagina web `/security-incident-{id}`. Il punto di
estensione è marcato con `_send_email_stub`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.telegram_client import TelegramClient

logger = logging.getLogger("financial_agent.breach_notifier")


@dataclass
class BreachNotificationResult:
    """Esito di una campagna di notifica violazione."""
    breach_ref: str
    total_recipients: int
    telegram_sent: int = 0
    telegram_failed: int = 0
    email_pending: int = 0
    dry_run: bool = False
    failed_chat_ids: list[str] = field(default_factory=list)


def _send_email_stub(email: str, message: str) -> None:
    """Placeholder per la notifica via email — non ancora implementata (manca client email).

    Quando si integrerà Brevo/SMTP, sostituire questa funzione con l'invio reale.
    """
    logger.warning(
        "[BreachNotifier] Canale email non implementato: notifica NON inviata a %s "
        "(integrare Brevo per abilitarlo)", email
    )


async def notify_users_of_breach(
    store,
    breach_ref: str,
    message_it: str,
    *,
    dry_run: bool = False,
) -> BreachNotificationResult:
    """Comunica la violazione `breach_ref` a tutti gli utenti attivi (Art. 34).

    Args:
        store: istanza di `UserStore`.
        breach_ref: riferimento della violazione nel registro (es. incident-20260701-001).
        message_it: testo della comunicazione, in linguaggio semplice (Art. 34(2)).
        dry_run: se True conta i destinatari senza inviare né aggiornare lo stato.

    Returns:
        BreachNotificationResult con il conteggio degli invii riusciti/falliti.

    Un fallimento di invio su un singolo utente viene registrato ma non interrompe
    la campagna verso gli altri.
    """
    recipients = store.get_users_for_breach_notification()
    result = BreachNotificationResult(
        breach_ref=breach_ref,
        total_recipients=len(recipients),
        dry_run=dry_run,
    )

    if dry_run:
        logger.info(
            "[BreachNotifier] DRY RUN %s: %d destinatari, nessun invio effettuato.",
            breach_ref, result.total_recipients,
        )
        return result

    for chat_id, email in recipients:
        try:
            await TelegramClient(chat_id=chat_id).send_report(message_it)
            result.telegram_sent += 1
        except Exception:
            result.telegram_failed += 1
            result.failed_chat_ids.append(chat_id)
            logger.exception(
                "[BreachNotifier] Invio Telegram fallito per chat_id=%s (violazione %s)",
                chat_id, breach_ref,
            )
        # Canale email: attualmente stub finché non c'è un client email.
        if email:
            _send_email_stub(email, message_it)
            result.email_pending += 1

    # Aggiorna il registro violazioni e traccia in audit log (best effort).
    now = datetime.utcnow()
    store.update_breach_record(
        breach_ref,
        users_notified=True,
        users_notified_at=now,
    )
    store.write_audit_log(
        user_id="system",
        actor="system",
        action="breach_notification",
        resource=breach_ref,
        metadata={
            "total_recipients": result.total_recipients,
            "telegram_sent": result.telegram_sent,
            "telegram_failed": result.telegram_failed,
            "email_pending": result.email_pending,
        },
    )

    logger.info(
        "[BreachNotifier] %s: inviati %d/%d via Telegram (%d falliti), %d email in attesa di canale.",
        breach_ref, result.telegram_sent, result.total_recipients,
        result.telegram_failed, result.email_pending,
    )
    return result
