"""Estensioni Flask condivise dalla dashboard: CSRF, rate limiter, store.

Istanziate qui come singleton di modulo secondo il pattern "app factory" di Flask
(l'estensione non è legata a nessuna app finché `init_extensions()` non chiama
`init_app()`): permette a blueprint e moduli leaf di importare `csrf`/`limiter`
senza dipendere da `app.py`/`factory.py`, evitando cicli di import.
"""
from __future__ import annotations

from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect

from config import Config
from src.user_store import UserStore

csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=[])

_store: UserStore | None = None


def get_store() -> UserStore:
    """Store condiviso (utenti/config, non i dati finanziari): pool piccolo apposta,
    dashboard admin, max 2 sessioni concorrenti reali (i due cofounder) — vedi
    analisi 2026-07-16, il pool va condiviso col bot su max_connections=30."""
    global _store
    if _store is None:
        _store = UserStore(db_url=Config.DATABASE_URL, pool_size=3, max_overflow=2)
    return _store


def init_extensions(app: Flask) -> UserStore:
    """Lega csrf/limiter all'app e registra lo store condiviso in app.config["STORE"]."""
    csrf.init_app(app)
    limiter.init_app(app)
    store = get_store()
    app.config["STORE"] = store
    return store
