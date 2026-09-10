"""
src/expense_label_normalizer.py — Normalizzazione delle voci di spesa.

Metadato di sola aggregazione per i grafici (Analytics -> "Voci"): raggruppa varianti
testuali della stessa voce ("coca", "coca cola", "coca-cola") sotto un'unica ancora
per utente+categoria (`ExpenseLabelCluster`). La descrizione originale della spesa
(`Expense.name`) non viene mai toccata né sostituita — l'ancora è solo la chiave di
raggruppamento usata dai grafici, mai mostrata al posto della descrizione dell'utente.

Design (vedi discussione — nessuna interazione utente, mai chiesta conferma):
- Ogni cluster è scoperto solo tra le spese con lo stesso `category_id` (guardrail):
  lo stesso testo in categorie diverse (es. "Coca Cola" al supermercato vs in
  discoteca) resta in due cluster separati by design, non è un errore da correggere.
- Una nuova spesa si confronta SOLO con l'ancora di ciascun cluster candidato, mai con
  gli altri membri già uniti — previene la "deriva a catena" (A si aggancia a B, poi C
  si aggancia a B pur non assomigliando ad A).
- L'ancora si aggiorna in tempo reale alla variante testuale più frequente vista finora
  (`variant_counts`, incrementato a ogni nuovo membro) — nessun job di audit periodico.

Correzione manuale (aggiunta 2026-09-03): il matching è conservativo ma non infallibile,
e l'utente può correggerlo dal grafico Analytics con "Unisci" e "Dividi". Perché la
correzione sia durevole non basta riassegnare le spese esistenti: la spesa successiva
con lo stesso testo verrebbe ri-accorpata dal fuzzy (`partial_ratio("ape", "ape 50
tagliando")` = 100). Ogni correzione scrive quindi delle regole in
`ExpenseLabelOverride`, consultate in testa a `assign_label_cluster` PRIMA di calcolare
qualunque similarità; e l'ancora scelta dall'utente viene marcata `anchor_locked` così
`_pick_anchor` non la sostituisce più. Il guardrail di categoria resta intatto: sia le
regole sia il merge sono scopati alla singola `category_id`.

Nota: NON riusa `category_matcher.normalize_event_name` — quella funzione rimuove i
token puramente numerici isolati (corretto per il suo scopo: "Pizza Mario 2" ->
"Pizza Mario", il "2" è rumore). Per noi un numero può essere il segnale che
DISAMBIGUA due voci simili (es. "Ape" vs "Ape 50" — scooter, non l'abbreviazione di
"Aperitivo"): rimuoverlo riaprirebbe esattamente il falso positivo che l'ancora fissa
+ guardrail di categoria sono nati per evitare. Qui si normalizza solo lowercase/spazi.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime

from rapidfuzz import fuzz
from sqlalchemy import func
from sqlalchemy.orm import Session

from config import Config
from src.storage.models import Expense, ExpenseLabelCluster, ExpenseLabelOverride

logger = logging.getLogger("financial_agent.expense_label_normalizer")

_MULTI_SPACE_RE = re.compile(r"\s+")

# Limiti di una singola correzione manuale: gli endpoint li importano da qui invece
# di ridichiararli, così restano un solo numero da cambiare.
MAX_MERGE_SOURCES = 20
MAX_SPLIT_VARIANTS = 50


class LabelClusterError(Exception):
    """Errore applicativo di una correzione manuale (merge/split).

    `code` è una chiave stabile che il layer HTTP mappa su messaggio e status:
    `cluster_not_found`, `category_mismatch`, `invalid_anchor`, `invalid_variants`,
    `split_all_variants`. Il messaggio non contiene mai testo scritto dall'utente.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _light_normalize(raw_name: str) -> str:
    """Lowercase + collasso spazi multipli. Non tocca cifre né punteggiatura: sono
    parte del segnale del confronto, non rumore da eliminare (vedi nota nel docstring
    del modulo)."""
    if not raw_name:
        return ""
    return _MULTI_SPACE_RE.sub(" ", raw_name.strip().lower())


