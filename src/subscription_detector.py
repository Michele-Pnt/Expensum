"""
src/subscription_detector.py — Rilevamento abbonamenti ricorrenti dalle spese.

Feature 100% Free: non nasconde nulla dietro un paywall, aiuta l'utente a smettere
di aggiungere a mano abbonamenti che già paga. La leva di conversione a Pro vive
altrove (limiti quantitativi su conti/abbonamenti tracciabili), non qui.

Scelte di design deliberate (vedi discussione di sessione):
- Nessun fuzzy matching sui nomi liberi delle spese. Il gruppo è identificato da
  `(categoria, importo ± tolleranza, cadenza)`; il nome mostrato è semplicemente
  quello dell'ultima occorrenza. L'ambiguità residua (due nomi diversi che finiscono
  nello stesso gruppo) la risolve l'utente con un tap Sì/No, non un algoritmo.
- L'analisi è ristretta alle categorie "subscription-prone" (keyword sul nome
  categoria): taglia a monte il rischio di raggruppare per coincidenza due spese
  scorrelate con lo stesso importo in categorie come "Bar" o "Ristoranti".
- Bande di intervallo larghe per cadenza: l'input è manuale (l'utente registra
  la spesa quando se ne ricorda, non quando viene addebitata), pretendere
  precisione al giorno romperebbe il rilevamento per la maggioranza dei casi reali.
- Mai un'affermazione automatica ("hai un abbonamento"): sempre un candidato con
  conferma Sì/No (`confirm_candidate`/`dismiss_candidate`), così i falsi positivi
  residui costano un tap all'utente, non credibilità alla feature.
- Nessuna chiamata LLM: tutto il calcolo che genera importi mostrati come fatti
  finanziari è deterministico e testabile, mai delegato a un modello.

Entry point live: `evaluate_and_track`, chiamato da bot.py subito dopo che una
spesa viene confermata e salvata (stesso punto di aggancio di
`category_matcher.evaluate_and_track`, tabella e logica separate). Lo stesso
entry point, applicato in ordine cronologico allo storico esistente, alimenta
anche `scripts/backfill_subscription_candidates.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session

from config import Config
from src.storage.base import FinancialStorage
from src.storage.models import SubscriptionCandidate

# Keyword (lowercase, substring) sul nome categoria che identificano categorie
# tipicamente popolate da spese ricorrenti fisse. Un falso negativo (categoria
# rinominata in modo non standard) è accettabile — qui si preferisce precisione
# a recall: un abbonamento non rilevato l'utente lo aggiunge a mano come oggi,
# mentre troppi falsi positivi sono rumore che spegne la fiducia nella feature.
_SUBSCRIPTION_CATEGORY_KEYWORDS = (
    "abbonament", "streaming", "palestra", "assicura", "bollett", "utenz",
)

# Bande di intervallo (giorni) tollerate fra due occorrenze consecutive per
# ciascuna cadenza. Volutamente larghe: l'utente registra la spesa quando se ne
# ricorda, non quando viene addebitata.
_CADENCE_BANDS: dict[str, tuple[int, int]] = {
    "weekly": (5, 10),
    "monthly": (20, 45),
    "quarterly": (75, 105),
    "yearly": (340, 390),
}

# Cadenza rilevata -> sub_type riconosciuto da src/billing_utils.py, per restare
# coerenti con la stessa matematica di equivalente mensile già usata dalla
# dashboard per gli abbonamenti tracciati a mano.
_CADENCE_TO_SUB_TYPE = {
    "weekly": "weekly",
    "monthly": "monthly",
    "quarterly": "quarterly",
    "yearly": "yearly",
}

_CADENCE_LABEL_IT = {
    "weekly": "a settimana",
    "monthly": "al mese",
    "quarterly": "al trimestre",
    "yearly": "all'anno",
}


@dataclass
class SubscriptionEvalResult:
    """Esito della valutazione di una spesa appena confermata.

    `awaiting_confirmation` è True solo quando il candidato ha appena superato
    la soglia di occorrenze: il chiamante (bot.py) deve mostrare il Sì/No.
    """

    candidate_id: int | None = None
    awaiting_confirmation: bool = False
    display_name: str | None = None
    category_name: str | None = None
    amount: float | None = None
    cadence: str | None = None


def is_subscription_prone_category(category_name: str | None) -> bool:
    """True se il nome categoria contiene una keyword da spesa ricorrente."""
    if not category_name:
        return False
    lowered = category_name.lower()
    return any(kw in lowered for kw in _SUBSCRIPTION_CATEGORY_KEYWORDS)


def cadence_label_it(cadence: str | None) -> str:
    return _CADENCE_LABEL_IT.get(cadence or "", "periodicamente")


def _amount_tolerance(amount: float) -> float:
    return max(
        Config.SUBSCRIPTION_AMOUNT_TOLERANCE_MIN,
        abs(amount) * Config.SUBSCRIPTION_AMOUNT_TOLERANCE_PCT,
    )


def _cadence_for_gap(gap_days: int) -> str | None:
    """Ritorna la cadenza la cui banda contiene `gap_days`, o None se nessuna combacia."""
    for cadence, (lo, hi) in _CADENCE_BANDS.items():
        if lo <= gap_days <= hi:
            return cadence
    return None


def evaluate_and_track(
    session: Session,
    user_id: str,
    expense_date: date,
    amount: float | None,
    category_name: str | None,
    name: str,
) -> SubscriptionEvalResult:
    """Valuta una spesa appena confermata rispetto ai candidati aperti dell'utente.

    Nessuna chiamata esterna (LLM, API): puro raggruppamento deterministico.
    Va chiamata con una `Session` attiva; committa internamente (stesso pattern
    di `category_matcher.evaluate_and_track`).
    """
    if not amount or amount <= 0 or not is_subscription_prone_category(category_name):
        return SubscriptionEvalResult()

    tolerance = _amount_tolerance(amount)
    now = datetime.utcnow()

    # Solo candidate ancora "vivi": un dismissed è una decisione definitiva
    # dell'utente; un confirmed è già un Subscription vero, i rinnovi successivi
    # li gestisce _nightly_subscription_job sull'abbonamento reale, non questo modulo.
    candidates = (
        session.query(SubscriptionCandidate)
        .filter(
            SubscriptionCandidate.user_id == user_id,
            SubscriptionCandidate.category_name == category_name,
            SubscriptionCandidate.status == "pending",
        )
        .all()
    )

    match = None
    match_cadence = None
    for candidate in candidates:
        if abs(float(candidate.amount) - amount) > tolerance:
            continue
        gap_days = (expense_date - candidate.last_occurrence_date).days
        if gap_days <= 0:
            continue  # spesa retroattiva prima dell'ultima occorrenza nota, ignorata
        if candidate.cadence:
            # Cadenza già nota: la nuova occorrenza deve rispettare la STESSA banda,
            # non una qualunque — altrimenti un acquisto casuale mesi dopo un
            # abbonamento mensile lo trasformerebbe in "trimestrale".
            lo, hi = _CADENCE_BANDS[candidate.cadence]
            if lo <= gap_days <= hi:
                match, match_cadence = candidate, candidate.cadence
                break
        else:
            cadence = _cadence_for_gap(gap_days)
            if cadence:
                match, match_cadence = candidate, cadence
                break

    if match is None:
        candidate = SubscriptionCandidate(
            user_id=user_id,
            category_name=category_name,
            amount=amount,
            cadence=None,
            display_name=name,
            occurrences=1,
            first_occurrence_date=expense_date,
            last_occurrence_date=expense_date,
            last_seen_at=now,
            status="pending",
        )
        session.add(candidate)
        session.commit()
        return SubscriptionEvalResult(candidate_id=candidate.id)

    match.occurrences += 1
    match.cadence = match_cadence
    match.last_occurrence_date = expense_date
    match.last_seen_at = now
    match.display_name = name
    match.amount = amount  # l'ultima occorrenza è la stima più aggiornata dell'importo

    awaiting_confirmation = False
    if match.occurrences >= Config.SUBSCRIPTION_CANDIDATE_THRESHOLD:
        match.status = "awaiting_confirm"
        awaiting_confirmation = True

    session.commit()

    return SubscriptionEvalResult(
        candidate_id=match.id,
        awaiting_confirmation=awaiting_confirmation,
        display_name=match.display_name,
        category_name=match.category_name,
        amount=float(match.amount),
        cadence=match.cadence,
    )


def get_awaiting_confirmation_candidates(session: Session, user_id: str) -> list[SubscriptionCandidate]:
    """Candidati in attesa di conferma Sì/No — usato dal comando on-demand
    /scova_abbonamenti per ripresentare anche quelli già pronti ma non ancora
    notificati (es. popolati dal backfill, che non manda messaggi Telegram)."""
    return (
        session.query(SubscriptionCandidate)
        .filter(
            SubscriptionCandidate.user_id == user_id,
            SubscriptionCandidate.status == "awaiting_confirm",
        )
        .order_by(SubscriptionCandidate.last_seen_at.desc())
        .all()
    )


def confirm_candidate(
    session: Session,
    storage: FinancialStorage,
    candidate_id: int,
) -> SubscriptionCandidate | None:
    """L'utente ha confermato (Sì): crea l'abbonamento reale tramite lo storage
    astratto e marca il candidate come `confirmed`.

    Se `storage.create_subscription()` fallisce (API esterna, es. Notion
    down/rate-limited), non lascia il candidate in uno stato inconsistente: torna
    `awaiting_confirm` così la conferma si può ripetere, invece di perdere il
    pattern rilevato (stesso principio di `category_matcher.confirm_promotion`).
    """
    candidate = session.query(SubscriptionCandidate).filter_by(id=candidate_id).first()
    if candidate is None:
        return None

    try:
        created = storage.create_subscription(
            candidate.display_name,
            amount=float(candidate.amount),
            last_billed=candidate.last_occurrence_date.isoformat(),
            sub_type=_CADENCE_TO_SUB_TYPE.get(candidate.cadence, "monthly"),
            category_name=candidate.category_name,
        )
        candidate.status = "confirmed"
        created_id = created.get("id") if isinstance(created, dict) else None
        candidate.promoted_subscription_id = created_id if isinstance(created_id, int) else None
        candidate.promoted_at = datetime.utcnow()
        session.commit()
    except Exception:
        session.rollback()
        candidate.status = "awaiting_confirm"
        session.commit()
        raise

    return candidate


def dismiss_candidate(session: Session, candidate_id: int) -> None:
    """L'utente ha rifiutato (No): decisione definitiva sui suoi soldi, non si
    richiede più conferma per questo pattern (a differenza della categorizzazione
    adattiva, qui un "No" non va reinterpretato come 'chiedimelo di nuovo dopo')."""
    candidate = session.query(SubscriptionCandidate).filter_by(id=candidate_id).first()
    if candidate is None:
        return
    candidate.status = "dismissed"
    session.commit()
