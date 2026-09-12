"""Impostazioni account, diritti dell'interessato GDPR (Art. 15/17/20), link
referral, dati demo, preferenze utente.

Blueprint leaf: legge lo store condiviso via `current_app.config["STORE"]`, mai
import diretto di `app.py`/`factory.py` (nessun ciclo).
"""
from __future__ import annotations

import re

from flask import Blueprint, Response, current_app, jsonify, request, session

from config import Config
from src.dashboard.auth import _get_user_by_chat_id, _resolve_request_chat_id
from src.dashboard.budget_validation import _category_budget_total_for_user, _parse_money
from src.dashboard.extensions import limiter
from src.dashboard.storage import _get_storage_for_chat
from src.privacy_export import (
    CSV_HEADER,
    NOTION_CSV_UNAVAILABLE_MESSAGE,
    build_csv_rows,
    build_export_json,
)
from src.user_store import User

privacy_bp = Blueprint("privacy", __name__)


def _store():
    return current_app.config["STORE"]


# ---------------------------------------------------------------------------
# Settings API
# ---------------------------------------------------------------------------

@privacy_bp.route("/api/settings", methods=["GET"])
def api_settings_get():
    """Dati account e piano per la pagina Impostazioni."""
    store = _store()
    chat_id, auth_mode = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    with store.Session() as s:
        user = s.query(User).filter_by(chat_id=chat_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404

        telegram_connected = not str(chat_id).startswith("web_")
        name_parts = (user.username or "").strip().split(" ", 1)
        first_name = name_parts[0] if name_parts else None
        last_name = name_parts[1] if len(name_parts) > 1 else None

    plan = store.get_user_plan(chat_id)
    reset_at = plan.get("tokens_reset_at")
    tokens_usage_percent = 0
    tokens_total = plan.get("tokens_total", 1)
    if tokens_total:
        used = plan.get("tokens_used_current_cycle", 0) + plan.get("tokens_reserved_current_cycle", 0)
        tokens_usage_percent = round(used / tokens_total * 100, 1)

    return jsonify({
        "chat_id": chat_id,
        "auth_mode": auth_mode,
        "account": {
            "email": user.email if hasattr(user, "email") else None,
            "first_name": first_name,
            "last_name": last_name,
            "telegram_connected": telegram_connected,
            "telegram_chat_id": chat_id if telegram_connected else None,
            "storage_backend": user.storage_backend,
            "is_active": user.is_active,
            "privacy_policy_version_accepted": user.privacy_policy_version_accepted,
            "privacy_policy_current_version": Config.CURRENT_PRIVACY_POLICY_VERSION,
            "tos_version_accepted": user.tos_version_accepted,
            "tos_current_version": Config.CURRENT_TOS_VERSION,
        },
        "plan": {
            "plan_type": plan.get("plan_type", "free"),
            "tokens_total": tokens_total,
            "tokens_used_current_cycle": plan.get("tokens_used_current_cycle", 0),
            "tokens_reserved_current_cycle": plan.get("tokens_reserved_current_cycle", 0),
            "tokens_remaining": plan.get("tokens_remaining", 0),
            "tokens_usage_percent": tokens_usage_percent,
            "tokens_reset_at": reset_at.isoformat() if reset_at else None,
            "alert": plan.get("alert"),
        },
    })


@privacy_bp.route("/api/telegram/link", methods=["POST"])
def api_telegram_link():
    """Genera un deep link per collegare l'account web corrente a Telegram."""
    store = _store()
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    if not str(chat_id).startswith("web_"):
        return jsonify({"already_linked": True})

    if not Config.TELEGRAM_BOT_USERNAME:
        return jsonify({"error": "Telegram bot non configurato"}), 500

    state = store.create_oauth_session(chat_id)
    link = f"https://t.me/{Config.TELEGRAM_BOT_USERNAME}?start=link_{state}"
    return jsonify({"already_linked": False, "link": link})


@privacy_bp.route("/api/settings/logout", methods=["POST"])
def api_settings_logout():
    """Sospende l'account (is_active=False) e invalida la sessione corrente."""
    store = _store()
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    store.logout_user(chat_id)
    session.clear()
    return jsonify({"ok": True, "redirect_url": "/login"})


@privacy_bp.route("/api/settings/change-name", methods=["POST"])
@limiter.limit("5 per minute")
def api_settings_change_name():
    """Aggiorna nome e cognome dell'account (diritto di rettifica, Art. 16 GDPR)."""
    store = _store()
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    first_name = (body.get("first_name") or "").strip()
    last_name = (body.get("last_name") or "").strip()

    if not first_name:
        return jsonify({"error": "Il nome non può essere vuoto."}), 400

    new_name = f"{first_name} {last_name}".strip()

    with store.Session() as s:
        user = s.query(User).filter_by(chat_id=chat_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404
        old_name = user.username

    store.update_username(chat_id, new_name)
    store.write_audit_log(
        chat_id, actor="user", action="change_name",
        metadata={"old_name": old_name, "new_name": new_name},
        ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent"),
    )
    return jsonify({"ok": True})


@privacy_bp.route("/api/settings/change-email", methods=["POST"])
@limiter.limit("5 per minute")
def api_settings_change_email():
    """Cambia l'email dell'account. Richiede la password corrente per re-autenticazione."""
    store = _store()
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    new_email = (body.get("new_email") or "").strip().lower()
    current_password = body.get("current_password") or ""

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", new_email):
        return jsonify({"error": "Email non valida."}), 400

    with store.Session() as s:
        user = s.query(User).filter_by(chat_id=chat_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404
        old_email = user.email

    if not old_email or not store.verify_password(old_email, current_password):
        return jsonify({"error": "Password corrente errata."}), 401

    if store.get_user_by_email_any_status(new_email):
        return jsonify({"error": "Email già in uso."}), 409

    store.update_email(chat_id, new_email)
    store.write_audit_log(
        chat_id, actor="user", action="change_email",
        metadata={"old_email": old_email, "new_email": new_email},
        ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent"),
    )
    return jsonify({"ok": True})


@privacy_bp.route("/api/settings/change-password", methods=["POST"])
@limiter.limit("5 per minute")
def api_settings_change_password():
    """Cambia la password dell'account. Richiede la password corrente per re-autenticazione."""
    store = _store()
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    current_password = body.get("current_password") or ""
    new_password = body.get("new_password") or ""

    if len(new_password) < 8:
        return jsonify({"error": "La nuova password deve essere di almeno 8 caratteri."}), 400

    with store.Session() as s:
        user = s.query(User).filter_by(chat_id=chat_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404
        email = user.email

    if not email or not store.verify_password(email, current_password):
        return jsonify({"error": "Password corrente errata."}), 401

    # update_password incrementa token_version: tutte le sessioni esistenti
    # (compresa questa) vengono invalidate. Riallineo la sessione del device
    # corrente al nuovo valore così chi cambia password non viene sloggato,
    # mentre gli altri dispositivi sì.
    store.update_password(chat_id, new_password)
    if session.get("user_logged_in"):
        session["token_version"] = store.get_token_version(chat_id)
    store.write_audit_log(
        chat_id, actor="user", action="change_password",
        ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent"),
    )
    return jsonify({"ok": True})


@privacy_bp.route("/api/settings/logout-all-devices", methods=["POST"])
def api_settings_logout_all_devices():
    """Revoca tutte le sessioni dell'utente su ogni dispositivo, inclusa questa.

    Incrementa `token_version`: ogni cookie di sessione emesso in precedenza
    diventa invalido al confronto in `_get_session_chat_id`. A differenza di
    /api/settings/logout NON sospende l'account (is_active resta True).
    """
    store = _store()
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    store.bump_token_version(chat_id)
    store.write_audit_log(
        chat_id, actor="user", action="logout_all_devices",
        ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent"),
    )
    session.clear()
    return jsonify({"ok": True, "redirect_url": "/login"})


@privacy_bp.route("/api/settings/delete-account", methods=["POST"])
@privacy_bp.route("/api/privacy/delete-account", methods=["POST"])
def api_settings_delete_account():
    """Elimina definitivamente account e dati locali. Richiede confirm='DELETE'.

    Esposto anche sotto /api/privacy/delete-account (Art. 17 GDPR) per coerenza
    col namespace degli altri endpoint diritti interessato.
    """
    store = _store()
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    if (body.get("confirm") or "").strip().upper() != "DELETE":
        return jsonify({"error": "Conferma non valida. Scrivi DELETE per procedere."}), 400

    # Audit log PRIMA della cancellazione: dopo, la riga users non esiste più.
    store.write_audit_log(
        chat_id, actor="user", action="delete_account",
        ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent"),
    )

    result = store.delete_user_completely(chat_id)
    if result == "not_found":
        return jsonify({"error": "Utente non trovato."}), 404

    session.clear()
    return jsonify({"ok": True, "redirect_url": "/login"})


# ---------------------------------------------------------------------------
# Privacy API — diritti dell'interessato (GDPR Art. 15, 17, 20)
# ---------------------------------------------------------------------------

@privacy_bp.route("/api/privacy/accept-policy", methods=["POST"])
def api_privacy_accept_policy():
    """Art. 7 GDPR — registra l'accettazione esplicita della versione corrente della privacy policy."""
    store = _store()
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    version = Config.CURRENT_PRIVACY_POLICY_VERSION
    store.accept_privacy_policy(chat_id, version)
    store.write_audit_log(
        chat_id, actor="user", action="consent_change",
        metadata={"consent_type": "privacy_policy", "version": version},
        ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent"),
    )
    return jsonify({"ok": True, "privacy_policy_version_accepted": version})


@privacy_bp.route("/api/privacy/accept-tos", methods=["POST"])
def api_privacy_accept_tos():
    """GDPR Art. 7 — registra l'accettazione esplicita della versione corrente dei ToS."""
    store = _store()
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    version = Config.CURRENT_TOS_VERSION
    store.accept_terms_of_service(chat_id, version)
    store.write_audit_log(
        chat_id, actor="user", action="consent_change",
        metadata={"consent_type": "terms_of_service", "version": version},
        ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent"),
    )
    return jsonify({"ok": True, "tos_version_accepted": version})


@privacy_bp.route("/api/privacy/export-json", methods=["GET"])
@limiter.limit("5 per minute")
def api_privacy_export_json():
    """Art. 15 GDPR — copia completa dei dati personali dell'utente."""
    store = _store()
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    with store.Session() as s:
        user = s.query(User).filter_by(chat_id=chat_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404
        export_data = build_export_json(s, user)

    store.write_audit_log(
        chat_id, actor="user", action="export_json",
        ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent"),
    )
    return jsonify(export_data)


@privacy_bp.route("/api/privacy/export-csv", methods=["GET"])
@limiter.limit("5 per minute")
def api_privacy_export_csv():
    """Art. 20 GDPR — transazioni dell'utente in formato CSV portabile."""
    import csv
    import io
    from datetime import date

    store = _store()
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    with store.Session() as s:
        user = s.query(User).filter_by(chat_id=chat_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404
        rows = build_csv_rows(s, user)

    if rows is None:
        return jsonify({"error": NOTION_CSV_UNAVAILABLE_MESSAGE}), 404

    store.write_audit_log(
        chat_id, actor="user", action="export_csv",
        ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent"),
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_HEADER)
    for row in rows:
        writer.writerow(row)

    filename = f"expensum_export_{date.today().isoformat()}.csv"
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# Referral, dati demo, preferenze utente
# ---------------------------------------------------------------------------

@privacy_bp.route("/api/referral/link", methods=["GET"])
def api_referral_link():
    """Ritorna il link referral personale dell'utente autenticato e il suo stato
    (quante persone ha già invitato, se ha sbloccato Lifetime Founder garantito).

    Mostrato nella schermata di condivisione on-site (fine onboarding /
    impostazioni): l'utente deve essere già autenticato, il referral è un
    beneficio per chi è già un utente Expensum.
    """
    store = _store()
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401
    user = _get_user_by_chat_id(chat_id)
    if not user or not user.email:
        return jsonify({"error": "User not found"}), 404

    status = store.get_referral_status(user.email)
    link = f"{Config.WEBAPP_BASE_URL}?ref={status['referral_code']}"
    return jsonify({
        "referral_code": status["referral_code"],
        "link": link,
        "referred_count": status["referred_count"],
        "lifetime_founder_guaranteed": status["lifetime_founder_guaranteed"],
    })


@privacy_bp.route("/api/demo/load", methods=["POST"])
def api_demo_load():
    """Carica 30 giorni di spese demo (prefissate [Demo]) per l'utente."""
    store = _store()
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        from src.demo_data import load_demo_data
        storage = _get_storage_for_chat(chat_id)
        count = load_demo_data(storage)
        store.set_has_demo_data(chat_id, True)
        return jsonify({"ok": True, "expense_count": count})
    except Exception as e:
        current_app.logger.warning("[User %s] Errore caricamento demo data: %s", chat_id, e)
        return jsonify({"ok": False, "error": str(e)}), 500


@privacy_bp.route("/api/demo/clear", methods=["POST"])
def api_demo_clear():
    """Cancella le spese demo (prefissate [Demo]) e resetta il flag has_demo_data."""
    store = _store()
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        storage = _get_storage_for_chat(chat_id)
        count = store.clear_demo_data(chat_id, storage)
        return jsonify({"ok": True, "deleted": count})
    except Exception as e:
        current_app.logger.warning("[User %s] Errore pulizia demo data: %s", chat_id, e)
        return jsonify({"ok": False, "error": str(e)}), 500


@privacy_bp.route("/api/user/preferences", methods=["GET"])
def api_user_preferences_get():
    """Restituisce le preferenze utente."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(_store().get_user_preferences(chat_id))


@privacy_bp.route("/api/user/preferences", methods=["PUT"])
def api_user_preferences_put():
    """Aggiorna le preferenze utente."""
    store = _store()
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    if "monthly_budget" in body and body["monthly_budget"] not in (None, ""):
        monthly_budget, error = _parse_money(body["monthly_budget"], "monthly_budget")
        if error:
            return error
        category_budget_total = _category_budget_total_for_user(chat_id)
        if category_budget_total > 0 and monthly_budget is not None and monthly_budget < category_budget_total:
            return jsonify({
                "error": (
                    "Il budget mensile generale non puo' essere minore della somma "
                    "dei budget categoria."
                ),
                "minimum_budget": float(category_budget_total),
            }), 400
        body["monthly_budget"] = float(monthly_budget)
    body.pop("step", None)
    store.update_user_preferences(chat_id, body)
    return jsonify({"status": "ok"})
