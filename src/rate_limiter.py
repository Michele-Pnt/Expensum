"""
rate_limiter.py — Sliding Window Rate Limiter per il Finance Bot.

Protegge il bot da attacchi DoS e Token Flooding limitando il numero
di messaggi che un singolo utente può inviare in un dato intervallo di tempo.

Funzionamento:
  - Per ogni utente, teniamo in memoria una lista di timestamp dei messaggi.
  - Ad ogni nuovo messaggio, rimuoviamo i timestamp più vecchi della finestra (es. 60s).
  - Se la lista supera il limite, blocchiamo il messaggio.
  - Questa tecnica si chiama "Sliding Window" ed è più precisa del semplice
    conteggio per minuto fisso.
"""

import logging
from collections import defaultdict
from time import time

logger = logging.getLogger("financial_agent.rate_limiter")

# Struttura: { "chat_id": [timestamp1, timestamp2, ...] }
_history: dict[str, list[float]] = defaultdict(list)


def is_rate_limited(chat_id: str, max_messages: int, window_seconds: int = 60) -> bool:
    """
    Controlla se un utente ha superato il limite di messaggi.

    Args:
        chat_id: L'ID univoco dell'utente Telegram.
        max_messages: Numero massimo di messaggi consentiti nella finestra.
        window_seconds: Durata della finestra di tempo in secondi (default: 60).

    Returns:
        True se l'utente è bloccato (ha superato il limite).
        False se il messaggio può essere processato normalmente.
    """
    now = time()
    chat_id = str(chat_id)

    # 1. Slide: rimuoviamo i timestamp fuori dalla finestra temporale
    _history[chat_id] = [t for t in _history[chat_id] if now - t < window_seconds]

    # 2. Controllo: se siamo già al limite, blocchiamo
    if len(_history[chat_id]) >= max_messages:
        logger.warning(
            f"[User {chat_id}] Rate limit superato: "
            f"{len(_history[chat_id])}/{max_messages} messaggi negli ultimi {window_seconds}s."
        )
        return True

    # 3. Registriamo il nuovo timestamp e lasciamo passare
    _history[chat_id].append(now)
    return False


def reset_user(chat_id: str) -> None:
    """Resetta il contatore di un utente (utile per i test)."""
    _history.pop(str(chat_id), None)


# Struttura: { "email": [timestamp1, timestamp2, ...] } — tentativi di login falliti
_failed_logins: dict[str, list[float]] = defaultdict(list)


def track_failed_login(key: str, window_seconds: int = 900) -> int:
    """
    Registra un tentativo di login fallito per `key` (es. email) e ritorna
    quanti fallimenti ci sono stati nella finestra temporale (sliding window).

    Usato per il rilevamento di breach (es. brute force): il chiamante decide
    la soglia oltre la quale considerare l'attività anomala.
    """
    now = time()
    key = str(key).lower()
    _failed_logins[key] = [t for t in _failed_logins[key] if now - t < window_seconds]
    _failed_logins[key].append(now)
    return len(_failed_logins[key])


def reset_failed_logins(key: str) -> None:
    """Azzera il contatore di fallimenti di login per `key` (es. dopo un login riuscito)."""
    _failed_logins.pop(str(key).lower(), None)
