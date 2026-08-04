"""Motore di valutazione degli achievement.

Contratto non negoziabile: **nessuna funzione pubblica di questo modulo solleva
mai**. La gamification è un ornamento; un suo errore non deve poter far fallire il
salvataggio di una spesa, la generazione di un report o una richiesta HTTP. Ogni
entry point è avvolto in try/except e in caso di guaio restituisce un valore neutro,
esattamente come `UserStore.record_streak_activity`.

Secondo vincolo: **niente query pesanti nel percorso caldo**. Alla conferma di una
spesa il motore fa una SELECT e una UPDATE sui contatori e poi confronta in memoria
una manciata di definizioni. Mai un COUNT, mai un accesso allo storage finanziario.

`record_event` è l'unico entry point che il resto del codebase dovrebbe usare.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.exc import IntegrityError

from src.gamification import metrics as M
from src.gamification import xp as XP
from src.gamification.registry import (
    ACHIEVEMENTS,
    BY_CODE,
    BY_FAMILY,
    BY_METRIC,
    FAMILIES_BY_METRIC,
    FAMILY_TITLES,
    AchievementDef,
    family_title,
)

logger = logging.getLogger("financial_agent.gamification")


@dataclass(frozen=True)
class Unlock:
    """Un achievement appena sbloccato, pronto per la notifica."""

    definition: AchievementDef
    dedup_key: str
    xp: int
    progress_value: int | None = None
    new_level: int | None = None   # valorizzato solo se questo sblocco ha alzato il livello

    def as_dict(self, locale: str = "it") -> dict:
        return {
            "code": self.definition.code,
            "family": self.definition.family,
            "tier": self.definition.tier,
            "icon": self.definition.icon,
            "title": self.definition.title(locale),
            "description": self.definition.description(locale),
            "xp": self.xp,
            "dedup_key": self.dedup_key,
            "progress_value": self.progress_value,
            "new_level": self.new_level,
        }


# Mappa evento di dominio -> (delta sui contatori, famiglie da rivalutare).
# Gli eventi delle spese hanno la forma "expense_confirmed:<input_method>" e sono
# risolti a runtime da `_deltas_for_event`, perché il canale è parte del nome.
EVENT_MAP: dict[str, tuple[dict[str, int], tuple[str, ...]]] = {
    "report_generated": ({M.REPORTS_GENERATED: 1}, ("reports",)),
    "report_opened": ({M.REPORTS_OPENED: 1}, ("reports",)),
    "feedback_sent": ({M.FEEDBACK_SENT: 1}, ("onboarding",)),
    "telegram_linked": ({M.TELEGRAM_LINKED: 1}, ("onboarding",)),
    "savings_goal_completed": ({M.GOALS_COMPLETED: 1}, ("goals",)),
    "streak_cycle_completed": ({M.STREAK_CYCLES: 1}, ("streak",)),
}

# Eventi che, oltre ad alzare un contatore, sbloccano un achievement ripetibile
# per singola istanza (un badge per ogni obiettivo raggiunto, non solo i tier).
REPEATABLE_BY_EVENT: dict[str, str] = {
    "savings_goal_completed": "goal_reached",
}


def _deltas_for_event(event: str) -> tuple[dict[str, int], tuple[str, ...]] | None:
    """Risolve un evento nei delta sui contatori e nelle famiglie da rivalutare."""
    if event.startswith("expense_confirmed:"):
        method = event.split(":", 1)[1]
        deltas = {M.EXPENSES_TOTAL: 1}
        channel_metric = M.INPUT_METHOD_METRICS.get(method)
        if channel_metric:
            deltas[channel_metric] = 1
        return deltas, ("volume", "channel")
    return EVENT_MAP.get(event)


# ---------------------------------------------------------------------------
# Contatori
# ---------------------------------------------------------------------------

def bump_metrics(
    store,
    chat_id: str,
    deltas: dict[str, int] | None = None,
    *,
    absolute: dict[str, int] | None = None,
    value_date: date | None = None,
) -> dict[str, int]:
    """Aggiorna i contatori dell'utente e restituisce lo stato completo.

    `deltas` incrementa, `absolute` sovrascrive (usato dal ricalcolo notturno e dal
    reset della catena mensile). L'incremento usa l'espressione SQL `value = value + n`
    invece di leggere-modificare-scrivere in Python: è atomico sia su Postgres sia
    su SQLite, e due conferme simultanee non si perdono a vicenda.

    Returns:
        Tutti i contatori aggiornati dell'utente, o `{}` in caso di errore.
    """
    from src.user_store import UserMetricCounter

    chat_id = str(chat_id)
    deltas = deltas or {}
    absolute = absolute or {}

    try:
        with store.Session() as session:
            existing = {
                row[0] for row in
                session.query(UserMetricCounter.metric).filter_by(chat_id=chat_id).all()
            }

            # Prima si creano le righe mancanti a zero: l'espressione SQL
            # `value = value + n` è valida solo in UPDATE, in INSERT fa riferimento
            # a una colonna che ancora non esiste.
            for metric in set(deltas) | set(absolute):
                if metric not in existing:
                    session.add(UserMetricCounter(chat_id=chat_id, metric=metric, value=0))
            session.flush()

            for metric, delta in deltas.items():
                values = {"value": UserMetricCounter.value + delta}
                if value_date is not None:
                    values["value_date"] = value_date
                session.query(UserMetricCounter).filter_by(
                    chat_id=chat_id, metric=metric,
                ).update(values, synchronize_session=False)

            for metric, value in absolute.items():
                values = {"value": value}
                if value_date is not None:
                    values["value_date"] = value_date
                session.query(UserMetricCounter).filter_by(
                    chat_id=chat_id, metric=metric,
                ).update(values, synchronize_session=False)

            session.commit()

            return {
                row.metric: row.value
                for row in session.query(UserMetricCounter).filter_by(chat_id=chat_id).all()
            }
    except Exception as exc:  # noqa: BLE001 — la gamification non deve mai propagare
        logger.warning(
            "Impossibile aggiornare i contatori per %s: %s", chat_id, exc,
            extra={"domain": "gamification", "event": "bump_metrics_failed",
                   "meta": {"chat_id": chat_id}},
        )
        return {}


def get_metrics(store, chat_id: str) -> dict[str, int]:
    """Contatori persistiti dell'utente (senza le derivate). `{}` in caso di errore."""
    from src.user_store import UserMetricCounter

    try:
        with store.Session() as session:
            rows = session.query(UserMetricCounter).filter_by(chat_id=str(chat_id)).all()
            return {row.metric: row.value for row in rows}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Impossibile leggere i contatori per %s: %s", chat_id, exc)
        return {}


