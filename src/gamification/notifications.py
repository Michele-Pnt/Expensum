"""Testi delle notifiche di sblocco.

Separato dal registry di proposito: le definizioni contengono solo dati, qui sta
la formattazione per un canale specifico (Markdown Telegram). Quando arriverà la
nuova UI, i suoi testi si aggiungeranno qui senza toccare il catalogo.

Nessuno di questi testi contiene contenuto libero dell'utente: solo titoli di
achievement, che vengono dal catalogo.
"""

from __future__ import annotations

# Oltre questa soglia si manda un unico messaggio riassuntivo invece di uno per
# achievement: succede tipicamente al primo accesso di un utente con storico.
MAX_INDIVIDUAL_MESSAGES = 3

_LEVEL_UP = {
    "it": "\n\n🆙 Sei salito al livello {level}!",
    "en": "\n\n🆙 You reached level {level}!",
}

_SINGLE = {
    "it": "🏅 *{title}*\n{description}\n\n+{xp} XP",
    "en": "🏅 *{title}*\n{description}\n\n+{xp} XP",
}

_AGGREGATE_HEADER = {
    "it": "🏅 *Hai sbloccato {count} obiettivi*\n",
    "en": "🏅 *You unlocked {count} achievements*\n",
}

_AGGREGATE_FOOTER = {
    "it": "\nIn tutto +{xp} XP.",
    "en": "\nA total of +{xp} XP.",
}


def _t(table: dict[str, str], locale: str) -> str:
    return table.get(locale) or table["it"]


def achievement_message(unlock: dict, locale: str = "it") -> str:
    """Messaggio Telegram per un singolo sblocco (Markdown)."""
    text = _t(_SINGLE, locale).format(
        title=unlock["title"],
        description=unlock["description"],
        xp=unlock["xp"],
    )
    if unlock.get("new_level"):
        text += _t(_LEVEL_UP, locale).format(level=unlock["new_level"])
    return text


def aggregate_message(unlocks: list[dict], locale: str = "it") -> str:
    """Messaggio unico quando gli sblocchi sono troppi per notificarli uno a uno."""
    lines = [_t(_AGGREGATE_HEADER, locale).format(count=len(unlocks))]
    lines += [f"• {u['title']}" for u in unlocks]
    total_xp = sum(u["xp"] for u in unlocks)
    lines.append(_t(_AGGREGATE_FOOTER, locale).format(xp=total_xp))

    highest_level = max((u.get("new_level") or 0) for u in unlocks)
    if highest_level:
        lines.append(_t(_LEVEL_UP, locale).format(level=highest_level))
    return "\n".join(lines)


def build_messages(unlocks: list[dict], locale: str = "it") -> list[str]:
    """I messaggi da inviare per una lista di sblocchi.

    Fino a `MAX_INDIVIDUAL_MESSAGES` sblocchi si festeggia uno per uno; oltre, un
    solo riepilogo — ricevere quindici notifiche di fila è un fastidio, non un premio.
    """
    if not unlocks:
        return []
    if len(unlocks) <= MAX_INDIVIDUAL_MESSAGES:
        return [achievement_message(u, locale) for u in unlocks]
    return [aggregate_message(unlocks, locale)]