def _pick_anchor(variants: dict[str, int]) -> str:
    """Sceglie l'ancora tra le varianti: più frequente vince; a parità di
    frequenza, la più corta — tende a essere la forma "pulita" del nome, non
    una nota personale aggiunta (es. "Coca Cola" preferita a "Coca cola
    famila", entrambe viste una sola volta)."""
    max_count = max(variants.values())
    top = [v for v, count in variants.items() if count == max_count]
    return min(top, key=len)


@dataclass
class LabelClusterResult:
    """Esito dell'assegnazione di una spesa a un cluster di normalizzazione."""

    cluster_id: int
    anchor_text: str
    created: bool


@dataclass
class MergeResult:
    """Esito di un'unione manuale di cluster."""

    target_cluster_id: int
    absorbed_cluster_ids: list[int]
    moved_expenses: int
    anchor_text: str


@dataclass
class SplitResult:
    """Esito di una separazione manuale di varianti da un cluster."""

    new_cluster_id: int
    anchor_text: str
    moved_expenses: int


def lookup_override(
    session: Session, user_id: str, raw_name: str, category_id: int | None
) -> int | None:
    """Cluster forzato dall'utente per questo testo, o None se non c'è una regola.

    La chiave è `_light_normalize(raw_name)`: la regola scritta su "Ape 50 tagliando"
    vale anche per "ape 50  tagliando" scritto dopo. Lo scoping include `category_id`,
    quindi una regola registrata in una categoria non si applica in un'altra —
    coerente con il guardrail del matching automatico.
    """
    normalized = _light_normalize(raw_name)
    row = (
        session.query(ExpenseLabelOverride)
        .filter_by(user_id=user_id, category_id=category_id, normalized_text=normalized)
        .first()
    )
    return row.cluster_id if row else None


def _upsert_override(
    session: Session,
    user_id: str,
    category_id: int | None,
    raw_name: str,
    cluster_id: int,
    source: str,
) -> None:
    """Crea o riscrive la regola che lega un testo a un cluster."""
    normalized = _light_normalize(raw_name)
    row = (
        session.query(ExpenseLabelOverride)
        .filter_by(user_id=user_id, category_id=category_id, normalized_text=normalized)
        .first()
    )
    if row is not None:
        row.cluster_id = cluster_id
        row.source = source
        row.updated_at = datetime.utcnow()
        return
    session.add(
        ExpenseLabelOverride(
            user_id=user_id,
            category_id=category_id,
            normalized_text=normalized,
            cluster_id=cluster_id,
            source=source,
        )
    )


def _attach_to_cluster(
    session: Session, cluster: ExpenseLabelCluster, raw_name: str
) -> LabelClusterResult:
    """Aggancia una spesa a un cluster esistente, aggiornando conteggi e ancora.

    L'ancora viene ricalcolata solo se non è bloccata: `anchor_locked` significa che
    l'utente l'ha scelta esplicitamente correggendo il raggruppamento, e nessuna
    variante più frequente deve sovrascriverla.
    """
    variants = dict(cluster.variant_counts or {})
    variants[raw_name] = variants.get(raw_name, 0) + 1
    cluster.variant_counts = variants
    if not cluster.anchor_locked:
        top_variant = _pick_anchor(variants)
        if top_variant != cluster.anchor_text:
            cluster.anchor_text = top_variant
    cluster.updated_at = datetime.utcnow()
    session.flush()
    return LabelClusterResult(
        cluster_id=cluster.id, anchor_text=cluster.anchor_text, created=False
    )