# ---------------------------------------------------------------------------
# Valutazione
# ---------------------------------------------------------------------------

def _insert_unlock(
    session,
    chat_id: str,
    definition: AchievementDef,
    dedup_key: str,
    progress_value: int | None,
    source: str,
    notified: bool,
) -> Unlock | None:
    """Inserisce lo sblocco e accredita l'XP, o None se era già presente.

    L'idempotenza è delegata allo unique constraint: si tenta l'insert e si tratta
    l'IntegrityError come "già sbloccato". Nessun check-then-insert, che sarebbe
    soggetto a race fra due eventi simultanei.

    L'insert sta dentro un SAVEPOINT (`begin_nested`) e non nella transazione
    esterna: un `session.rollback()` annullerebbe l'intera transazione, cioè anche
    gli sblocchi riusciti prima nello stesso ciclo di `evaluate`. Il risultato
    sarebbe un achievement notificato all'utente ma mai scritto a DB, rinotificato
    a ogni riconciliazione notturna.
    """
    from src.user_store import UserAchievement, UserGamificationProfile

    row = UserAchievement(
        chat_id=chat_id,
        code=definition.code,
        dedup_key=dedup_key,
        xp_awarded=definition.xp,
        progress_value=progress_value,
        source=source,
        notified_telegram=notified,
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        return None

    profile = session.query(UserGamificationProfile).filter_by(chat_id=chat_id).first()
    if profile is None:
        profile = UserGamificationProfile(chat_id=chat_id, total_xp=0, level=1)
        session.add(profile)
        session.flush()

    previous_level = profile.level
    profile.total_xp = (profile.total_xp or 0) + definition.xp
    profile.level = XP.level_for_xp(profile.total_xp)
    new_level = None
    if profile.level > previous_level:
        profile.last_level_up_at = datetime.utcnow()
        new_level = profile.level

    return Unlock(
        definition=definition,
        dedup_key=dedup_key,
        xp=definition.xp,
        progress_value=progress_value,
        new_level=new_level,
    )


def evaluate(
    store,
    chat_id: str,
    *,
    counters: dict[str, int] | None = None,
    families: tuple[str, ...] | None = None,
    source: str = "live",
    notified: bool = False,
) -> list[Unlock]:
    """Sblocca gli achievement le cui soglie sono ora soddisfatte.

    Args:
        counters: contatori già in mano al chiamante (evita una query in più).
        families: se valorizzato, valuta solo queste famiglie. È ciò che tiene
            leggero il percorso caldo: alla conferma di una spesa si guardano solo
            'volume' e 'channel', non tutte e 44 le definizioni.
        source: 'live' | 'backfill' | 'reconcile', tracciato sulla riga.
        notified: preimposta `notified_telegram`. Il backfill lo mette a True per
            non sommergere di messaggi chi ha già mesi di storico.

    Returns:
        Solo gli sblocchi *nuovi* — lista vuota è il caso normale. Mai un'eccezione.
    """
    chat_id = str(chat_id)
    try:
        values = M.with_derived(counters if counters is not None else get_metrics(store, chat_id))
        candidates = [
            a for a in ACHIEVEMENTS
            if a.metric and not a.repeatable
            and (families is None or a.family in families)
            and values.get(a.metric, 0) >= a.threshold
        ]
        if not candidates:
            return []

        unlocks = []
        with store.Session() as session:
            for definition in sorted(candidates, key=lambda a: (a.family, a.threshold)):
                unlock = _insert_unlock(
                    session, chat_id, definition, "",
                    progress_value=values.get(definition.metric or "", 0),
                    source=source, notified=notified,
                )
                if unlock:
                    unlocks.append(unlock)
            session.commit()

        for unlock in unlocks:
            logger.info(
                "Achievement sbloccato: %s", unlock.definition.code,
                extra={"domain": "gamification", "event": "achievement_unlocked",
                       "meta": {"chat_id": chat_id, "code": unlock.definition.code,
                                "family": unlock.definition.family, "source": source}},
            )
        return unlocks
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Valutazione achievement fallita per %s: %s", chat_id, exc,
            extra={"domain": "gamification", "event": "evaluate_failed",
                   "meta": {"chat_id": chat_id}},
        )
        return []


