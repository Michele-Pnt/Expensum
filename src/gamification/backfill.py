"""Ricalcolo dei contatori dalle sorgenti di verità e backfill retroattivo.

Due usi, stessa logica:

- **Riconciliazione notturna**: i contatori sono materializzati, quindi un evento
  perso resterebbe perso per sempre. `recompute_metrics` li riallinea leggendo i
  dati reali, e rende il sistema auto-riparante.
- **Backfill iniziale**: gli utenti beta hanno mesi di storico. Senza questo passo
  partirebbero da zero, il che sarebbe assurdo per chi usa il prodotto da sempre.

Il backfill scrive `source='backfill'` e `notified_telegram=True`: nessuno deve
ricevere trenta messaggi di congratulazioni in fila. `seen_at` resta NULL, così al
primo accesso alla UI futura il profilo appare già popolato.
"""

from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date, datetime

from src.gamification import metrics as M
from src.gamification import engine

logger = logging.getLogger("financial_agent.gamification")

# Quante spese servono in un mese perché il "mese pulito" conti: senza questa
# soglia basterebbe non registrare nulla per collezionare la serie.
CLEAN_MONTH_MIN_EXPENSES = 5


def _previous_month(today: date) -> tuple[int, int]:
    return (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def is_clean_month(storage, year: int, month: int, fallback_name: str) -> bool | None:
    """True se il mese si è chiuso senza spese nella categoria di fallback.

    Returns:
        None se il mese non è valutabile (troppe poche spese): in quel caso la
        catena non avanza ma nemmeno si azzera, perché non c'è stato un fallimento,
        solo assenza di dati.
    """
    start, end = _month_bounds(year, month)
    expenses = storage.fetch_all_transactions(start, end)
    if len(expenses) < CLEAN_MONTH_MIN_EXPENSES:
        return None
    return not any((e.get("category") or "") == fallback_name for e in expenses)


def evaluate_month(store, chat_id: str, storage, year: int, month: int,
                   *, source: str = "live", notified: bool = False) -> list:
    """Valuta un mese chiuso e assegna gli achievement ciclici che spettano.

    Sorgente unica di verità per i cicli mensili: la usano sia il job del 1° del
    mese sia il backfill retroattivo, così non possono divergere. Idempotente —
    la `dedup_key` è il periodo, quindi rivalutare lo stesso mese non premia due
    volte né gonfia i contatori.

    Aggiorna anche `clean_months_streak` (serie consecutiva), che si azzera al
    primo mese sporco mentre i contatori cumulativi non regrediscono mai.

    Returns:
        Gli Unlock assegnati (cicli + eventuali milestone appena superate).
    """
    from config import Config

    period = date(year, month, 1)
    start, end = _month_bounds(year, month)
    unlocks = []

    try:
        expenses = storage.fetch_all_transactions(start, end)
    except Exception:  # noqa: BLE001 — backend non interrogabile: mese saltato
        return []

    if len(expenses) < CLEAN_MONTH_MIN_EXPENSES:
        # Mese non valutabile: la serie consecutiva non avanza ma nemmeno si
        # azzera — non c'è stato un fallimento, solo assenza di dati.
        return []

    u = engine.award_cycle(store, chat_id, "cycle_active_month", period,
                           counter=M.ACTIVE_MONTHS_TOTAL, source=source, notified=notified)
    if u:
        unlocks.append(u)

    fallback = Config.CATEGORY_FALLBACK_NAME
    if not any((e.get("category") or "") == fallback for e in expenses):
        u = engine.award_cycle(store, chat_id, "cycle_clean_month", period,
                               counter=M.CLEAN_MONTHS_TOTAL, source=source, notified=notified)
        if u:
            unlocks.append(u)
            engine.bump_metrics(store, chat_id, {M.CLEAN_MONTHS_STREAK: 1}, value_date=period)
    else:
        engine.bump_metrics(store, chat_id, absolute={M.CLEAN_MONTHS_STREAK: 0}, value_date=period)

    if _opened_report_in_month(store, chat_id, start, end):
        u = engine.award_cycle(store, chat_id, "cycle_report_month", period,
                               counter=M.REPORT_MONTHS_TOTAL, source=source, notified=notified)
        if u:
            unlocks.append(u)

    # Le milestone cumulative si rivalutano subito: superare una soglia deve
    # sbloccare nello stesso passaggio, non alla prossima transazione.
    unlocks += engine.evaluate(
        store, chat_id, families=("cycles", "categories"), source=source, notified=notified,
    )
    return unlocks


def _opened_report_in_month(store, chat_id: str, start: date, end: date) -> bool:
    from src.user_store import ReportEvent

    with store.Session() as session:
        return session.query(ReportEvent).filter(
            ReportEvent.chat_id == chat_id,
            ReportEvent.event_type == "opened",
            ReportEvent.occurred_at >= datetime.combine(start, datetime.min.time()),
            ReportEvent.occurred_at <= datetime.combine(end, datetime.max.time()),
        ).first() is not None


def _count_streak_cycles(store, chat_id: str) -> int:
    """Cicli di streak completati, dedotti dai PlanChange di tipo streak_reward."""
    from src.user_store import PlanChange

    with store.Session() as session:
        return session.query(PlanChange).filter_by(
            chat_id=chat_id, change_type="streak_reward",
        ).count()


def _streak_max_days(store, chat_id: str) -> int:
    """Giorno più alto mai raggiunto: il target corrente meno l'incremento di 14."""
    from src.user_store import UserStreak

    with store.Session() as session:
        row = session.query(UserStreak).filter_by(chat_id=chat_id).first()
        if not row:
            return 0
        return max(row.streak_target_days - 14, row.current_streak_days)


def _count_tx_events(store, chat_id: str) -> dict[str, int]:
    """Spese confermate per canale, da `tx_events`.

    Lo storico precedente all'introduzione di `tx_events` non contiene il canale e
    non è ricostruibile: non lo si inventa, quei contatori partono da quel che c'è.
    """
    from src.user_store import TxEvent

    counters = {M.TX_TEXT: 0, M.TX_PHOTO: 0, M.TX_VOICE: 0}
    with store.Session() as session:
        rows = session.query(TxEvent.input_method).filter_by(
            chat_id=chat_id, outcome="confirmed", tx_type="expense",
        ).all()
    for (method,) in rows:
        metric = M.INPUT_METHOD_METRICS.get(method)
        if metric:
            counters[metric] += 1
    return counters


def recompute_metrics(store, chat_id: str, storage=None) -> dict[str, int]:
    """Ricalcola i contatori dalle sorgenti di verità e li scrive.

    Args:
        storage: `FinancialStorage` dell'utente. Se assente, le metriche che ne
            hanno bisogno (volume reale, mesi puliti, obiettivi) non vengono
            toccate — meglio lasciare il valore vecchio che azzerarlo per sbaglio.

    Returns:
        I contatori risultanti, o `{}` in caso di errore.
    """
    from src.user_store import Feedback, TxEvent

    chat_id = str(chat_id)
    try:
        absolute: dict[str, int] = {}
        absolute.update(_count_tx_events(store, chat_id))
        absolute[M.STREAK_CYCLES] = _count_streak_cycles(store, chat_id)
        absolute[M.STREAK_MAX_DAYS] = _streak_max_days(store, chat_id)
        absolute[M.TELEGRAM_LINKED] = 0 if chat_id.startswith("web_") else 1

        with store.Session() as session:
            absolute[M.FEEDBACK_SENT] = session.query(Feedback).filter_by(
                chat_id=chat_id
            ).count()
            tx_expenses = session.query(TxEvent).filter_by(
                chat_id=chat_id, outcome="confirmed", tx_type="expense",
            ).count()

        if storage is not None:
            # Lo storico pre-`tx_events` vive solo nelle spese vere: si prende il
            # massimo fra le due fonti, così nessuna delle due sottostima.
            expenses = storage.fetch_all_transactions(date(2000, 1, 1), date.today())
            absolute[M.EXPENSES_TOTAL] = max(len(expenses), tx_expenses)
            absolute[M.GOALS_COMPLETED] = len(
                storage.fetch_savings_goals(status="completed")
            )
        else:
            absolute[M.EXPENSES_TOTAL] = tx_expenses

        # `reports_generated` e `reports_opened` si contano da `report_events`, che
        # il backfill popola separatamente (vedi `backfill_report_events`).
        absolute.update(_count_report_events(store, chat_id))

        # I contatori dei cicli NON si ricalcolano qui: derivano dagli sblocchi
        # ciclici già assegnati, che sono la sorgente di verità. Ricalcolarli
        # dallo storico rischierebbe di sfasarli rispetto ai badge.
        absolute.update(_count_cycle_unlocks(store, chat_id))

        return engine.bump_metrics(store, chat_id, absolute=absolute)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Ricalcolo contatori fallito per %s: %s", chat_id, exc,
            extra={"domain": "gamification", "event": "recompute_failed",
                   "meta": {"chat_id": chat_id}},
        )
        return {}


