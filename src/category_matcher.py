"""
src/category_matcher.py — Categorizzazione adattiva delle spese.

Quando la categoria proposta dal parser LLM non matcha con sufficiente confidenza
nessuna categoria esistente dell'utente, la spesa resta su una categoria fallback
mentre il pattern (nome spesa normalizzato) viene tracciato in `category_candidates`.
Superata una soglia di occorrenze entro una finestra temporale, l'utente viene
interpellato (Sì/No): solo alla conferma il pattern viene promosso a categoria reale
tramite `FinancialStorage.create_category` — mai un accesso diretto a Notion/Postgres
da questo modulo, per rispettare l'astrazione del layer di storage (vedi CLAUDE.md).
Condiviso da bot Telegram (bot.py) e webapp (src/dashboard/app.py), nessuna duplicazione
di logica tra i due canali.
"""

import difflib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from config import Config
from src.expense_parser import match_category_string
from src.storage.base import FinancialStorage
from src.storage.models import CategoryCandidate, UserCategory
from src.user_store import UserStore

logger = logging.getLogger("financial_agent.category_matcher")

_NUMERIC_TOKEN_RE = re.compile(r"^\d+$")
_NON_WORD_RE = re.compile(r"[^\w\s]", re.UNICODE)
_MULTI_SPACE_RE = re.compile(r"\s+")


@dataclass
class MatchResult:
    """Esito della valutazione di categorizzazione per una spesa.

    `awaiting_confirmation`/`candidate_id`/`suggested_name` sono valorizzati solo
    quando la soglia di promozione è stata appena raggiunta: il chiamante (bot.py o
    src/dashboard/app.py) deve chiedere conferma Sì/No all'utente prima che la
    promozione avvenga davvero (vedi `confirm_promotion`/`decline_promotion`).
    """

    category_name: str
    score: float
    promoted: bool = False
    promoted_category_name: str | None = None
    awaiting_confirmation: bool = False
    candidate_id: int | None = None
    suggested_name: str | None = None


def normalize_event_name(raw_name: str) -> str:
    """Normalizza un nome spesa per il clustering dei pattern ricorrenti.

    Lowercase, rimozione punteggiatura, collasso spazi multipli, rimozione dei
    token puramente numerici isolati (es. "Pizza Mario 2" -> "pizza mario"),
    così occorrenze dello stesso evento con piccole variazioni testuali
    convergono sulla stessa chiave normalizzata.
    """
    if not raw_name:
        return ""
    cleaned = _NON_WORD_RE.sub("", raw_name.lower().strip())
    tokens = [t for t in _MULTI_SPACE_RE.split(cleaned) if t and not _NUMERIC_TOKEN_RE.match(t)]
    return " ".join(tokens)


def _capitalize_display_name(name: str) -> str:
    """Capitalizza parola per parola il nome da mostrare/creare come categoria.

    Evita il bug di `str.title()` sugli apostrofi (es. "mcdonald's" -> "Mcdonald's",
    non "Mcdonald'S" come produrrebbe `.title()`).
    """
    return " ".join(w[:1].upper() + w[1:] for w in name.strip().split() if w)


def compute_llm_confidence(category_from_llm: str | None, known_categories: list[str]) -> float:
    """Deriva una confidenza deterministica riusando il match esatto/fuzzy già
    testato in `expense_parser.match_category_string` (nessun campo LLM dedicato,
    vedi motivazione nel piano: self-reported confidence non affidabile)."""
    _, score = match_category_string(category_from_llm, known_categories)
    return score


