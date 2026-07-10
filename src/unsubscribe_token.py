"""
src/unsubscribe_token.py — Token HMAC per il link di disiscrizione email (Art. 21 GDPR).

Condiviso tra chi genera il link (bot.py, per le email drip) e chi lo verifica
(src/dashboard/app.py::unsubscribe), per evitare di duplicare la logica HMAC.
"""

import hashlib
import hmac


def make_unsubscribe_token(chat_id: str, secret_key: str) -> str:
    """Firma il chat_id con la secret key dell'app. Nessuna scadenza, nessun dato
    sensibile nel token: serve solo a impedire che chiunque possa disiscrivere un
    altro utente indovinando l'URL.
    """
    return hmac.new(secret_key.encode(), chat_id.encode(), hashlib.sha256).hexdigest()


def verify_unsubscribe_token(chat_id: str, token: str, secret_key: str) -> bool:
    """Verifica il token in tempo costante (evita timing attack)."""
    expected = make_unsubscribe_token(chat_id, secret_key)
    return hmac.compare_digest(expected, token)