def _count_cycle_unlocks(store, chat_id: str) -> dict[str, int]:
    """Contatori cumulativi dedotti dagli sblocchi ciclici già assegnati."""
    from src.user_store import UserAchievement

    pairs = (("cycle_active_month", M.ACTIVE_MONTHS_TOTAL),
             ("cycle_clean_month", M.CLEAN_MONTHS_TOTAL),
             ("cycle_report_month", M.REPORT_MONTHS_TOTAL))
    with store.Session() as session:
        return {
            metric: session.query(UserAchievement).filter_by(
                chat_id=chat_id, code=code,
            ).count()
            for code, metric in pairs
        }


def _count_report_events(store, chat_id: str) -> dict[str, int]:
    from src.user_store import ReportEvent

    with store.Session() as session:
        rows = session.query(ReportEvent.event_type).filter_by(chat_id=chat_id).all()
    generated = sum(1 for (kind,) in rows if kind == "generated")
    opened = sum(1 for (kind,) in rows if kind == "opened")
    return {M.REPORTS_GENERATED: generated, M.REPORTS_OPENED: opened}


def backfill_report_events(store, chat_id: str, storage) -> int:
    """Crea le righe `report_events` mancanti per i report già salvati.

    Solo `generated`: l'apertura di un report passato non è ricostruibile e non la
    si inventa — il contatore partirà dalla prima apertura reale.

    Returns:
        Quante righe sono state create.
    """
    from src.user_store import ReportEvent

    chat_id = str(chat_id)
    try:
        # `limit` alto: qui serve tutto lo storico, non l'ultima pagina.
        reports = storage.get_reports_for_user(chat_id, limit=1000)
    except Exception:  # noqa: BLE001 — backend senza report salvati
        return 0

    created = 0
    for report in reports:
        token = report.get("share_token")
        if not token:
            continue
        try:
            with store.Session() as session:
                session.add(ReportEvent(
                    chat_id=chat_id,
                    share_token=token,
                    report_type=report.get("report_type") or "monthly",
                    event_type="generated",
                    source="job",
                    occurred_at=_parse_dt(report.get("created_at")),
                ))
                session.commit()
                created += 1
        except Exception:  # noqa: BLE001 — già presente (unique) o errore transitorio
            continue
    return created