def assign_label_cluster(
    session: Session,
    user_id: str,
    raw_name: str,
    category_id: int | None,
    threshold: float | None = None,
) -> LabelClusterResult:
    """Assegna una spesa al suo cluster di normalizzazione, creandone uno nuovo se serve.

    `raw_name` è la descrizione così come scritta dall'utente (mai modificata a valle
    di questa funzione). Il confronto avviene su `_light_normalize(raw_name)` contro
    `_light_normalize(anchor_text)` di ciascun cluster candidato — la normalizzazione
    è usata solo per calcolare il punteggio, mai per decidere cosa salvare come ancora.

    Non solleva mai eccezioni per input vuoto/None: `anchor_text` è NOT NULL, quindi
    `None` viene trattato come stringa vuota prima di tutto il resto — il cluster viene
    comunque creato (nessun testo su cui fare matching utile, ma la spesa deve comunque
    ricevere un cluster).

    Usa `session.flush()`, non `commit()`: questa funzione viene chiamata dentro la
    stessa transazione che crea la spesa (`PostgresStorage.create_expense`) — il
    cluster e la spesa devono diventare visibili insieme, con un solo commit finale
    a carico del chiamante. `flush()` assegna comunque l'id al cluster appena creato.
    """
    raw_name = raw_name or ""
    threshold = Config.EXPENSE_LABEL_MATCH_THRESHOLD if threshold is None else threshold
    normalized_new = _light_normalize(raw_name)

    # Una correzione manuale dell'utente batte sempre il fuzzy: è l'unico modo per cui
    # "Ape 50 tagliando", separata a mano da "Ape", non ci ricada al prossimo inserimento.
    forced_id = lookup_override(session, user_id, raw_name, category_id)
    if forced_id is not None:
        forced = (
            session.query(ExpenseLabelCluster)
            .filter_by(id=forced_id, user_id=user_id)
            .first()
        )
        if forced is not None:  # difensivo: regola orfana -> si ricade sul fuzzy
            logger.info(
                "expense_label_cluster_override_hit",
                extra={
                    "domain": "usage",
                    "event": "expense_label_cluster_override_hit",
                    "chat_id": user_id,
                    "meta": {"cluster_id": forced.id},
                },
            )
            return _attach_to_cluster(session, forced, raw_name)

    candidates = (
        session.query(ExpenseLabelCluster)
        .filter_by(user_id=user_id, category_id=category_id)
        .all()
    )

    best_cluster: ExpenseLabelCluster | None = None
    best_score = 0.0
    if normalized_new:
        for cluster in candidates:
            score = fuzz.partial_ratio(normalized_new, _light_normalize(cluster.anchor_text))
            if score > best_score:
                best_cluster, best_score = cluster, score
    else:
        # Nome vuoto: partial_ratio("", x) darebbe 100 e unirebbe a un cluster
        # arbitrario (per questo il ramo sopra lo evita), ma niente impedisce che
        # esista già un cluster "vuoto" per questo utente+categoria — riusarlo invece
        # di aprirne uno nuovo a ogni spesa senza nome.
        for cluster in candidates:
            if cluster.anchor_text == "":
                best_cluster, best_score = cluster, threshold
                break

    if best_cluster is not None and best_score >= threshold:
        result = _attach_to_cluster(session, best_cluster, raw_name)
        logger.info(
            "expense_label_cluster_matched",
            extra={
                "domain": "usage",
                "event": "expense_label_cluster_matched",
                "chat_id": user_id,
                "meta": {"cluster_id": best_cluster.id, "score": round(best_score, 1)},
            },
        )
        return result

    cluster = ExpenseLabelCluster(
        user_id=user_id,
        category_id=category_id,
        anchor_text=raw_name,
        variant_counts={raw_name: 1},
    )
    session.add(cluster)
    session.flush()

    logger.info(
        "expense_label_cluster_created",
        extra={
            "domain": "usage",
            "event": "expense_label_cluster_created",
            "chat_id": user_id,
            "meta": {"cluster_id": cluster.id},
        },
    )
    return LabelClusterResult(cluster_id=cluster.id, anchor_text=cluster.anchor_text, created=True)


def _forms_in_cluster(session: Session, user_id: str, cluster_id: int) -> dict[str, int]:
    """Grafie realmente presenti tra le spese del cluster, con quante spese ciascuna.

    È la fonte di verità delle correzioni manuali. `variant_counts` serve al matching
    ma resta indietro rispetto alla realtà: rinominare, spostare di categoria o
    cancellare una spesa non lo aggiorna. L'utente sceglie da ciò che vede a schermo,
    cioè dalle spese; validare contro `variant_counts` faceva fallire correzioni
    perfettamente legittime con "questa voce non esiste più".
    """
    rows = (
        session.query(Expense.name, func.count(Expense.id))
        .filter(Expense.user_id == user_id, Expense.label_cluster_id == cluster_id)
        .group_by(Expense.name)
        .all()
    )
    return {name: int(count) for name, count in rows}


