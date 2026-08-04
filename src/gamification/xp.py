"""Curva di esperienza e livelli.

Curva quadratica chiusa e invertibile: `cumulative_xp_for_level(L) = 50·L·(L−1)`,
cioè 0, 100, 300, 600, 1000, 1500... Ogni livello costa 100 XP più del precedente,
quindi la progressione rallenta senza mai bloccarsi.

L'XP si guadagna **solo** sbloccando achievement, mai per singola azione: la curva
resta prevedibile e il backfill retroattivo deterministico (rieseguirlo non può
produrre un livello diverso).

Il tetto è tenuto volutamente alto (30, cioè 43.500 XP) rispetto a quanto il
catalogo attuale mette in gioco (~11.200 XP una tantum + ~780 XP/anno di rendita
ciclica): un utente vede solo il proprio livello, mai il massimo teorico, quindi un
tetto capiente costa zero in percezione ma lascia margine per i cataloghi futuri
senza dover rialzare la curva né toccare i livelli già raggiunti dagli utenti
esistenti. Con il catalogo di oggi, il livello 20 (19.000 XP) resta comunque
l'orizzonte pratico: cinque-sei anni di uso costante prima che la sola rendita
ciclica possa colmare il divario.
"""

from __future__ import annotations

MAX_LEVEL = 30

# Coefficiente della curva: costo del primo livello / 2.
_XP_COEFFICIENT = 50


def cumulative_xp_for_level(level: int) -> int:
    """XP totale necessario per *raggiungere* un livello (0 per il livello 1)."""
    level = max(1, min(level, MAX_LEVEL))
    return _XP_COEFFICIENT * level * (level - 1)


def level_for_xp(total_xp: int) -> int:
    """Livello corrispondente a un totale di XP. Inverso di `cumulative_xp_for_level`."""
    total_xp = max(0, total_xp)
    level = 1
    while level < MAX_LEVEL and cumulative_xp_for_level(level + 1) <= total_xp:
        level += 1
    return level


def level_progress(total_xp: int) -> dict:
    """Stato completo del profilo XP, nella forma che l'API espone alla UI."""
    total_xp = max(0, total_xp)
    level = level_for_xp(total_xp)
    is_max = level >= MAX_LEVEL

    floor_xp = cumulative_xp_for_level(level)
    if is_max:
        return {
            "level": level,
            "total_xp": total_xp,
            "xp_into_level": total_xp - floor_xp,
            "xp_for_next": 0,
            "xp_to_next": 0,
            "progress_pct": 100.0,
            "is_max": True,
        }

    next_xp = cumulative_xp_for_level(level + 1)
    span = next_xp - floor_xp
    into = total_xp - floor_xp
    return {
        "level": level,
        "total_xp": total_xp,
        "xp_into_level": into,
        "xp_for_next": span,
        "xp_to_next": next_xp - total_xp,
        "progress_pct": round(into / span * 100, 1) if span else 0.0,
        "is_max": False,
    }
