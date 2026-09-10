"""Notifiche email per i reward referral applicati/sbloccati.

Modulo leaf puro (nessuna dipendenza da Flask/app.py/blueprint): usato sia dal
webhook Tally (`blueprints/public.py`) sia dai flussi di login/registrazione
web (`app.py`), evitando di duplicare la logica o di introdurre un ciclo di
import tra i due.
"""
from __future__ import annotations

import logging

from src import analytics, beta_access, brevo_client

logger = logging.getLogger(__name__)


def _send_referral_reward_emails(applied_rewards: list, unlocked_lifetime_founder_email: str | None) -> None:
    """Invia le email di notifica per i reward referral appena applicati/sbloccati.

    Fire-and-forget: eventuali errori Brevo vengono loggati ma non propagati,
    lo stato del reward in DB resta 'applied' anche se la mail fallisce.
    """
    for reward in applied_rewards:
        try:
            subject, html = beta_access.build_referral_reward_email(reward.days_granted)
            brevo_client.send_transactional_email(
                to_email=reward.beneficiary_email, subject=subject, html_content=html,
            )
        except Exception:
            logger.exception(
                "Errore invio email reward referral",
                extra={"domain": "dashboard", "event": "referral_reward_email_failed"},
            )
        if reward.role == "referred" and reward.beneficiary_chat_id:
            analytics.track(reward.beneficiary_chat_id, "referral_signup", {"days_granted": reward.days_granted, "platform": "web"})
    if unlocked_lifetime_founder_email:
        try:
            subject, html = beta_access.build_lifetime_founder_unlocked_email()
            brevo_client.send_transactional_email(
                to_email=unlocked_lifetime_founder_email, subject=subject, html_content=html,
            )
        except Exception:
            logger.exception(
                "Errore invio email Lifetime Founder sbloccato",
                extra={"domain": "dashboard", "event": "lifetime_founder_email_failed"},
            )