def _resync_variant_counts(
    session: Session, user_id: str, cluster: ExpenseLabelCluster
) -> None:
    """Riallinea `variant_counts` e l'ancora alle spese realmente nel cluster.

    Chiamata dopo ogni correzione manuale: è il punto in cui la deriva accumulata
    da rinomine e cancellazioni viene sanata, invece di restare lì a far fallire
    l'operazione successiva.
    """
    counts = _forms_in_cluster(session, user_id, cluster.id)
    cluster.variant_counts = counts
    if counts and not cluster.anchor_locked:
        cluster.anchor_text = _pick_anchor(counts)
    elif counts and cluster.anchor_text not in counts:
        # L'ancora bloccata non ha più spese che la usano: il blocco non ha più senso.
        cluster.anchor_locked = False
        cluster.anchor_text = _pick_anchor(counts)
    cluster.updated_at = datetime.utcnow()


def resync_cluster(session: Session, user_id: str, cluster_id: int) -> None:
    """Riallinea un cluster alle sue spese dopo una cancellazione o una rinomina.

    Va chiamata dal layer storage quando un cluster perde una spesa: senza,
    `variant_counts` e quindi l'ancora restano fermi alla situazione precedente e il
    grafico può mostrare un'etichetta che non corrisponde più a nessuna spesa.
    Un cluster rimasto senza spese non viene toccato: non compare in nessuna
    schermata e cancellarlo qui complicherebbe la transazione del chiamante.
    """
    cluster = (
        session.query(ExpenseLabelCluster)
        .filter_by(id=cluster_id, user_id=user_id)
        .first()
    )
    if cluster is None:
        return
    if not _forms_in_cluster(session, user_id, cluster_id):
        return
    _resync_variant_counts(session, user_id, cluster)


def _own_cluster(
    session: Session, user_id: str, cluster_id: int
) -> ExpenseLabelCluster | None:
    """Carica un cluster verificando esplicitamente la proprietà.

    Il filtro applicativo su `user_id` resta obbligatorio anche con la RLS attiva:
    è la difesa che vale identica su SQLite (dev/test), dove la RLS è un no-op.
    """
    return (
        session.query(ExpenseLabelCluster)
        .filter_by(id=cluster_id, user_id=user_id)
        .first()
    )