def award(
    store,
    chat_id: str,
    code: str,
    dedup_key: str = "",
    *,
    progress_value: int | None = None,
    source: str = "live",
    notified: bool = False,
) -> Unlock | None:
    """Sblocca esplicitamente un achievement non basato su soglia.

    Serve ai ripetibili (`goal_reached`, uno per obiettivo raggiunto), dove la
    chiave di deduplicazione identifica l'istanza. Idempotente. Mai un'eccezione.
    """
    chat_id = str(chat_id)
    definition = BY_CODE.get(code)
    if definition is None:
        logger.warning("Achievement sconosciuto: %s", code)
        return None
    try:
        with store.Session() as session:
            unlock = _insert_unlock(
                session, chat_id, definition, dedup_key,
                progress_value=progress_value, source=source, notified=notified,
            )
            session.commit()
        if unlock:
            logger.info(
                "Achievement sbloccato: %s", code,
                extra={"domain": "gamification", "event": "achievement_unlocked",
                       "meta": {"chat_id": chat_id, "code": code, "source": source}},
            )
        return unlock
    except Exception as exc:  # noqa: BLE001
        logger.warning("Award %s fallito per %s: %s", code, chat_id, exc)
        return None


def award_cycle(
    store,
    chat_id: str,
    code: str,
    period: date,
    *,
    counter: str | None = None,
    source: str = "live",
    notified: bool = False,
) -> Unlock | None:
    """Assegna un achievement ciclico per un dato mese e incrementa il contatore.

    I cicli sono l'asse che non si esaurisce mai: ogni mese si riguadagnano. La
    `dedup_key` è il periodo (`YYYY-MM`), quindi lo unique constraint impedisce di
    premiare due volte lo stesso mese anche se il job gira più volte o il backfill
    viene rieseguito — ed è ciò che rende sicuro incrementare `counter` solo quando
    lo sblocco è davvero nuovo.

    Args:
        period: un giorno qualsiasi del mese da premiare.
        counter: metrica cumulativa da incrementare (es. `clean_months_total`),
            che alimenta le milestone. None se il ciclo non ne ha una.

    Returns:
        L'Unlock se il mese non era già stato premiato, altrimenti None. Mai
        un'eccezione.
    """
    key = f"{period.year:04d}-{period.month:02d}"
    unlock = award(store, chat_id, code, key, source=source, notified=notified)
    if unlock and counter:
        bump_metrics(store, chat_id, {counter: 1}, value_date=period)
    return unlock


