"""
src/trial_lifecycle.py — Logica pura del drip lifecycle trial→Pro (D7/D14/D25/D29).

Nessuna dipendenza da DB o rete: le funzioni qui dentro sono testabili in isolamento.
Il job schedulato (bot.py) è responsabile di recuperare gli utenti, lo storage e di
effettuare gli invii veri (Telegram/Brevo), usando queste funzioni come building block.
"""

import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)

# Giorni dall'inizio del trial (trial_started_at) a cui è dovuto ciascuno step.
DRIP_STEPS: dict[str, int] = {"d7": 7, "d14": 14, "d25": 25, "d29": 29}

# Ordine di invio (dal più vecchio al più recente), usato per recuperare step arretrati
# nell'ordine corretto se il job ha saltato più giorni.
_STEP_ORDER: list[str] = sorted(DRIP_STEPS, key=lambda step: DRIP_STEPS[step])

# Bottoni CTA delle email drip:
# - reports: D7/D14 (engagement), verso il login con redirect ai report
#   (src/dashboard/app.py::web_login supporta ?next=... per riportare l'utente lì dopo
#   l'autenticazione).
# - upgrade: D25/D29 (trial in scadenza), verso la sezione prezzi della landing page —
#   non esiste ancora una pagina piani in-app autenticata, il checkout Stripe è fuori
#   scope in questa fase beta (vedi task ClickUp pagamenti post-beta).
_EMAIL_SIGNATURE = '<p style="margin-top:24px;color:#6b7280">— Moneo 🤖, il tuo assistente Expensum</p>'

_EMAIL_CTA_BUTTON = (
    '<p style="margin-top:24px">'
    '<a href="{reports_url}" '
    'style="display:inline-block;padding:12px 24px;background:#5f55ee;color:#ffffff;'
    'text-decoration:none;border-radius:8px;font-weight:600">Vai ai tuoi report</a>'
    "</p>" + _EMAIL_SIGNATURE
)
_EMAIL_CTA_BUTTON_UPGRADE = (
    '<p style="margin-top:24px">'
    '<a href="{piani_url}" '
    'style="display:inline-block;padding:12px 24px;background:#5f55ee;color:#ffffff;'
    'text-decoration:none;border-radius:8px;font-weight:600">Scegli il tuo piano</a>'
    "</p>" + _EMAIL_SIGNATURE
)

# Step per cui il bottone (email + Telegram) porta ai piani invece che ai report.
UPGRADE_CTA_STEPS: frozenset[str] = frozenset({"d25", "d29"})

