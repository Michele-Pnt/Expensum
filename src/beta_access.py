"""
src/beta_access.py — Creazione account beta e invio email di accesso.

Condiviso tra creazione manuale (administrative provisioning) e automatica al
submit del form Tally (src/dashboard/app.py::webhook_tally, con tetto
Config.AUTO_BETA_ACCESS_MAX_ACCOUNTS).
"""

import logging

from config import Config
from src import brevo_client
from src.user_store import UserStore

logger = logging.getLogger(__name__)


_SOCIAL_LINKS: list[tuple[str, str, str]] = [
    ("LinkedIn", "https://www.linkedin.com/company/expensum/", "linkedin.png"),
    ("Instagram", "https://instagram.com/expensum.finance", "instagram.png"),
    ("Facebook", "https://acesse.one/ite4lxk", "facebook.png"),
    ("TikTok", "https://www.tiktok.com/@expensum", "tiktok.png"),
]


def build_welcome_email(name: str, login_url: str, email: str, password: str) -> tuple[str, str]:
    """Ritorna (subject, html) dell'email di benvenuto/accesso beta."""
    display_name = name or "ciao"
    base_url = Config.WEBAPP_BASE_URL
    feedback_url = f"{base_url}/feedback"
    icons_base_url = f"{base_url}/email/icons"
    social_icons_html = "".join(
        f'<a href="{url}" style="margin:0 6px;text-decoration:none;" aria-label="{label}">'
        f'<img src="{icons_base_url}/{icon}" width="28" height="28" alt="{label}" '
        f'style="border-radius:50%;vertical-align:middle;"></a>'
        for label, url, icon in _SOCIAL_LINKS
    )
    subject = "Sei nella beta di Expensum 🎉 ecco come accedere"
    html = f"""
    <p>Ciao {display_name},</p>
    <p>grazie per esserti iscritto/a alla waitlist di Expensum! Il sito è ancora in
    costruzione, ma la beta è già viva: ecco le tue credenziali di accesso.</p>
    <p>
      <strong>Link:</strong> <a href="{login_url}">{login_url}</a><br>
      <strong>Email:</strong> {email}<br>
      <strong>Password:</strong> {password}
    </p>
    <p>Ti consigliamo di cambiare la password dopo il primo accesso
    (Impostazioni → Privacy).</p>
    <p>Nella web app trovi anche una pagina <strong>Feedback</strong>
    (<a href="{feedback_url}">{feedback_url}</a>) pensata apposta per segnalare
    bug o dirci cosa pensi dell'app: sei tra le prime persone a provarla, per una
    beta è oro.</p>
    <p>A presto,<br>Michele, Expensum</p>
    <hr>
    <p style="text-align:center;">{social_icons_html}</p>
    <p style="font-size:12px;color:#888;text-align:center;">
      <a href="{base_url}">Sito</a> ·
      <a href="{base_url}/privacy">Privacy Policy</a> ·
      <a href="{base_url}/terms">Termini di Servizio</a> ·
      <a href="{base_url}/cookies">Cookie Policy</a>
    </p>
    """
    return subject, html


def build_referral_reward_email(days_granted: int) -> tuple[str, str]:
    """Ritorna (subject, html) dell'email di notifica reward referral sbloccato."""
    login_url = f"{Config.WEBAPP_BASE_URL}/login"
    subject = f"Hai sbloccato {days_granted} giorni extra di Pro 🎁"
    html = f"""
    <p>Ciao,</p>
    <p>grazie al referral, il tuo account Expensum è stato esteso di
    <strong>{days_granted} giorni</strong> di piano Pro.</p>
    <p><a href="{login_url}">Accedi</a> per continuare a usarlo.</p>
    <p>A presto,<br>Michele, Expensum</p>
    """
    return subject, html


def build_lifetime_founder_unlocked_email() -> tuple[str, str]:
    """Ritorna (subject, html) dell'email per lo sblocco dell'accesso garantito Lifetime Founder."""
    subject = "Hai sbloccato l'accesso garantito a Lifetime Founder 🏆"
    html = """
    <p>Ciao,</p>
    <p>hai portato 3 persone su Expensum tramite il tuo link di invito: come
    ringraziamento, ti garantiamo un posto nell'offerta <strong>Lifetime Founder</strong>
    quando la apriremo, senza rischiare di restare fuori dai posti disponibili.</p>
    <p>Ti scriveremo appena l'offerta sarà attiva.</p>
    <p>A presto,<br>Michele, Expensum</p>
    """
    return subject, html


def grant_beta_access(store: UserStore, email: str, name: str = "") -> tuple[str, str] | None:
    """Crea l'account beta (se non esiste già) e invia l'email di accesso via Brevo.

    Ritorna (chat_id, password) se creato ora, None se esisteva già un account
    per quell'email (nessuna azione, nessuna seconda email).
    """
    result = store.create_beta_account(email, name)
    if result is None:
        return None

    chat_id, password = result
    login_url = f"{Config.WEBAPP_BASE_URL}/login"
    subject, html = build_welcome_email(name, login_url, email, password)
    brevo_client.send_transactional_email(to_email=email, subject=subject, html_content=html)
    return chat_id, password