def record_event(
    store,
    chat_id: str,
    event: str,
    *,
    dedup_key: str | None = None,
    extra_absolute: dict[str, int] | None = None,
    source: str = "live",
    notified: bool = False,
) -> list[Unlock]:
    """Entry point unico: registra un evento di dominio e ritorna gli sblocchi.

    Args:
        event: 'expense_confirmed:<text|photo|voice>' oppure una chiave di `EVENT_MAP`.
        dedup_key: identifica l'istanza per gli achievement ripetibili (es. "goal:12").
        extra_absolute: contatori da impostare a un valore assoluto insieme all'evento
            (es. `streak_max_days`, che è un massimo e non un'accumulazione).

    Returns:
        Gli achievement appena sbloccati. Lista vuota anche in caso di errore: questa
        funzione **non solleva mai**.
    """
    chat_id = str(chat_id)
    try:
        resolved = _deltas_for_event(event)
        if resolved is None:
            logger.warning("Evento di gamification sconosciuto: %s", event)
            return []
        deltas, families = resolved

        counters = bump_metrics(store, chat_id, deltas, absolute=extra_absolute)
        unlocks = evaluate(
            store, chat_id, counters=counters, families=families,
            source=source, notified=notified,
        )

        repeatable_code = REPEATABLE_BY_EVENT.get(event)
        if repeatable_code and dedup_key:
            unlock = award(
                store, chat_id, repeatable_code, dedup_key,
                source=source, notified=notified,
            )
            if unlock:
                unlocks.append(unlock)
        return unlocks
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "record_event('%s') fallito per %s: %s", event, chat_id, exc,
            extra={"domain": "gamification", "event": "record_event_failed",
                   "meta": {"chat_id": chat_id, "gamification_event": event}},
        )
        return []


# ---------------------------------------------------------------------------
# Lettura per l'API
# ---------------------------------------------------------------------------

def get_profile(store, chat_id: str) -> dict:
    """Profilo XP dell'utente, con livello e progresso verso il successivo."""
    from src.user_store import UserAchievement, UserGamificationProfile

    try:
        with store.Session() as session:
            profile = session.query(UserGamificationProfile).filter_by(
                chat_id=str(chat_id)
            ).first()
            total_xp = profile.total_xp if profile else 0
            rows = session.query(UserAchievement).filter_by(chat_id=str(chat_id)).all()
            unseen = sum(1 for r in rows if r.seen_at is None)
        data = XP.level_progress(total_xp)
        data.update({"unlocked_count": len(rows), "unseen_count": unseen})
        return data
    except Exception as exc:  # noqa: BLE001
        logger.warning("Lettura profilo gamification fallita per %s: %s", chat_id, exc)
        data = XP.level_progress(0)
        data.update({"unlocked_count": 0, "unseen_count": 0})
        return data