def merge_clusters(
    session: Session,
    user_id: str,
    target_cluster_id: int,
    source_cluster_ids: list[int],
    anchor_text: str | None = None,
    source_variants: dict[int, list[str]] | None = None,
) -> MergeResult:
    """Unisce uno o più cluster nel cluster di destinazione (correzione manuale).

    Usata quando il matching automatico ha lasciato separate voci che per l'utente
    sono la stessa cosa. Oltre a spostare le spese, scrive una regola in
    `ExpenseLabelOverride` per ogni variante del gruppo risultante: senza quelle
    regole il prossimo inserimento potrebbe ricreare la separazione appena corretta.

    `anchor_text`, se passato, deve essere una delle varianti già presenti nei cluster
    coinvolti — non è mai testo libero — e viene bloccata (`anchor_locked`) perché è
    una scelta esplicita dell'utente.

    Con `source_variants` l'unione può essere parziale: dal gruppo indicato si
    spostano solo quelle voci e il gruppo sopravvive con le rimanenti. L'unità resta
    la voce (forma normalizzata), mai la singola spesa: due spese scritte allo stesso
    modo finiscono sempre insieme, altrimenti nessuna regola potrebbe descriverle e
    il prossimo inserimento romperebbe la separazione.

    Idempotente: i cluster sorgente già assorbiti (id inesistenti) vengono ignorati
    senza errore, così un doppio invio dalla UI non produce un fallimento.

    Args:
        session: sessione già associata all'utente (RLS) dal chiamante.
        user_id: proprietario dei cluster.
        target_cluster_id: cluster che sopravvive.
        source_cluster_ids: cluster da cui prendere le voci.
        anchor_text: etichetta scelta dall'utente per il gruppo risultante.
        source_variants: per ciascun cluster sorgente, le voci da spostare. I cluster
            assenti dalla mappa vengono assorbiti per intero e cancellati.

    Returns:
        MergeResult con id assorbiti, spese spostate ed etichetta finale.

    Raises:
        LabelClusterError: target inesistente (`cluster_not_found`), sorgente di
            un'altra categoria (`category_mismatch`), ancora non tra le varianti
            (`invalid_anchor`), voci selezionate inesistenti (`invalid_variants`).
    """
    target = _own_cluster(session, user_id, target_cluster_id)
    if target is None:
        raise LabelClusterError("cluster_not_found", "Voce non trovata")

    source_ids = [cid for cid in dict.fromkeys(source_cluster_ids) if cid != target_cluster_id]
    sources = (
        session.query(ExpenseLabelCluster)
        .filter(
            ExpenseLabelCluster.user_id == user_id,
            ExpenseLabelCluster.id.in_(source_ids),
        )
        .all()
        if source_ids
        else []
    )
    for source in sources:
        if source.category_id != target.category_id:
            raise LabelClusterError(
                "category_mismatch", "Puoi unire solo voci della stessa categoria"
            )

    # Per ogni sorgente: quali forme grezze si spostano e quali restano.
    taken: dict[int, dict[str, int]] = {}
    kept: dict[int, dict[str, int]] = {}
    for source in sources:
        # Spese reali, non `variant_counts`: quest'ultimo resta indietro dopo
        # rinomine e cancellazioni, e farebbe fallire correzioni legittime.
        counts = _forms_in_cluster(session, user_id, source.id)
        wanted = (source_variants or {}).get(source.id)
        if wanted is None:
            taken[source.id], kept[source.id] = counts, {}
            continue
        by_normalized: dict[str, list[str]] = {}
        for variant in counts:
            by_normalized.setdefault(_light_normalize(variant), []).append(variant)
        wanted_norm = list(dict.fromkeys(_light_normalize(v) for v in wanted))
        if not wanted_norm or any(norm not in by_normalized for norm in wanted_norm):
            raise LabelClusterError(
                "invalid_variants",
                "Alcune voci selezionate non esistono più: ricarica la pagina",
            )
        moved_forms = {raw for norm in wanted_norm for raw in by_normalized[norm]}
        taken[source.id] = {v: c for v, c in counts.items() if v in moved_forms}
        kept[source.id] = {v: c for v, c in counts.items() if v not in moved_forms}

    merged_variants: dict[str, int] = _forms_in_cluster(session, user_id, target.id)
    for source in sources:
        for variant, count in taken[source.id].items():
            merged_variants[variant] = merged_variants.get(variant, 0) + count

    if anchor_text is not None:
        if anchor_text not in merged_variants:
            raise LabelClusterError(
                "invalid_anchor", "L'etichetta scelta non è più disponibile"
            )
        target.anchor_text = anchor_text
        target.anchor_locked = True

    # Assorbiti = svuotati del tutto; quelli con voci rimaste sopravvivono.
    absorbed = [source for source in sources if not kept[source.id]]
    absorbed_ids = [source.id for source in absorbed]
    moved_expenses = 0

    for source in sources:
        if kept[source.id]:
            # Unione parziale: si spostano solo le grafie scelte.
            moved_expenses += (
                session.query(Expense)
                .filter(
                    Expense.user_id == user_id,
                    Expense.label_cluster_id == source.id,
                    Expense.name.in_(list(taken[source.id])),
                )
                .update({"label_cluster_id": target.id}, synchronize_session=False)
            )
        else:
            # Assorbimento totale: si sposta per cluster, non per nome. Filtrare per
            # nome lascerebbe indietro le spese la cui grafia non risulta tra quelle
            # note, e il cluster viene cancellato subito dopo: resterebbero appese.
            moved_expenses += (
                session.query(Expense)
                .filter(
                    Expense.user_id == user_id,
                    Expense.label_cluster_id == source.id,
                )
                .update({"label_cluster_id": target.id}, synchronize_session=False)
            )
    session.flush()

    for source in sources:
        if kept[source.id]:
            _resync_variant_counts(session, user_id, source)

    if absorbed_ids:
        # Le regole che puntavano ai cluster assorbiti vanno ripuntate a mano: su
        # SQLite le foreign key non sono attive di default, quindi la CASCADE del
        # DB non è una garanzia su cui appoggiarsi.
        stale = (
            session.query(ExpenseLabelOverride)
            .filter(
                ExpenseLabelOverride.user_id == user_id,
                ExpenseLabelOverride.cluster_id.in_(absorbed_ids),
            )
            .all()
        )
        for row in stale:
            session.delete(row)
        session.flush()

    # Una regola per ogni variante del gruppo risultante: è ciò che rende durevole la
    # correzione anche quando l'ancora cambia o nasce un cluster simile in mezzo.
    for variant in merged_variants:
        _upsert_override(
            session, user_id, target.category_id, variant, target.id, "merge"
        )
    # Le voci rimaste in un gruppo parzialmente svuotato vanno ancorate lì, altrimenti
    # il fuzzy potrebbe portarle nel gruppo di destinazione appena arricchito.
    for source in sources:
        for variant in kept[source.id]:
            _upsert_override(
                session, user_id, source.category_id, variant, source.id, "merge"
            )

    for source in absorbed:
        session.delete(source)
    session.flush()

    # Conteggi e ancora del gruppo di destinazione ricalcolati dalle spese: sana
    # anche la deriva ereditata da rinomine e cancellazioni precedenti.
    was_locked = target.anchor_locked
    chosen_anchor = target.anchor_text
    _resync_variant_counts(session, user_id, target)
    if was_locked:
        target.anchor_text = chosen_anchor
        target.anchor_locked = True
    session.flush()

    logger.info(
        "expense_label_clusters_merged",
        extra={
            "domain": "usage",
            "event": "expense_label_clusters_merged",
            "chat_id": user_id,
            "meta": {
                "target_cluster_id": target.id,
                "absorbed": len(absorbed_ids),
                "moved_expenses": moved_expenses,
                "anchor_locked": bool(target.anchor_locked),
            },
        },
    )
    return MergeResult(
        target_cluster_id=target.id,
        absorbed_cluster_ids=absorbed_ids,
        moved_expenses=moved_expenses,
        anchor_text=target.anchor_text,
    )