def compute_historical_score(
    session: Session,
    user_id: str,
    normalized_name: str,
    cluster_cutoff: float | None = None,
    promotion_threshold: int | None = None,
) -> tuple[float, CategoryCandidate | None]:
    """Cerca tra i candidate esistenti dell'utente il pattern più simile.

    Match esatto sul nome normalizzato -> candidate trovato direttamente.
    Altrimenti clustering tra i candidate pending/promoted dell'utente, con due
    criteri alternativi:
    - fuzzy ratio (difflib.SequenceMatcher — NON sostituibile con rapidfuzz.fuzz.ratio:
      algoritmi diversi, verificato che divergono ~19% su coppie casuali e sempre nella
      direzione più permissiva su stringhe dissimili, es. "aperitivo"/"benzina" 0.13 vs
      0.25 — rapidfuzz ricalibrerebbe silenziosamente CATEGORY_CANDIDATE_CLUSTER_CUTOFF
      senza che nessuno l'abbia deciso) >= `cluster_cutoff` — cattura typo/variazioni
      minori;
    - containment di token — se l'insieme di parole del pattern più corto è
      sottoinsieme di quello del pattern più lungo (es. {netflix} ⊆ {netflix,
      mensile}), sono considerati lo stesso pattern anche se il ratio testuale è
      basso (0.636 per "netflix"/"netflix mensile", sotto il cutoff 0.8) — copre il
      caso comune di una parola descrittiva aggiunta/rimossa tra un'occorrenza e
      l'altra, che altrimenti frammenterebbe lo stesso pattern reale in più
      candidate, nessuno dei quali raggiunge mai la soglia di promozione da solo.
    Lo score è proporzionale a occorrenze/soglia di promozione, clampato a 1.0.
    """
    cluster_cutoff = Config.CATEGORY_CANDIDATE_CLUSTER_CUTOFF if cluster_cutoff is None else cluster_cutoff
    promotion_threshold = Config.CATEGORY_PROMOTION_THRESHOLD if promotion_threshold is None else promotion_threshold

    if not normalized_name:
        return 0.0, None

    exact = (
        session.query(CategoryCandidate)
        .filter_by(user_id=user_id, normalized_name=normalized_name)
        .first()
    )
    if exact:
        return min(exact.occurrences / promotion_threshold, 1.0), exact

    candidates = (
        session.query(CategoryCandidate)
        .filter(
            CategoryCandidate.user_id == user_id,
            CategoryCandidate.status.in_(("pending", "promoted", "awaiting_confirm")),
        )
        .all()
    )
    name_tokens = set(normalized_name.split())
    best_candidate: CategoryCandidate | None = None
    best_ratio = 0.0
    for candidate in candidates:
        candidate_tokens = set(candidate.normalized_name.split())
        is_subset_match = bool(
            name_tokens and candidate_tokens
            and (name_tokens <= candidate_tokens or candidate_tokens <= name_tokens)
        )
        if is_subset_match:
            # Containment è una decisione definitiva (parola descrittiva in più/meno
            # rispetto a un pattern già tracciato) — si accetta subito, non serve
            # confrontare il ratio con gli altri candidate.
            return min(candidate.occurrences / promotion_threshold, 1.0), candidate

        ratio = difflib.SequenceMatcher(None, normalized_name, candidate.normalized_name).ratio()
        if ratio > best_ratio:
            best_ratio, best_candidate = ratio, candidate

    if best_candidate is not None and best_ratio >= cluster_cutoff:
        return min(best_candidate.occurrences / promotion_threshold, 1.0), best_candidate

    return 0.0, None


def score_categorization(
    llm_confidence: float,
    historical_score: float,
    weight_llm: float | None = None,
    weight_historical: float | None = None,
) -> float:
    """Combinazione lineare pesata dei due segnali, clampata a [0, 1]."""
    weight_llm = Config.CATEGORY_MATCH_WEIGHT_LLM if weight_llm is None else weight_llm
    weight_historical = Config.CATEGORY_MATCH_WEIGHT_HISTORY if weight_historical is None else weight_historical
    combined = llm_confidence * weight_llm + historical_score * weight_historical
    return max(0.0, min(1.0, combined))


def _generate_promoted_category_description(display_name: str) -> str | None:
    """Genera una descrizione comportamentale una tantum per una categoria
    promossa automaticamente da un pattern ricorrente (nessun testo scritto
    dall'utente da cui partire, solo il nome — vedi
    `MistralClient.generate_category_description_from_name`).

    Best-effort: mai bloccare la promozione per un errore Mistral, la categoria
    viene comunque creata senza descrizione se la generazione fallisce.
    """
    try:
        from src.mistral_client import MistralClient
        return MistralClient().generate_category_description_from_name(display_name)
    except Exception as e:
        logger.warning(
            "category_description_generation_failed",
            extra={
                "domain": "usage", "event": "category_description_generation_failed",
                "meta": {"error_type": type(e).__name__},
            },
        )
        return None