def _progress_for(definition: AchievementDef, values: dict[str, int]) -> dict | None:
    """Avanzamento verso la soglia, o None per gli achievement senza metrica."""
    if not definition.metric:
        return None
    current = values.get(definition.metric, 0)
    target = definition.threshold
    return {
        "current": current,
        "target": target,
        "pct": round(min(current / target, 1.0) * 100, 1) if target else 0.0,
    }


def get_user_state(
    store,
    chat_id: str,
    *,
    locale: str = "it",
    backend: str = "postgres",
    plan_type: str = "free",
) -> dict:
    """Catalogo completo più stato e progresso dell'utente.

    Il payload contiene *tutti* gli achievement, non solo quelli sbloccati: è ciò
    che lo rende renderizzabile da una UI che non esiste ancora. Le famiglie non
    ottenibili con il backend/piano dell'utente non spariscono, vengono marcate
    `unavailable`, così possono essere usate come teaser.

    Costo: tre query, nessun accesso allo storage finanziario.
    """
    from src.user_store import UserAchievement

    chat_id = str(chat_id)
    values = M.with_derived(get_metrics(store, chat_id))

    try:
        with store.Session() as session:
            rows = session.query(UserAchievement).filter_by(chat_id=chat_id).all()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Lettura achievement fallita per %s: %s", chat_id, exc)
        rows = []

    unlocked: dict[str, list] = {}
    for row in rows:
        unlocked.setdefault(row.code, []).append(row)

    families = []
    for family in FAMILY_TITLES:
        definitions = BY_FAMILY.get(family, ())
        if not definitions:
            continue
        available = any(d.is_available(backend, plan_type) for d in definitions)
        items = []
        for definition in definitions:
            instances = unlocked.get(definition.code, [])
            if definition.hidden and not instances:
                continue
            if instances:
                state = "unlocked"
            elif not available:
                state = "unavailable"
            else:
                state = "locked"
            item = {
                "code": definition.code,
                "family": definition.family,
                "tier": definition.tier,
                "title": definition.title(locale),
                "description": definition.description(locale),
                "icon": definition.icon,
                "xp": definition.xp,
                "repeatable": definition.repeatable,
                "supersedes": definition.supersedes,
                "state": state,
                "progress": _progress_for(definition, values),
                "unlocked_at": (
                    max(i.unlocked_at for i in instances).isoformat() if instances else None
                ),
                "seen": all(i.seen_at is not None for i in instances) if instances else False,
            }
            if definition.repeatable:
                item["count"] = len(instances)
                item["instances"] = [
                    {"dedup_key": i.dedup_key, "unlocked_at": i.unlocked_at.isoformat()}
                    for i in instances
                ]
            items.append(item)

        families.append({
            "code": family,
            "title": family_title(family, locale),
            "state": "available" if available else "unavailable",
            "unavailable_reason": None if available else _unavailable_reason(
                definitions, backend, plan_type
            ),
            "unlocked": sum(1 for i in items if i["state"] == "unlocked"),
            "total": len(items),
            "achievements": items,
        })

    recent = sorted(rows, key=lambda r: r.unlocked_at, reverse=True)[:10]
    return {
        "profile": get_profile(store, chat_id),
        "metrics": values,
        "families": families,
        "recent_unlocks": [
            {
                "code": r.code,
                "title": BY_CODE[r.code].title(locale) if r.code in BY_CODE else r.code,
                "unlocked_at": r.unlocked_at.isoformat(),
                "xp": r.xp_awarded,
                "seen": r.seen_at is not None,
            }
            for r in recent
        ],
        "locale": locale,
        "generated_at": datetime.utcnow().isoformat(),
    }


