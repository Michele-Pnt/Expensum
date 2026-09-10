"""API Reports — storico report web (settimanali/mensili) e generazione on-demand.

Blueprint leaf: legge lo store condiviso via `current_app.config["STORE"]`, mai
import diretto di `app.py`/`factory.py` (nessun ciclo).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date

from flask import Blueprint, current_app, g, jsonify, request

from src.dashboard.auth import _tg_webapp_auth
from src.dashboard.extensions import limiter
from src.storage.postgres_storage import PostgresStorage
from src.user_store import User

logger = logging.getLogger(__name__)

reports_bp = Blueprint("reports", __name__)


def _store():
    return current_app.config["STORE"]


def _is_report_locked(plan_type: str, signup: date | None, report_date_str: str | None) -> bool:
    """Piano Free: il report del mese di iscrizione è visibile per intero; dal
    secondo mese in poi viene mostrato sfocato per incentivare l'upgrade a Premium."""
    if plan_type == "pro" or not signup or not report_date_str:
        return False
    report_date = date.fromisoformat(report_date_str)
    months_since_signup = (report_date.year - signup.year) * 12 + (report_date.month - signup.month)
    return months_since_signup >= 1


@reports_bp.route("/api/reports/<share_token>", methods=["GET"])
@_tg_webapp_auth
def api_get_report_by_token(share_token: str):
    """Endpoint autenticato: restituisce un report tramite share_token, solo se
    appartiene all'utente loggato corrente (RLS + controllo esplicito di ownership)."""
    store = _store()
    with store.Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        report = storage.get_report_by_token(share_token)
        if not report or report.get("user_id") != g.chat_id:
            return jsonify({"error": "Report non trovato"}), 404
        user = s.query(User).filter_by(chat_id=report["user_id"]).first()
        signup = user.created_at.date() if user and user.created_at else None

    plan_info = store.get_user_plan(report["user_id"])
    report["plan_type"] = plan_info["plan_type"]
    report["locked"] = _is_report_locked(plan_info["plan_type"], signup, report.get("report_date"))
    report.pop("user_id", None)

    # Tracking server-side dell'apertura: è la sorgente affidabile per gli
    # achievement, al contrario dell'evento PostHog che dipende dal consenso cookie.
    # Lo unique constraint fa sì che i refresh non contino come aperture multiple.
    store.record_report_event(
        g.chat_id, share_token, report.get("report_type") or "monthly", "opened", "webapp",
    )
    return jsonify(report)


@reports_bp.route("/api/reports/generate", methods=["POST"])
@_tg_webapp_auth
@limiter.limit("5 per minute")
def api_generate_report():
    """Endpoint autenticato: genera on-demand il report weekly o monthly per l'utente
    corrente, riusando la stessa logica della routine automatica (bot.py). Nessun
    messaggio Telegram: l'utente è già in webapp, un teaser duplicherebbe l'avviso.

    Riservato al piano Premium: sul piano Free i report sono solo automatici
    (generati da noi, non a richiesta dell'utente)."""
    store = _store()
    body = request.get_json(silent=True) or {}
    report_type = body.get("type")
    if report_type not in ("weekly", "monthly"):
        return jsonify({"error": "type deve essere 'weekly' o 'monthly'"}), 400

    chat_id = g.chat_id

    if store.get_user_plan(chat_id)["plan_type"] != "pro":
        return jsonify({
            "error": "Sul piano Free i report arrivano automaticamente (ogni lunedì per il "
                     "settimanale, il 1° del mese per il mensile). Passa a Premium per generarli "
                     "quando vuoi.",
            "code": "premium_required",
        }), 403

    try:
        if report_type == "weekly":
            import bot as bot_module

            # bot=None: l'utente ha generato il report dalla webapp, sta già
            # guardando lo schermo giusto — un teaser su Telegram duplicherebbe
            # l'avviso invece di aggiungere valore.
            share_token = asyncio.run(
                bot_module._build_and_send_weekly_plan(chat_id=chat_id, bot=None, source="webapp")
            )
        else:
            if store.get_user_plan(chat_id)["tokens_remaining"] < 5000:
                return jsonify({"error": "Token mensili insufficienti per generare il report mensile."}), 402

            import main as main_module

            target_year, target_month = main_module._resolve_default_target_month(date.today())
            share_token = asyncio.run(main_module.run_agent(
                target_year, target_month, dry_run=False, chat_id=chat_id, shared_store=store,
                notify_telegram=False, source="webapp",
            ))
    except Exception as e:
        logger.exception("Errore generazione report %s on-demand per %s: %s", report_type, chat_id, e)
        return jsonify({"error": "Generazione del report fallita. Riprova tra poco."}), 500

    if not share_token:
        return jsonify({"error": "Nessun dato disponibile per generare il report di questo periodo."}), 422

    return jsonify({"ok": True, "share_token": share_token})


@reports_bp.route("/api/reports", methods=["GET"])
@_tg_webapp_auth
def api_get_reports_for_user():
    """Endpoint autenticato: lista report dell'utente corrente."""
    store = _store()
    limit = min(int(request.args.get("limit", 24)), 100)
    with store.Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        reports = storage.get_reports_for_user(user_id=g.chat_id, limit=limit)
        user = s.query(User).filter_by(chat_id=g.chat_id).first()
        signup = user.created_at.date() if user and user.created_at else None

    plan_info = store.get_user_plan(g.chat_id)
    # Omette text_content e report_data per tenere la lista leggera
    summary = [
        {
            "id": r["id"],
            "report_type": r["report_type"],
            "report_date": r["report_date"],
            "share_token": r["share_token"],
            "created_at": r["created_at"],
            "locked": _is_report_locked(plan_info["plan_type"], signup, r["report_date"]),
        }
        for r in reports
    ]
    return jsonify({"reports": summary, "plan_type": plan_info["plan_type"]})