def _promote_candidate(
    session: Session,
    storage: FinancialStorage,
    user_store: UserStore,
    user_id: str,
    candidate: CategoryCandidate,
) -> str:
    """Promuove un candidate a categoria reale tramite il layer di storage astratto.

    Allinea subito il mirror locale `user_categories` (via `upsert_user_categories`)
    indipendentemente dal backend: per Notion la creazione tocca solo l'API esterna,
    senza questo allineamento la nuova categoria resterebbe invisibile al parser
    fino al sync notturno. Il nome è sempre capitalizzato parola per parola, mai il
    testo grezzo dell'ultima occorrenza (che potrebbe essere tutto minuscolo).

    Può sollevare (chiamata API storage esterna, es. Notion) — il chiamante
    (`confirm_promotion`) è responsabile della gestione dell'errore.
    """
    display_name = _capitalize_display_name(candidate.display_name)
    description_summary = _generate_promoted_category_description(display_name)

    created = storage.create_category(display_name, description_summary=description_summary)
    notion_page_id = created.get("id") if isinstance(created.get("id"), str) else None

    category_payload = {"name": display_name}
    if notion_page_id:
        category_payload["notion_page_id"] = notion_page_id
    if description_summary:
        category_payload["description_summary"] = description_summary
    user_store.upsert_user_categories(user_id, [category_payload])

    user_category = (
        session.query(UserCategory)
        .filter_by(user_id=user_id, name=display_name)
        .first()
    )
    candidate.display_name = display_name
    candidate.status = "promoted"
    candidate.promoted_category_id = user_category.id if user_category else None
    candidate.promoted_at = datetime.utcnow()

    return display_name


def confirm_promotion(
    session: Session,
    storage: FinancialStorage,
    user_store: UserStore,
    candidate_id: int,
) -> MatchResult:
    """L'utente ha confermato (Sì) la creazione della categoria suggerita.

    Se `storage.create_category()` fallisce (es. Notion API rate-limited/down), non
    propaga l'eccezione: il candidate torna a `status="pending"` (le occorrenze
    restano oltre soglia) così la prossima occorrenza dello stesso pattern rifà la
    richiesta di conferma automaticamente, invece di rompere il flusso di conferma
    spesa in corso per l'utente.
    """
    candidate = session.query(CategoryCandidate).filter_by(id=candidate_id).first()
    if candidate is None:
        return MatchResult(category_name=Config.CATEGORY_FALLBACK_NAME, score=0.0)

    try:
        promoted_category_name = _promote_candidate(session, storage, user_store, candidate.user_id, candidate)
        session.commit()
    except Exception as e:
        session.rollback()
        candidate.status = "pending"
        session.commit()
        logger.error(
            "category_promotion_failed",
            extra={
                "domain": "usage",
                "event": "category_promotion_failed",
                "chat_id": candidate.user_id,
                "meta": {"candidate_id": candidate.id, "error_type": type(e).__name__},
            },
        )
        return MatchResult(category_name=candidate.display_name, score=0.0)

    logger.info(
        "category_promoted",
        extra={
            "domain": "usage",
            "event": "category_promoted",
            "chat_id": candidate.user_id,
            "meta": {"candidate_id": candidate.id},
        },
    )
    return MatchResult(
        category_name=promoted_category_name,
        score=1.0,
        promoted=True,
        promoted_category_name=promoted_category_name,
    )


def decline_promotion(session: Session, candidate_id: int) -> None:
    """L'utente ha rifiutato (No) la creazione della categoria suggerita.

    Azzera il contatore occorrenze: il pattern deve ripresentarsi altre
    `CATEGORY_PROMOTION_THRESHOLD` volte da capo per essere richiesto di nuovo,
    invece di richiedere conferma a ogni occorrenza successiva.
    """
    candidate = session.query(CategoryCandidate).filter_by(id=candidate_id).first()
    if candidate is None:
        return
    candidate.occurrences = 0
    candidate.status = "pending"
    session.commit()
    logger.info(
        "category_promotion_declined",
        extra={
            "domain": "usage",
            "event": "category_promotion_declined",
            "chat_id": candidate.user_id,
            "meta": {"candidate_id": candidate.id},
        },
    )