def _unavailable_reason(definitions, backend: str, plan_type: str) -> str:
    """Perché una famiglia non è ottenibile: serve alla UI per il messaggio giusto."""
    needs_pg = all("postgres" in d.backends and "notion" not in d.backends for d in definitions)
    needs_pro = all(d.plans == ("pro",) for d in definitions)
    if needs_pg and needs_pro:
        return "requires_postgres_pro"
    if needs_pg:
        return "requires_postgres"
    if needs_pro:
        return "requires_pro"
    return "unavailable"


def get_summary(store, chat_id: str, *, locale: str = "it",
                backend: str = "postgres", plan_type: str = "free") -> dict:
    """Versione compatta per un widget di home o la schermata iniziale dell'app."""
    from src.user_store import UserAchievement

    chat_id = str(chat_id)
    values = M.with_derived(get_metrics(store, chat_id))

    try:
        with store.Session() as session:
            rows = session.query(UserAchievement).filter_by(chat_id=chat_id).all()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Lettura achievement fallita per %s: %s", chat_id, exc)
        rows = []

    unlocked_codes = {r.code for r in rows}

    # I tre achievement più vicini al traguardo: è la spinta più efficace da mostrare.
    next_up = []
    for definition in ACHIEVEMENTS:
        if definition.code in unlocked_codes or not definition.metric:
            continue
        if not definition.is_available(backend, plan_type):
            continue
        progress = _progress_for(definition, values)
        if progress and progress["pct"] > 0:
            next_up.append({
                "code": definition.code,
                "title": definition.title(locale),
                "icon": definition.icon,
                "xp": definition.xp,
                "progress": progress,
            })
    next_up.sort(key=lambda item: item["progress"]["pct"], reverse=True)

    return {
        "profile": get_profile(store, chat_id),
        "next_up": next_up[:3],
        "unseen_unlocks": [
            {
                "code": r.code,
                "title": BY_CODE[r.code].title(locale) if r.code in BY_CODE else r.code,
                "icon": BY_CODE[r.code].icon if r.code in BY_CODE else "award",
                "xp": r.xp_awarded,
                "unlocked_at": r.unlocked_at.isoformat(),
            }
            for r in sorted(rows, key=lambda r: r.unlocked_at, reverse=True)
            if r.seen_at is None
        ][:10],
        "locale": locale,
    }


def mark_seen(store, chat_id: str, codes: list[str] | None = None) -> int:
    """Marca come visti gli sblocchi indicati (tutti se `codes` è None).

    È il meccanismo con cui webapp e app dichiarano di aver mostrato il toast:
    pull, non push, quindi identico sui due client.

    Returns:
        Quante righe sono state aggiornate.
    """
    from src.user_store import UserAchievement

    try:
        with store.Session() as session:
            query = session.query(UserAchievement).filter(
                UserAchievement.chat_id == str(chat_id),
                UserAchievement.seen_at.is_(None),
            )
            if codes:
                query = query.filter(UserAchievement.code.in_(codes))
            updated = query.update({"seen_at": datetime.utcnow()}, synchronize_session=False)
            session.commit()
            return updated
    except Exception as exc:  # noqa: BLE001
        logger.warning("mark_seen fallito per %s: %s", chat_id, exc)
        return 0


def mark_notified(store, chat_id: str, codes: list[str]) -> int:
    """Marca come già notificati su Telegram gli sblocchi indicati."""
    from src.user_store import UserAchievement

    if not codes:
        return 0
    try:
        with store.Session() as session:
            updated = session.query(UserAchievement).filter(
                UserAchievement.chat_id == str(chat_id),
                UserAchievement.code.in_(codes),
                UserAchievement.notified_telegram.is_(False),
            ).update({"notified_telegram": True}, synchronize_session=False)
            session.commit()
            return updated
    except Exception as exc:  # noqa: BLE001
        logger.warning("mark_notified fallito per %s: %s", chat_id, exc)
        return 0