def split_variants(
    session: Session,
    user_id: str,
    cluster_id: int,
    variants: list[str],
    new_anchor: str | None = None,
) -> SplitResult:
    """Separa alcune varianti testuali in un cluster nuovo (correzione manuale).

    Usata quando il matching ha unito voci che non c'entrano tra loro (il caso tipico
    è `partial_ratio("ape", "ape 50 tagliando")` = 100). L'unità di separazione è la
    variante testuale, non la singola spesa: tutte le spese con quel nome esatto si
    spostano insieme, e continueranno a stare insieme anche in futuro.

    Scrive regole su ENTRAMBI i lati — varianti spostate verso il cluster nuovo e
    varianti rimaste verso quello di partenza. Il secondo lato non è ridondante: senza
    di esso il prossimo inserimento resterebbe in balia del fuzzy, che assegna 100 a
    entrambi i candidati e potrebbe rifondere ciò che l'utente ha appena separato.

    Args:
        session: sessione già associata all'utente (RLS) dal chiamante.
        user_id: proprietario del cluster.
        cluster_id: cluster da cui separare.
        variants: varianti testuali da spostare (chiavi di `variant_counts`).
        new_anchor: etichetta del nuovo gruppo, deve essere una delle `variants`.

    Returns:
        SplitResult con il nuovo cluster e il numero di spese spostate.

    Raises:
        LabelClusterError: cluster inesistente (`cluster_not_found`), varianti
            sconosciute (`invalid_variants`), tutte le varianti selezionate
            (`split_all_variants`), ancora non tra le varianti (`invalid_anchor`).
    """
    cluster = _own_cluster(session, user_id, cluster_id)
    if cluster is None:
        raise LabelClusterError("cluster_not_found", "Voce non trovata")

    # Si parte dalle spese reali, non da `variant_counts`: è quello che l'utente ha
    # visto nel pannello, ed è l'unico dato che non è mai in ritardo sulla realtà.
    existing = _forms_in_cluster(session, user_id, cluster.id)
    # L'unità di separazione è la forma NORMALIZZATA, non il testo grezzo: "Coca Cola"
    # e "coca  cola" sono la stessa voce per l'utente e condividono la chiave di
    # override. Trattarle separatamente farebbe sovrascrivere una regola con l'altra,
    # e la correzione si disferebbe al primo inserimento successivo.
    by_normalized: dict[str, list[str]] = {}
    for variant in existing:
        by_normalized.setdefault(_light_normalize(variant), []).append(variant)

    wanted_norm = list(dict.fromkeys(_light_normalize(variant) for variant in variants))
    if not wanted_norm or any(norm not in by_normalized for norm in wanted_norm):
        raise LabelClusterError(
            "invalid_variants",
            "Alcune voci selezionate non esistono più: ricarica la pagina",
        )
    if len(wanted_norm) == len(by_normalized):
        raise LabelClusterError(
            "split_all_variants", "Lascia almeno una voce nel gruppo di partenza"
        )
    if new_anchor is not None and _light_normalize(new_anchor) not in wanted_norm:
        raise LabelClusterError(
            "invalid_anchor", "L'etichetta scelta non è più disponibile"
        )

    wanted = [raw for norm in wanted_norm for raw in by_normalized[norm]]
    moved_counts = {variant: existing[variant] for variant in wanted}
    remaining = {v: c for v, c in existing.items() if v not in moved_counts}

    # L'ancora è sempre una variante realmente presente: se il client ne passa una
    # scritta in modo leggermente diverso si usa la forma grezza più frequente.
    if new_anchor is not None and new_anchor not in moved_counts:
        same_form = {v: c for v, c in moved_counts.items()
                     if _light_normalize(v) == _light_normalize(new_anchor)}
        new_anchor = _pick_anchor(same_form)

    new_cluster = ExpenseLabelCluster(
        user_id=user_id,
        category_id=cluster.category_id,
        anchor_text=new_anchor if new_anchor is not None else _pick_anchor(moved_counts),
        variant_counts=moved_counts,
        anchor_locked=True,
    )
    session.add(new_cluster)
    session.flush()

    moved_expenses = (
        session.query(Expense)
        .filter(
            Expense.user_id == user_id,
            Expense.label_cluster_id == cluster.id,
            Expense.name.in_(wanted),
        )
        .update({"label_cluster_id": new_cluster.id}, synchronize_session=False)
    )
    session.flush()

    # Conteggi e ancore ricalcolati dalle spese dopo lo spostamento: nessuno dei due
    # cluster può restare disallineato dalla realtà.
    _resync_variant_counts(session, user_id, cluster)

    for variant in moved_counts:
        _upsert_override(
            session, user_id, cluster.category_id, variant, new_cluster.id, "split"
        )
    for variant in remaining:
        _upsert_override(
            session, user_id, cluster.category_id, variant, cluster.id, "split"
        )
    session.flush()

    logger.info(
        "expense_label_cluster_split",
        extra={
            "domain": "usage",
            "event": "expense_label_cluster_split",
            "chat_id": user_id,
            "meta": {
                "cluster_id": cluster.id,
                "new_cluster_id": new_cluster.id,
                "variants_moved": len(wanted),
                "moved_expenses": moved_expenses,
            },
        },
    )
    return SplitResult(
        new_cluster_id=new_cluster.id,
        anchor_text=new_cluster.anchor_text,
        moved_expenses=moved_expenses,
    )