def evaluate_and_track(
    session: Session,
    storage: FinancialStorage,
    user_store: UserStore,
    user_id: str,
    raw_name: str,
    category_from_llm: str | None,
    known_categories: list[str],
    fallback_category_name: str | None = None,
) -> MatchResult:
    """Entry point unico chiamato da bot.py e src/dashboard/app.py dopo il parsing
    di una spesa.

    Se la categoria proposta matcha una categoria esistente con confidenza >=
    soglia, viene accettata invariata (comportamento identico a prima del feature).
    Altrimenti la spesa resta sulla categoria fallback mentre l'occorrenza del
    pattern viene tracciata; superata la soglia di promozione, l'utente viene
    interpellato (Sì/No) — vedi `MatchResult.awaiting_confirmation` — e solo alla
    conferma esplicita (`confirm_promotion`) il pattern diventa una categoria reale.
    """
    fallback_category_name = fallback_category_name or Config.CATEGORY_FALLBACK_NAME

    # Gate primario: se la categoria proposta matcha (esatto o fuzzy) una categoria
    # ESISTENTE con confidenza sufficiente, si accetta subito — comportamento invariato
    # rispetto a oggi. Lo storico non deve poter "diluire" questo segnale: senza questo
    # gate separato, una spesa mai vista prima (storico=0) con match perfetto (LLM=1.0)
    # otterrebbe uno score combinato 50/50 pari a 0.5, sempre sotto soglia di default —
    # il che romperebbe la categorizzazione per ogni spesa nuova.
    #
    # Eccezione: il parser sceglie SEMPRE una categoria dalla lista nota (vincolo nel
    # system prompt), quindi per una spesa che non riconosce propone il fallback stesso
    # ("Altro") — che è a tutti gli effetti un match esatto con confidenza 1.0. Senza
    # questa eccezione il gate primario intercetterebbe ogni fallback prima che il
    # tracking delle occorrenze abbia la possibilità di scattare, rendendo la promozione
    # automatica irraggiungibile nella pratica.
    matched_name, llm_confidence = match_category_string(category_from_llm, known_categories)
    is_fallback_match = matched_name is not None and matched_name.lower() == fallback_category_name.lower()
    if matched_name is not None and not is_fallback_match and llm_confidence >= Config.CATEGORY_MATCH_THRESHOLD:
        return MatchResult(category_name=matched_name, score=llm_confidence)

    normalized = normalize_event_name(raw_name)
    now = datetime.utcnow()

    historical_score, candidate = compute_historical_score(session, user_id, normalized)

    resolved_fallback = (
        fallback_category_name
        if fallback_category_name in known_categories
        else (known_categories[0] if known_categories else fallback_category_name)
    )

    if candidate is not None and candidate.status == "promoted":
        return MatchResult(category_name=candidate.display_name, score=1.0)

    if candidate is not None and candidate.status == "awaiting_confirm":
        # Promozione già proposta, in attesa della risposta Sì/No dell'utente — non
        # richiedere di nuovo né incrementare le occorrenze nel frattempo.
        return MatchResult(category_name=resolved_fallback, score=historical_score)

    # Sotto soglia: lo score combinato serve solo da telemetria/osservabilità
    # (salvato su candidate.last_score), non da ulteriore gate di accettazione — evita
    # di accettare `category_from_llm` grezzo (non presente in known_categories) solo
    # perché lo storico ha fatto crescere il punteggio combinato.
    score = score_categorization(llm_confidence, historical_score)

    window = timedelta(days=Config.CATEGORY_PROMOTION_WINDOW_DAYS)
    if candidate is None:
        candidate = CategoryCandidate(
            user_id=user_id,
            normalized_name=normalized,
            display_name=raw_name,
            occurrences=1,
            first_seen_at=now,
            last_seen_at=now,
            last_score=score,
            status="pending",
        )
        session.add(candidate)
    else:
        if now - candidate.last_seen_at > window:
            candidate.occurrences = 1
            candidate.first_seen_at = now
        else:
            candidate.occurrences += 1
        candidate.last_seen_at = now
        candidate.last_score = score
        candidate.display_name = raw_name

    # Commit dell'incremento prima di valutare la soglia — se poi la promozione viene
    # rifiutata o fallisce, il conteggio fin qui resta comunque salvato.
    session.commit()

    awaiting_confirmation = False
    suggested_name = None
    if candidate.occurrences >= Config.CATEGORY_PROMOTION_THRESHOLD:
        candidate.status = "awaiting_confirm"
        session.commit()
        awaiting_confirmation = True
        suggested_name = _capitalize_display_name(candidate.display_name)

    logger.info(
        "category_candidate_evaluated",
        extra={
            "domain": "usage",
            "event": "category_awaiting_confirm" if awaiting_confirmation else "category_candidate_tracked",
            "chat_id": user_id,
            "meta": {
                "candidate_id": candidate.id,
                "occurrences": candidate.occurrences,
                "score": round(score, 3),
                "threshold": Config.CATEGORY_MATCH_THRESHOLD,
            },
        },
    )

    return MatchResult(
        category_name=resolved_fallback,
        score=score,
        awaiting_confirmation=awaiting_confirmation,
        candidate_id=candidate.id if awaiting_confirmation else None,
        suggested_name=suggested_name,
    )
