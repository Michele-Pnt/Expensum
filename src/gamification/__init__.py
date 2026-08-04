"""Motore di gamification: achievement, XP e livelli.

Punto di ingresso per il resto del codebase: `record_event` per segnalare che è
successo qualcosa, `get_user_state` / `get_summary` per leggere lo stato.

Nessuna funzione di questo package solleva mai: un errore di gamification non deve
poter far fallire il salvataggio di una spesa o la generazione di un report.
"""

from src.gamification.engine import (  # noqa: F401
    Unlock,
    award,
    evaluate,
    get_profile,
    get_summary,
    get_user_state,
    mark_notified,
    mark_seen,
    record_event,
)

__all__ = [
    "Unlock",
    "award",
    "evaluate",
    "get_profile",
    "get_summary",
    "get_user_state",
    "mark_notified",
    "mark_seen",
    "record_event",
]