DRIP_TEMPLATES: dict[str, dict[str, str]] = {
    "d7": {
        "telegram_text": (
            "🌱 *Una settimana con Expensum!*\n\n"
            "Moneo ha tenuto d'occhio le tue spese: ne ha già contate {expense_count}. "
            "Continua così e vai alla dashboard per scoprire il tuo primo report personalizzato."
        ),
        "email_subject": "Moneo ha contato {expense_count} spese per te 🎉",
        "email_html": (
            "<p>Ciao{name},</p>"
            "<p>In una settimana Moneo ha già registrato e organizzato <strong>{expense_count} spese</strong> "
            "per te. Ottimo inizio!</p>"
            "<p>Apri i tuoi report per scoprire il primo riepilogo personalizzato che Moneo ha "
            "generato dai tuoi dati reali.</p>" + _EMAIL_CTA_BUTTON
        ),
    },
    "d14": {
        "telegram_text": (
            "📊 *Due settimane di progressi*\n\n"
            "Moneo ha analizzato come stanno andando le tue finanze da quando hai iniziato. "
            "Solo con Expensum Pro sblocchi l'analisi completa sul tuo stile di vita e le tue finanze."
        ),
        "email_subject": "Moneo ha preparato il tuo report dei 14 giorni",
        "email_html": (
            "<p>Ciao{name},</p>"
            "<p>Sono passate due settimane: Moneo ha generato per te un riepilogo di come stai "
            "usando Expensum e dove potresti trarre ancora più valore con il piano Pro.</p>" + _EMAIL_CTA_BUTTON
        ),
    },
    "d25": {
        "telegram_text": (
            "⏳ *Il tuo trial finisce tra {days_left} giorni*\n\n"
            "Dopo la scadenza perderai foto scontrino, audio, conti illimitati, report AI "
            "infiniti e analisi avanzate delle tue finanze. Scrivi /piano per scegliere il tuo piano "
            "e non perdere nulla."
        ),
        "email_subject": "Il tuo trial Expensum Pro finisce tra {days_left} giorni",
        "email_html": (
            "<p>Ciao{name},</p>"
            "<p>Moneo ti avvisa: il tuo trial Pro sta per finire (tra <strong>{days_left} giorni</strong>). "
            "Ecco cosa perderesti tornando al piano Free: foto scontrino, audio, conti "
            "illimitati, report AI mensile, chat conversazionale, analytics avanzata.</p>" + _EMAIL_CTA_BUTTON_UPGRADE
        ),
    },
    "d29": {
        "telegram_text": (
            "🔒 *Ultimo giorno di trial*\n\n"
            "Da domani il tuo account torna al piano Free. Scrivi /piano e usa il codice "
            "*{discount_code}* per uno sconto sul primo mese."
        ),
        "email_subject": "Moneo ha preparato uno sconto speciale per te",
        "email_html": (
            "<p>Ciao{name},</p>"
            "<p>Oggi è l'ultimo giorno del tuo trial Pro. Moneo ha preparato per te un codice "
            "sconto sul primo mese: usa <strong>{discount_code}</strong> e continua "
            "a usare tutte le funzionalità Pro senza interruzioni.</p>" + _EMAIL_CTA_BUTTON_UPGRADE
        ),
    },
}


def compute_days_since_trial_start(
    trial_started_at: datetime, reference_date: date | None = None
) -> int:
    """Giorni interi trascorsi dall'inizio del trial ad oggi (o a `reference_date`)."""
    reference_date = reference_date or date.today()
    return (reference_date - trial_started_at.date()).days


def steps_pending(days_since_trial_start: int, already_sent_steps: set[str]) -> list[str]:
    """Step con soglia già raggiunta/superata e non ancora presenti in `already_sent_steps`.

    Usa `>=` invece del match esatto sul giorno per non perdere uno step se il job non
    gira un giorno (es. downtime del bot): verrà recapitato con un giorno di ritardo,
    accettabile per una comunicazione di lifecycle. In condizioni normali la lista ha al
    massimo un elemento.
    """
    return [
        step
        for step in _STEP_ORDER
        if days_since_trial_start >= DRIP_STEPS[step] and step not in already_sent_steps
    ]


def count_user_expenses_since_signup(storage, trial_started_at: datetime) -> int:
    """Conta le spese registrate dall'utente da `trial_started_at` ad oggi.

    `storage` è l'interfaccia astratta `FinancialStorage` (mai accesso diretto a
    Notion/Postgres da qui, coerente con le regole architetturali del progetto).
    """
    transactions = storage.fetch_all_transactions(
        start_date=trial_started_at.date(), end_date=date.today()
    )
    return len(transactions)


def build_drip_message(step: str, channel: str, context: dict) -> str:
    """Applica i placeholder al template dello step/canale richiesto.

    Non solleva eccezioni per placeholder mancanti: logga un warning (mai il testo
    renderizzato, coerente con le regole di logging) e ritorna il template non sostituito.
    """
    key = "telegram_text" if channel == "telegram" else "email_html"
    template = DRIP_TEMPLATES[step][key]
    try:
        return template.format(**context)
    except KeyError as e:
        logger.warning(
            "Placeholder mancante nel template drip",
            extra={"domain": "app", "event": "drip_template_error", "meta": {
                "step": step, "channel": channel, "missing_key": str(e),
            }},
        )
        return template
