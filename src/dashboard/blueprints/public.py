"""Route pubbliche/anonime della dashboard: stats social proof, tracking analytics,
webhook Tally (waitlist beta) e Stripe (stub), unsubscribe email.

Blueprint leaf: legge lo store condiviso via `current_app.config["STORE"]`, mai
import diretto di `app.py`/`factory.py` (nessun ciclo). Stesso principio di
disaccoppiamento già usato da `admin_routes.py`.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
import uuid

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func

from config import Config
from src import analytics, beta_access, brevo_client
from src.dashboard.auth import _get_session_chat_id
from src.dashboard.extensions import limiter
from src.dashboard.referrals import _send_referral_reward_emails
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
# Webhook Tally (waitlist beta)
# ---------------------------------------------------------------------------

def _extract_tally_email(fields: list) -> str | None:
    """Estrae l'email dai campi di un submit Tally (per tipo o label)."""
    for field in fields:
        if not isinstance(field, dict):
            continue
        if field.get("type") == "INPUT_EMAIL":
            value = field.get("value")
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
    for field in fields:
        if not isinstance(field, dict):
            continue
        label = (field.get("label") or "").strip().lower()
        value = field.get("value")
        if "email" in label and isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


def _extract_tally_name(fields: list) -> str:
    """Estrae il nome dai campi di un submit Tally (per label), stringa vuota se assente."""
    for field in fields:
        if not isinstance(field, dict):
            continue
        label = (field.get("label") or "").strip().lower()
        value = field.get("value")
        if "nome" in label and isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_tally_ref(fields: list) -> str | None:
    """Estrae il codice referral (campo hidden 'ref') da un submit Tally, se presente."""
    for field in fields:
        if not isinstance(field, dict):
            continue
        key = (field.get("key") or "").strip().lower()
        label = (field.get("label") or "").strip().lower()
        value = field.get("value")
        if ("ref" in key or "ref" in label) and isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _sync_tally_lead_to_brevo(tally_submission_id: str, email: str, name: str = "") -> None:
    """Sincronizza un lead Tally su Brevo e, se sotto il tetto configurato,
    crea subito l'account beta e invia le credenziali (in background: risponde
    subito 200 a Tally, che ha timeout stretti sul webhook, senza far dipendere
    l'ack dalla latenza di Brevo).
    """
    store = _store()
    try:
        brevo_client.upsert_contact(email, list_ids=[Config.BREVO_BETA_WAITLIST_LIST_ID])
        store.mark_tally_lead_synced(tally_submission_id)
    except Exception:
        logger.exception(
            "Errore sync lead Tally verso Brevo",
            extra={"domain": "dashboard", "event": "tally_brevo_sync_failed"},
        )

    if not Config.AUTO_BETA_ACCESS_ENABLED:
        return

    try:
        if store.count_beta_accounts_granted() >= Config.AUTO_BETA_ACCESS_MAX_ACCOUNTS:
            logger.warning(
                "Tetto account beta automatici raggiunto, nessuna creazione",
                extra={"domain": "dashboard", "event": "beta_access_cap_reached"},
            )
            return
        granted = beta_access.grant_beta_access(store, email, name)
        if granted:
            store.mark_tally_lead_beta_access_granted(tally_submission_id)
            logger.info(
                "Account beta creato automaticamente da lead Tally",
                extra={"domain": "dashboard", "event": "beta_access_auto_granted"},
            )
    except Exception:
        logger.exception(
            "Errore creazione account beta automatica",
            extra={"domain": "dashboard", "event": "beta_access_auto_failed"},
        )

    # L'account beta appena creato (o già esistente) potrebbe sbloccare reward
    # referral rimasti 'pending' (come 'referred' o come 'referrer' in attesa).
    try:
        applied = store.apply_pending_referral_rewards(email)
        if applied:
            _send_referral_reward_emails(applied, unlocked_lifetime_founder_email=None)
    except Exception:
        logger.exception(
            "Errore applicazione reward referral pendenti",
            extra={"domain": "dashboard", "event": "referral_reward_apply_failed"},
        )


@public_bp.route("/webhooks/tally", methods=["POST"])
@limiter.limit("60 per minute")
def webhook_tally():
    """Riceve i submit del form Tally (waitlist beta) e sincronizza il lead su Brevo.

    Chiamata server-to-server da Tally, non autenticata via cookie di sessione
    (vedi carve-out in enforce_csrf_on_forms). Idempotente su submissionId:
    i retry del webhook Tally non generano doppie righe né doppi sync.
    """
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

    store = _store()
    payload = request.get_json(silent=True) or {}
    data = payload.get("data") or {}
    submission_id = data.get("submissionId")
    if not submission_id or not isinstance(submission_id, str):
        return jsonify({"error": "missing submissionId"}), 400

    fields = data.get("fields") or []
    email = _extract_tally_email(fields) if isinstance(fields, list) else None
    name = _extract_tally_name(fields) if isinstance(fields, list) else ""
    ref = _extract_tally_ref(fields) if isinstance(fields, list) else None

    lead, is_new = store.save_tally_lead(
        tally_submission_id=submission_id,
        email=email,
        raw_payload=json.dumps(payload),
        referral_code=secrets.token_urlsafe(6),
        referred_by_code=ref,
    )

    logger.info(
        "Lead Tally ricevuto",
        extra={
            "domain": "dashboard",
            "event": "tally_lead_received",
            "meta": {"is_new": is_new, "has_email": bool(email), "has_ref": bool(ref)},
        },
    )

    # Attribuzione referral: va fatta sincrona (non nel thread di background) così
    # i ReferralReward esistono già prima che _sync_tally_lead_to_brevo tenti di
    # applicarli alla creazione dell'account beta.
    if is_new and ref:
        referrer_lead = store.get_tally_lead_by_referral_code(ref)
        # Il confronto sulle email è la guardia vera contro l'auto-invito: due submit
        # della stessa persona producono lead con id diversi. `create_referral_rewards`
        # ricontrolla comunque, questa è solo la prima linea.
        same_person = (
            referrer_lead is not None
            and (referrer_lead.email or "").strip().lower() == (email or "").strip().lower()
        )
        if referrer_lead and referrer_lead.id != lead.id and not same_person:
            try:
                result = store.create_referral_rewards(lead, referrer_lead)
                unlocked_email = referrer_lead.email if result.get("lifetime_founder_unlocked") else None
                if unlocked_email:
                    threading.Thread(
                        target=_send_referral_reward_emails,
                        args=([], unlocked_email),
                        daemon=True,
                    ).start()
            except Exception:
                logger.exception(
                    "Errore creazione reward referral",
                    extra={"domain": "dashboard", "event": "referral_rewards_create_failed"},
                )

    if is_new and email:
        threading.Thread(
            target=_sync_tally_lead_to_brevo,
            args=(submission_id, email, name),
            daemon=True,
        ).start()

    return jsonify({"ok": True})


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