def _parse_dt(value):
    """`created_at` arriva come stringa ISO dallo storage. None se non parsabile."""
    from datetime import datetime

    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


#: Quanti mesi indietro ricostruire al backfill. Tre anni coprono le milestone
#: più alte senza scandagliare uno storico che non esiste.
BACKFILL_MONTHS = 36


def backfill_cycles(store, chat_id: str, storage, today: date | None = None) -> int:
    """Riassegna retroattivamente i cicli mensili di tutto lo storico.

    Percorre i mesi dal più vecchio al più recente — l'ordine conta, perché
    `clean_months_streak` è una serie consecutiva e va ricostruita in avanti.
    Idempotente: `evaluate_month` deduplica sul periodo.

    Returns:
        Quanti cicli sono stati assegnati.
    """
    today = today or date.today()
    year, month = _previous_month(today)
    months = []
    for _ in range(BACKFILL_MONTHS):
        months.append((year, month))
        year, month = _previous_month(date(year, month, 1))

    assigned = 0
    for y, m in reversed(months):
        assigned += len(evaluate_month(
            store, chat_id, storage, y, m, source="backfill", notified=True,
        ))
    return assigned


def backfill_user(store, chat_id: str, storage=None, *, silent: bool = True) -> dict:
    """Ricalcola tutto e sblocca gli achievement retroattivi di un utente.

    Args:
        silent: se True (default) gli sblocchi nascono già marcati come notificati,
            per non sommergere di messaggi chi ha mesi di storico alle spalle.

    Returns:
        `{"chat_id", "metrics", "unlocked", "codes"}`. Idempotente: rieseguirla non
        duplica gli sblocchi né raddoppia l'XP.
    """
    chat_id = str(chat_id)
    if storage is not None:
        # I report_events prima dei cicli: `cycle_report_month` li interroga.
        backfill_report_events(store, chat_id, storage)
        backfill_cycles(store, chat_id, storage)

    counters = recompute_metrics(store, chat_id, storage)

    unlocks = engine.evaluate(
        store, chat_id, counters=counters, source="backfill", notified=silent,
    )

    # Un badge per ciascun obiettivo già raggiunto, oltre ai tier a soglia.
    if storage is not None:
        try:
            for goal in storage.fetch_savings_goals(status="completed"):
                unlock = engine.award(
                    store, chat_id, "goal_reached", f"goal:{goal['id']}",
                    source="backfill", notified=silent,
                )
                if unlock:
                    unlocks.append(unlock)
        except Exception:  # noqa: BLE001 — backend senza obiettivi
            pass

    return {
        "chat_id": chat_id,
        "metrics": counters,
        "unlocked": len(unlocks),
        "codes": [u.definition.code for u in unlocks],
    }


