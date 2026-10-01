"""Route pubbliche/anonime della dashboard: stats, analytics e webhook legacy.

Blueprint leaf: legge lo store condiviso via `current_app.config["STORE"]`, mai
import diretto di `app.py`/`factory.py` (nessun ciclo). Stesso principio di
disaccoppiamento già usato da `admin_routes.py`.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import time
import uuid

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func

from config import Config
from src import analytics
from src.dashboard.auth import _get_session_chat_id
from src.dashboard.extensions import limiter
from src.user_store import User

logger = logging.getLogger(__name__)

public_bp = Blueprint("public", __name__)


def _store():
    return current_app.config["STORE"]


def _is_valid_tally_signature(raw_body: bytes, received_signature: str, secret: str) -> bool:
    """Verifica la firma HMAC-SHA256 Base64 del payload webhook Tally."""
    if not received_signature or not secret:
        return False
    expected_signature = base64.b64encode(
        hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(expected_signature, received_signature)


# ---------------------------------------------------------------------------
# Webhook Tally (retired legacy channel)
# ---------------------------------------------------------------------------
# /api/public/stats
# ---------------------------------------------------------------------------

_public_stats_cache: dict | None = None
_PUBLIC_STATS_TTL_SECONDS = 300


@public_bp.route("/api/public/stats", methods=["GET"])
@limiter.limit("30 per minute")
def api_public_stats():
    """Statistiche pubbliche aggregate per il social proof sulla landing page.

    Conta tx_events.outcome='confirmed', NON la tabella `expenses`: `expenses`
    esiste solo per gli utenti su backend Postgres, ma storage_backend di
    default è 'notion' (vedi User.storage_backend), quindi `expenses` è quasi
    sempre vuota e il conteggio risultava 0. `tx_events` è l'unica tabella
    pensata cross-backend (Notion + Postgres, vedi sua docstring): esiste solo
    dal 14/07/2026, quindi parte basso, ma è l'unico numero onesto e cresce
    correttamente da qui in avanti su entrambi i backend. Cache in-memory con
    TTL perché la rotta è pubblica, non autenticata, e potenzialmente ad alto
    traffico.
    """
    from src.user_store import TxEvent

    global _public_stats_cache
    now = time.time()
    if _public_stats_cache and now - _public_stats_cache["ts"] < _PUBLIC_STATS_TTL_SECONDS:
        return jsonify(_public_stats_cache["data"])

    with _store().Session() as s:
        total_confirmed = s.query(func.count(TxEvent.id)).filter(
            TxEvent.outcome == "confirmed"
        ).scalar() or 0

    data = {"total_expenses_tracked": int(total_confirmed)}
    _public_stats_cache = {"ts": now, "data": data}
    return jsonify(data)


# ---------------------------------------------------------------------------
# /api/track
# ---------------------------------------------------------------------------

_TRACK_EVENT_RE = re.compile(r"^[a-z0-9_]{1,64}$")


@public_bp.route("/api/track", methods=["POST"])
@limiter.limit("60 per minute")
def api_track():
    """Riceve un evento di analytics dal frontend e lo inoltra server-side.

    Il browser non parla mai direttamente con PostHog/Meta: questa rotta è
    same-origin, la CSP non concede script-src/connect-src a quei domini.
    GA4 fa eccezione: gtag.js viene caricato lato browser (solo dopo consenso
    "analytics", vedi CookieConsent.tsx) perché serve a calcolare sessioni e
    provenienza del traffico, impossibili da ricostruire da qui. Per questo
    il page_view "grezzo" NON viene rinoltrato a GA4 in questa rotta: lo
    gestisce già gtag.js in autonomia, rimandarlo duplicherebbe il conteggio.
    Tutti gli altri eventi (custom di prodotto) continuano ad arrivare a GA4
    da qui, invariato. PostHog resta gated dallo stesso consenso "analytics"
    del banner, non è esente solo perché la chiamata è server-side.
    """
    data = request.get_json(silent=True) or {}
    event = data.get("event", "")
    if not _TRACK_EVENT_RE.match(event):
        return jsonify({"error": "invalid event name"}), 400

    properties = data.get("properties") or {}
    if not isinstance(properties, dict):
        return jsonify({"error": "invalid properties"}), 400

    anonymous_id = data.get("anonymous_id")
    session_chat_id = _get_session_chat_id()
    distinct_id = session_chat_id or anonymous_id
    if not distinct_id or not isinstance(distinct_id, str) or len(distinct_id) > 128:
        return jsonify({"error": "missing distinct id"}), 400

    consent = data.get("consent") or {}
    if consent.get("analytics"):
        properties.setdefault("platform", "web")
        if event == "identify":
            analytics.identify(distinct_id, properties)
            return jsonify({"ok": True})
        analytics.track(distinct_id, event, properties)
        if event != "page_view":
            # page_view lo gestisce già gtag.js lato browser (vedi docstring).
            analytics.track_ga4(distinct_id, event, properties)
        # Il tour guidato webapp prima viveva solo in localStorage: questi eventi
        # rispecchiano lo stato in Postgres (solo per sessioni autenticate, mai
        # per visitatori anonimi) così la dashboard admin sa chi lo salta e a
        # quale step si ferma. Vedi frontend/src/context/TourContext.tsx.
        if session_chat_id and event.startswith("tour_"):
            _store().record_tour_event(session_chat_id, event, properties.get("step_id"))
    if consent.get("marketing"):
        event_id = data.get("event_id") or str(uuid.uuid4())
        analytics.track_meta(event, event_id, properties)

    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Webhook Tally (retired legacy channel)
# ---------------------------------------------------------------------------
@public_bp.route("/webhooks/tally", methods=["POST"])
@limiter.limit("60 per minute")
def webhook_tally():
    """Reject the retired Tally account-provisioning channel after signature checks."""
    signing_secret = Config.TALLY_WEBHOOK_SIGNING_SECRET
    if not signing_secret:
        logger.error(
            "Webhook Tally non configurato",
            extra={"domain": "security", "event": "tally_webhook_secret_missing", "meta": {}},
        )
        return jsonify({"error": "webhook_not_configured"}), 503

    raw_body = request.get_data(cache=True)
    received_signature = request.headers.get("Tally-Signature", "")
    if not _is_valid_tally_signature(raw_body, received_signature, signing_secret):
        logger.warning(
            "Firma webhook Tally non valida",
            extra={"domain": "security", "event": "tally_webhook_signature_invalid", "meta": {}},
        )
        return jsonify({"error": "invalid_webhook_signature"}), 401

    logger.info(
        "Canale Tally dismesso",
        extra={"domain": "dashboard", "event": "tally_webhook_retired", "meta": {}},
    )
    return jsonify({"error": "tally_registration_retired"}), 410


# ---------------------------------------------------------------------------
# /unsubscribe
# ---------------------------------------------------------------------------

def _set_notifications_enabled(chat_id: str, enabled: bool) -> None:
    """Aggiorna il flag notifications_enabled per chat_id (usato da /unsubscribe)."""
    with _store().Session() as session:
        user = session.query(User).filter(User.chat_id == str(chat_id)).first()
        if not user:
            return
        user.notifications_enabled = enabled
        session.commit()


@public_bp.route("/unsubscribe", methods=["GET"])
def unsubscribe():
    """Disattiva le notifiche (Telegram + email) senza richiedere login.

    Il link viene inviato nelle email di lifecycle/marketing (drip trial) con un token
    firmato sul chat_id, verificabile da chiunque riceva l'email ma non falsificabile.
    """
    from src.unsubscribe_token import verify_unsubscribe_token

    chat_id = request.args.get("chat_id", "").strip()
    token = request.args.get("token", "").strip()
    if not chat_id or not token:
        return jsonify({"error": "missing chat_id or token"}), 400

    if not verify_unsubscribe_token(chat_id, token, current_app.secret_key):
        return jsonify({"error": "invalid token"}), 403

    _set_notifications_enabled(chat_id, False)

    logger.info(
        "Utente disiscritto dalle notifiche via link email",
        extra={"domain": "dashboard", "event": "unsubscribe_via_email_link"},
    )
    return "Notifiche disattivate. Puoi riattivarle in qualsiasi momento dalle impostazioni.", 200


# ---------------------------------------------------------------------------
# Webhook Stripe (stub)
# ---------------------------------------------------------------------------

@public_bp.route("/webhooks/stripe", methods=["POST"])
def webhook_stripe():
    """Stub webhook Stripe — scaffolding inerte finché non si esce dalla beta.

    Nessuna verifica firma né logica di business qui: risponde 503 finché
    STRIPE_API_KEY non è configurata. La vera integrazione (Checkout Session,
    verifica firma webhook, wiring set_user_plan) è tracciata come task separato.
    """
    if not Config.STRIPE_API_KEY:
        logger.info(
            "Webhook Stripe ricevuto ma non ancora attivo (beta mode)",
            extra={"domain": "dashboard", "event": "stripe_webhook_disabled"},
        )
        return jsonify({"error": "not_available_yet"}), 503

    # TODO: verifica firma webhook + gestione eventi (post-beta, task pagamenti Stripe)
    return jsonify({"error": "not_implemented"}), 501
