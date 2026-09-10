"""App factory della dashboard Flask.

`create_app()` costruisce l'istanza Flask con estensioni, error handler e hook
di sicurezza (CSRF) già configurati. Le route applicative vivono ancora in gran
parte direttamente in `app.py`, in corso di migrazione verso blueprint per area
(`src/dashboard/blueprints/`, più `admin_routes.py` già estratto): è `app.py` a
registrarle/registrarli dopo aver chiamato `create_app()`, per non introdurre un
ciclo di import finché la migrazione non è completa.
"""
from __future__ import annotations

import logging
import os
from datetime import timedelta

from flask import Flask, jsonify, request
from flask_wtf.csrf import generate_csrf
from sqlalchemy.exc import IntegrityError
from werkzeug.middleware.proxy_fix import ProxyFix

from src.dashboard.extensions import csrf, init_extensions

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    """Costruisce l'app Flask della dashboard: config, estensioni, hook globali."""
    # static_url_path sotto /admin: nginx proxya a Flask solo /admin, /auth e
    # /api (vedi deployment documentation) — lo static_url_path di default "/static" cade
    # fuori da questi prefissi e finisce sul frontend Next.js (404), lasciando
    # la dashboard admin senza CSS. Solo i template della dashboard (base.html)
    # referenziano static/, quindi spostarlo sotto /admin/static non tocca le
    # altre pagine Flask (login, register, ecc. sono self-contained).
    app = Flask(__name__, static_url_path="/admin/static")
    # Dietro nginx: senza questo, Werkzeug costruisce URL assoluti di redirect
    # (es. lo strict-slash redirect di /admin -> /admin/) usando l'host visto
    # a livello di socket (127.0.0.1:5000) invece del dominio pubblico dietro
    # il reverse proxy, facendo puntare il browser a un indirizzo irraggiungibile.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    flask_secret = os.getenv("FLASK_SECRET_KEY")
    if not flask_secret:
        raise RuntimeError(
            "FLASK_SECRET_KEY non impostata. L'app richiede una secret key "
            "persistente per firmare i cookie di sessione. Genera con "
            "`python -c 'import secrets; print(secrets.token_urlsafe(48))'` "
            "e aggiungila al .env."
        )
    app.secret_key = flask_secret
    app.config["WTF_CSRF_CHECK_DEFAULT"] = False   # CSRF applicato solo ai form, non alle JSON API
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"  # blocca invio cookie su richieste cross-origin
    app.config["SESSION_COOKIE_HTTPONLY"] = True    # cookie non accessibile da JavaScript
    app.config["SESSION_COOKIE_SECURE"] = os.getenv("FLASK_ENV") == "production"  # HTTPS only in prod
    # "Ricordami": una sessione marcata permanente (session.permanent = True) sopravvive
    # alla chiusura del browser fino a PERMANENT_SESSION_LIFETIME. Con REFRESH_EACH_REQUEST
    # la scadenza è *scorrevole*: ogni richiesta la sposta avanti di 30 giorni, quindi
    # l'utente resta loggato finché torna almeno una volta ogni 30 giorni. Senza spuntare
    # "ricordami" la sessione resta un cookie di sessione del browser (muore alla chiusura).
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
    app.config["SESSION_REFRESH_EACH_REQUEST"] = True

    init_extensions(app)

    @app.errorhandler(IntegrityError)
    def _handle_integrity_error(exc: IntegrityError):
        """Violazione di vincolo DB → 409 con un messaggio utile, non un 500 opaco.

        Il caso tipico è la cancellazione di una categoria ancora referenziata da spese
        (foreign key RESTRICT): senza questo handler il client riceveva un 500 e la
        webapp mostrava "Errore sconosciuto". Il dettaglio del vincolo resta nei log,
        fuori dalla risposta: contiene nomi di tabella e valori non destinati al client.
        """
        logger.warning(
            "Violazione di vincolo su %s %s: %s",
            request.method, request.path, exc.orig,
            extra={"domain": "app", "event": "integrity_error",
                   "meta": {"path": request.path, "method": request.method}},
        )
        return jsonify({
            "error": "Operazione in conflitto con dati esistenti",
            "detail": "Il record è ancora collegato ad altri dati oppure viola un vincolo di unicità.",
        }), 409

    @app.before_request
    def enforce_csrf_on_forms():
        """Applica CSRF ai form HTML e alle API autenticate via cookie di sessione browser.

        Le richieste /api/* che portano l'header X-Telegram-Init-Data sono esenti:
        un sito malevolo non può impostare header custom su richieste cross-origin,
        quindi quel canale di autenticazione non è sfruttabile da CSRF. Quando invece
        la stessa pagina viene aperta in un browser normale (fuori dalla WebView
        Telegram), l'header manca e l'autenticazione ricade sul cookie di sessione,
        che torna vulnerabile esattamente come le rotte protette dai form HTML.
        """
        if not app.config.get("WTF_CSRF_ENABLED", True):
            # Rispetta il flag standard Flask-WTF: protect() chiamato manualmente
            # (come qui sotto) non lo controlla di suo, a differenza dell'hook
            # automatico di CSRFProtect. Senza questo check, WTF_CSRF_ENABLED=False
            # nei test è inerte e ogni POST richiede comunque un token valido.
            return
        if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
            return
        if request.path == "/auth/telegram-login":
            return
        if request.path.startswith("/api/") and request.headers.get("X-Telegram-Init-Data"):
            return
        if request.path.startswith("/webhooks/"):
            # Chiamate server-to-server (Tally, ecc.), non autenticate via cookie di
            # sessione browser: la protezione CSRF non si applica per definizione.
            return
        csrf.protect()

    @app.route("/api/csrf-token", methods=["GET"])
    def api_csrf_token():
        """Restituisce un token CSRF per la sessione browser corrente.

        Usato dalle pagine Next.js che non possono leggere {{ csrf_token() }} via Jinja.
        """
        return jsonify({"csrf_token": generate_csrf()})

    @app.after_request
    def skip_ngrok_interstitial(response):
        response.headers["ngrok-skip-browser-warning"] = "true"
        return response

    return app