def backfill_all(store, storage_factory=None, *, limit: int | None = None) -> dict:
    """Esegue il backfill per tutti gli utenti attivi.

    Args:
        storage_factory: callable `chat_id -> FinancialStorage | None`. Senza di
            essa si ricalcolano solo le metriche che non richiedono lo storage
            finanziario.

    Returns:
        Riepilogo aggregato con il dettaglio per utente.
    """
    from src.user_store import User

    with store.Session() as session:
        chat_ids = [
            row[0] for row in session.query(User.chat_id).filter(
                User.is_active == True  # noqa: E712
            ).all()
        ]
    if limit:
        chat_ids = chat_ids[:limit]

    results = []
    total_unlocked = 0
    for chat_id in chat_ids:
        storage = None
        if storage_factory is not None:
            try:
                storage = storage_factory(chat_id)
            except Exception as exc:  # noqa: BLE001 — un utente rotto non blocca gli altri
                logger.warning("Storage non disponibile per %s: %s", chat_id, exc)
        result = backfill_user(store, chat_id, storage)
        total_unlocked += result["unlocked"]
        results.append(result)

    return {"users": len(results), "unlocked": total_unlocked, "details": results}


# ---------------------------------------------------------------------------
# Ricalcolo dell'XP dopo una ricalibrazione del catalogo
# ---------------------------------------------------------------------------

def recompute_xp(store, chat_id: str) -> dict:
    """Riallinea l'XP di un utente ai valori attuali del registry.

    Serve perché `xp_awarded` e `total_xp` sono **istantanee**: il registry viene
    letto una volta sola, allo sblocco, e poi il numero resta congelato a database.
    Cambiare un valore in `registry.py` non è quindi retroattivo — senza questa
    funzione una ricalibrazione varrebbe solo per gli sblocchi futuri, e due utenti
    con gli stessi badge avrebbero XP diversi a seconda di quando li hanno presi.

    Tocca esclusivamente `xp_awarded`, `total_xp` e `level`. Non sfiora
    `unlocked_at`, `seen_at`, `notified_telegram` né `source`: la storia di cosa
    l'utente ha fatto e quando non cambia, cambia solo quanto vale.

    I codici non più presenti nel registry (achievement deprecati) mantengono il
    valore con cui erano stati assegnati: azzerarli toglierebbe XP già guadagnati
    per una decisione di prodotto successiva.

    Idempotente. Non solleva mai.

    Returns:
        `{"chat_id", "updated", "unknown_codes", "old_xp", "new_xp",
          "old_level", "new_level"}`.
    """
    from src.user_store import UserAchievement, UserGamificationProfile
    from src.gamification import xp as XP
    from src.gamification.registry import BY_CODE

    chat_id = str(chat_id)
    result = {"chat_id": chat_id, "updated": 0, "unknown_codes": [],
              "old_xp": 0, "new_xp": 0, "old_level": 1, "new_level": 1}
    try:
        with store.Session() as session:
            rows = session.query(UserAchievement).filter_by(chat_id=chat_id).all()
            if not rows:
                return result

            total = 0
            unknown = set()
            for row in rows:
                definition = BY_CODE.get(row.code)
                if definition is None:
                    unknown.add(row.code)
                    total += row.xp_awarded or 0
                    continue
                if row.xp_awarded != definition.xp:
                    row.xp_awarded = definition.xp
                    result["updated"] += 1
                total += definition.xp

            profile = session.query(UserGamificationProfile).filter_by(
                chat_id=chat_id
            ).first()
            if profile is None:
                profile = UserGamificationProfile(chat_id=chat_id, total_xp=0, level=1)
                session.add(profile)

            result["old_xp"] = profile.total_xp or 0
            result["old_level"] = profile.level or 1
            profile.total_xp = total
            profile.level = XP.level_for_xp(total)
            result["new_xp"] = total
            result["new_level"] = profile.level
            result["unknown_codes"] = sorted(unknown)

            session.commit()
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Ricalcolo XP fallito per %s: %s", chat_id, exc,
            extra={"domain": "gamification", "event": "recompute_xp_failed",
                   "meta": {"chat_id": chat_id}},
        )
        return result


def recompute_xp_all(store, *, limit: int | None = None) -> dict:
    """Riallinea l'XP di tutti gli utenti attivi.

    Returns:
        Riepilogo con il dettaglio per utente e l'elenco di chi cambia livello —
        in particolare chi lo **perde**, che è il caso da guardare prima di
        confermare una ricalibrazione.
    """
    from src.user_store import User

    with store.Session() as session:
        chat_ids = [
            row[0] for row in session.query(User.chat_id).filter(
                User.is_active == True  # noqa: E712
            ).all()
        ]
    if limit:
        chat_ids = chat_ids[:limit]

    details = [recompute_xp(store, cid) for cid in chat_ids]
    return {
        "users": len(details),
        "rows_updated": sum(d["updated"] for d in details),
        "level_up": [d for d in details if d["new_level"] > d["old_level"]],
        "level_down": [d for d in details if d["new_level"] < d["old_level"]],
        "unknown_codes": sorted({c for d in details for c in d["unknown_codes"]}),
        "details": details,
    }
