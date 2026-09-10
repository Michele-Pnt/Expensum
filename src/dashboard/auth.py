"""Autenticazione condivisa delle route dashboard: Telegram WebApp init-data e sessione browser.

Modulo leaf: legge lo store condiviso via `current_app.config["STORE"]`, non importa
mai `app.py`/`factory.py` né i blueprint (evita cicli di import). Segue lo stesso
principio di disaccoppiamento già usato da `admin_routes.py`/`admin_metrics.py`.
"""
from __future__ import annotations

import hashlib
import hmac
import json as _json
from functools import wraps
from urllib.parse import unquote

from flask import current_app, g, jsonify, request, session

from config import Config


def _store():
    return current_app.config["STORE"]


def _validate_telegram_init_data(init_data_raw: str) -> dict | None:
    """Valida HMAC-SHA256 di Telegram WebApp initData e ritorna i campi parsati.

    Spec: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    token = Config.TELEGRAM_BOT_TOKEN.encode()
    secret_key = hmac.new(b"WebAppData", token, hashlib.sha256).digest()

    params: dict[str, str] = {}
    received_hash: str | None = None
    for part in init_data_raw.split("&"):
        if "=" not in part:
            continue
        k, _, v = part.partition("=")
        if k == "hash":
            received_hash = v
        else:
            params[k] = unquote(v)  # signature inclusa nel dcs (Bot API 7.0+)

    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        return None

    user_json = params.get("user", "{}")
    try:
        user_data = _json.loads(unquote(user_json))
    except Exception:
        user_data = {}

    return {"user": user_data, "chat_id": str(user_data.get("id", ""))}


def _user_has_web_access(user) -> bool:
    """La web app è riservata agli utenti con backend PostgreSQL.

    Chi ha collegato Notion gestisce le finanze esclusivamente dal bot Telegram
    e dal proprio workspace Notion: per questi utenti la web app (login browser,
    chat, onboarding, analytics, gestione spazi, impostazioni) non è disponibile.
    """
    return bool(user) and user.storage_backend != "notion"


def _get_user_by_chat_id(chat_id: str):
    from src.user_store import User

    with _store().Session() as s:
        return s.query(User).filter_by(chat_id=chat_id).first()


def _get_session_chat_id() -> str | None:
    """Ritorna il chat_id della sessione browser se valida.

    Oltre al flag di login, verifica la `token_version`: il valore salvato nel
    cookie al login deve combaciare con quello corrente nel DB. In caso contrario
    la sessione è stata revocata (cambio password, "esci da tutti i dispositivi")
    o è una sessione legacy anteriore all'introduzione del meccanismo: in entrambi
    i casi va invalidata forzando un nuovo login.
    """
    if not session.get("user_logged_in"):
        return None
    chat_id = session.get("chat_id")
    if not chat_id:
        return None
    current_version = _store().get_token_version(chat_id)
    if current_version is None or session.get("token_version") != current_version:
        session.clear()
        return None
    return str(chat_id)


def _resolve_request_chat_id() -> tuple[str | None, str | None]:
    """Risolvi utente autenticato via Telegram WebApp o sessione browser."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if init_data:
        parsed = _validate_telegram_init_data(init_data)
        if parsed and parsed.get("chat_id"):
            chat_id = str(parsed["chat_id"])
            # Gli utenti Notion non hanno accesso alla web app: nega la risoluzione
            # così ogni endpoint risponde 401 anche via Telegram WebApp.
            if not _user_has_web_access(_get_user_by_chat_id(chat_id)):
                return None, None
            return chat_id, "telegram"

    chat_id = _get_session_chat_id()
    if not chat_id:
        return None, None

    user = _get_user_by_chat_id(chat_id)
    if not user:
        session.clear()
        return None, None
    if not _user_has_web_access(user):
        return None, None
    return chat_id, "browser"


def _tg_webapp_auth(f):
    """Decorator: autentica via Telegram WebApp o sessione browser."""
    @wraps(f)
    def decorated(*args, **kwargs):
        chat_id, auth_mode = _resolve_request_chat_id()
        if not chat_id:
            return jsonify({"error": "Unauthorized"}), 401
        g.chat_id = chat_id
        g.auth_mode = auth_mode
        return f(*args, **kwargs)
    return decorated
