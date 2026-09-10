"""Blueprint della dashboard admin di Expensum.

Raccoglie tutte le route `/admin/*` (tranne login/logout, che restano in app.py
accanto al rate limiter e all'audit log). La logica di aggregazione vive in
`admin_metrics.py`: qui si orchestra soltanto (apertura sessione + render).

Disaccoppiamento dal monolite `app.py`:
- lo `store` condiviso è letto da `current_app.config["STORE"]` (nessun import
  di app.py → nessun ciclo di import, una sola connessione DB);
- la guardia admin è una piccola funzione locale (`_admin_required`) che replica
  il check di sessione, così il blueprint non dipende da app.py.
"""
from __future__ import annotations

import json
import os
from collections import deque
from datetime import date
from functools import wraps
from typing import Any

import psutil
from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import text

from config import Config
from src.dashboard import admin_metrics
from src.notification_service import create_notification
from src.user_store import Feedback, User

admin_bp = Blueprint("admin", __name__)


def _admin_required(f):
    """Guardia admin locale: redirect a /admin/login se non autenticati."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("auth.admin_login"))
        return f(*args, **kwargs)
    return wrapper


def _store():
    """Ritorna lo `store` UserStore condiviso, registrato da app.py."""
    return current_app.config["STORE"]


def get_system_metrics() -> dict[str, Any]:
    """Utilizzo risorse macchina (CPU/RAM) + dimensione DB.

    La dimensione DB è calcolata correttamente sia per SQLite (dimensione file)
    sia per PostgreSQL (`pg_database_size`), evitando il bug precedente che
    restituiva 0 in produzione perché assumeva sempre SQLite.
    """
    vmem = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=None)

    db_size_mb = 0.0
    db_url = Config.DATABASE_URL
    if db_url.startswith("sqlite"):
        db_path = db_url.replace("sqlite:///", "")
        if db_path and os.path.exists(db_path):
            db_size_mb = os.path.getsize(db_path) / (1024 * 1024)
    else:
        try:
            with _store().Session() as s:
                size_bytes = s.execute(
                    text("SELECT pg_database_size(current_database())")
                ).scalar() or 0
            db_size_mb = size_bytes / (1024 * 1024)
        except Exception:  # noqa: BLE001 — metrica best-effort, non deve rompere la dashboard
            db_size_mb = 0.0

    return {
        "cpu_percent": cpu,
        "ram_percent": vmem.percent,
        "ram_used_gb": round(vmem.used / (1024 ** 3), 2),
        "db_size_mb": round(db_size_mb, 2),
    }


# ---------------------------------------------------------------------------
# Overview (KPI + token analytics)
# ---------------------------------------------------------------------------
@admin_bp.route("/admin", strict_slashes=False)
@_admin_required
def index():
    """Pagina overview: KPI di sistema, token ledger e analytics 90gg."""
    with _store().Session() as s:
        kpis = admin_metrics.get_overview_kpis(s)
        analytics_data = admin_metrics.get_token_analytics_90d(s)
        source_breakdown = admin_metrics.get_source_breakdown_90d(s)
        input_method_breakdown = admin_metrics.get_input_method_breakdown_90d(s)
        provider_cost_breakdown = admin_metrics.get_provider_cost_breakdown_90d(s)
    return render_template(
        "index.html",
        sys=get_system_metrics(),
        analytics_data=analytics_data,
        source_breakdown=source_breakdown,
        input_method_breakdown=input_method_breakdown,
        provider_cost_breakdown=provider_cost_breakdown,
        **kpis,
    )


@admin_bp.route("/admin/api/users/token-usage")
@_admin_required
def users_token_usage():
    """Consumo token per ogni utente (JSON, popolato via fetch nella overview)."""
    with _store().Session() as s:
        return jsonify(admin_metrics.get_token_usage_per_user(s))


@admin_bp.route("/admin/api/overview")
@_admin_required
def overview_refresh():
    """KPI + token ledger + analytics 90gg in JSON, per l'auto-refresh lato client
    della pagina overview (stesse funzioni usate dal render iniziale di index()).

    Il parametro opzionale `?days=N` sovrascrive il periodo del grafico "Consumo
    Token LLM" (default 10, selettore 10gg/1mese/2mesi/N a scelta in dashboard);
    tutto il resto del payload (KPI, analytics 90gg) resta sui periodi standard.
    """
    try:
        chart_days = int(request.args.get("days", 10))
    except (TypeError, ValueError):
        chart_days = 10

    with _store().Session() as s:
        kpis = admin_metrics.get_overview_kpis(s)
        if chart_days != 10:
            kpis.update(admin_metrics.get_usage_chart(s, days=chart_days))
        analytics_data = admin_metrics.get_token_analytics_90d(s)
        source_breakdown = admin_metrics.get_source_breakdown_90d(s)
        input_method_breakdown = admin_metrics.get_input_method_breakdown_90d(s)
        provider_cost_breakdown = admin_metrics.get_provider_cost_breakdown_90d(s)
    return jsonify({
        "sys": get_system_metrics(),
        "kpis": kpis,
        "analytics_data": analytics_data,
        "source_breakdown": source_breakdown,
        "input_method_breakdown": input_method_breakdown,
        "provider_cost_breakdown": provider_cost_breakdown,
    })


# ---------------------------------------------------------------------------
# Prodotto: retention, timing spese, onboarding, engagement
# ---------------------------------------------------------------------------
@admin_bp.route("/admin/product", strict_slashes=False)
@_admin_required
def product_metrics():
    """Metriche di prodotto: retention, timing spese, funnel onboarding, engagement."""
    with _store().Session() as s:
        retention = admin_metrics.get_retention(s)
        timing = admin_metrics.get_expense_timing(s)
        onboarding = admin_metrics.get_onboarding_funnel(s)
        engagement = admin_metrics.get_engagement_acquisition(s)
        tx_success = admin_metrics.get_tx_success_by_type_method(s)
        tour = admin_metrics.get_tour_funnel(s)
        subscription_funnel = admin_metrics.get_subscription_candidate_funnel(s)
        expense_label_clusters = admin_metrics.get_expense_label_cluster_stats(s)
    return render_template(
        "product.html",
        retention=retention,
        timing=timing,
        onboarding=onboarding,
        engagement=engagement,
        tx_success=tx_success,
        tour=tour,
        subscription_funnel=subscription_funnel,
        expense_label_clusters=expense_label_clusters,
    )


# ---------------------------------------------------------------------------
# Business: funnel & revenue + consumo token mensile per utente (tuning quote)
# ---------------------------------------------------------------------------
@admin_bp.route("/admin/business", strict_slashes=False)
@_admin_required
def business_metrics():
    """Metriche di business: piani, MRR, churn, unit economics, quote token."""
    with _store().Session() as s:
        revenue = admin_metrics.get_funnel_revenue(s)
        monthly = admin_metrics.get_monthly_token_usage(s)
    return render_template(
        "business.html",
        revenue=revenue,
        monthly=monthly,
    )


# ---------------------------------------------------------------------------
# Referral: leaderboard, reward, sblocco Lifetime Founder
# ---------------------------------------------------------------------------
@admin_bp.route("/admin/referrals", strict_slashes=False)
@_admin_required
def referrals():
    """Stato del sistema referral: KPI, classifica referrer, invii recenti."""
    with _store().Session() as s:
        referral_data = admin_metrics.get_referral_metrics(s)
    return render_template("referrals.html", referral=referral_data)


# ---------------------------------------------------------------------------
# Utenti + drill-down per utente
# ---------------------------------------------------------------------------
@admin_bp.route("/admin/users", strict_slashes=False)
@_admin_required
def users_list():
    """Lista utenti con stato attivo/sospeso."""
    with _store().Session() as s:
        users = s.query(User).order_by(User.created_at.desc()).all()
    return render_template("users.html", users=users)


@admin_bp.route("/admin/user/<chat_id>", strict_slashes=False)
@_admin_required
def user_detail(chat_id: str):
    """Timeline completa del singolo utente (supporto/analisi)."""
    with _store().Session() as s:
        detail = admin_metrics.get_user_detail(s, chat_id)
    if detail is None:
        return render_template("user_detail.html", detail=None, chat_id=chat_id), 404
    return render_template("user_detail.html", detail=detail, chat_id=chat_id)


@admin_bp.route("/admin/api/toggle-user/<chat_id>", methods=["POST"])
@_admin_required
def toggle_user(chat_id: str):
    """Sospende/riattiva un utente."""
    with _store().Session() as s:
        user = s.query(User).filter(User.chat_id == chat_id).first()
        if user:
            user.is_active = not user.is_active
            s.commit()
            return jsonify({"status": "ok", "new_state": user.is_active})
    return jsonify({"error": "User not found"}), 404


@admin_bp.route("/admin/api/notify-user/<chat_id>", methods=["POST"])
@_admin_required
def notify_user(chat_id: str):
    """Invia una notifica in-app a un singolo utente (messaggio manuale admin)."""
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    body = (data.get("body") or "").strip()
    if not title or not body:
        return jsonify({"error": "title e body sono obbligatori"}), 400

    with _store().Session() as s:
        user = s.query(User).filter(User.chat_id == chat_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404
        if not user.notifications_enabled:
            return jsonify({"error": "Utente in opt-out dalle notifiche (Art. 21 GDPR)"}), 409
        create_notification(s, chat_id, "admin_message", title, body, priority="info")
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------
@admin_bp.route("/admin/feedbacks", strict_slashes=False)
@_admin_required
def feedbacks_list():
    """Lista feedback utenti."""
    with _store().Session() as s:
        fbs = s.query(Feedback).order_by(Feedback.created_at.desc()).all()
    return render_template("feedbacks.html", feedbacks=fbs)


@admin_bp.route("/admin/api/resolve-feedback/<int:fb_id>", methods=["POST"])
@_admin_required
def resolve_feedback(fb_id: int):
    """Toggle stato feedback unread/resolved."""
    with _store().Session() as s:
        fb = s.query(Feedback).filter(Feedback.id == fb_id).first()
        if fb:
            fb.status = "resolved" if fb.status == "unread" else "unread"
            s.commit()
            return jsonify({"status": "ok", "new_state": fb.status})
    return jsonify({"error": "Feedback not found"}), 404


# ---------------------------------------------------------------------------
# Scheduled job: esiti + no-show
# ---------------------------------------------------------------------------
@admin_bp.route("/admin/jobs", strict_slashes=False)
@_admin_required
def jobs_status():
    """Stato degli scheduled job di oggi (esiti, return code, no-show)."""
    with _store().Session() as s:
        jobs = admin_metrics.get_jobs_status(s)
    return render_template("jobs.html", jobs=jobs)


# ---------------------------------------------------------------------------
# Log viewer (architettura JSONL per-dominio)
# ---------------------------------------------------------------------------
# File JSONL prodotti da config.setup_logging(). `agent.log` resta come fallback
# legacy finché non sparisce dai server.
LOG_FILES = ["app.jsonl", "error.jsonl", "security.jsonl", "usage.jsonl"]
_MAX_SCAN_LINES = 4000  # tetto di righe lette per file (bound di memoria)


def _parse_log_line(line: str) -> dict[str, Any] | None:
    """Parsa una riga JSON Lines nel formato di config.JsonFormatter.

    Mirror di log analysis tooling::_parse_jsonl_line (schema ts/level/domain/
    event/meta), tenuto locale per non dipendere da un import del package scripts/.
    """
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    ts = record.get("ts", "")
    timestamp = ts.replace("T", " ").split(".")[0] if ts else ""
    return {
        "timestamp": timestamp,
        "level": str(record.get("level", "INFO")).upper(),
        "domain": record.get("domain", "app"),
        "event": record.get("event", ""),
        "meta": record.get("meta", {}),
        "chat_id": record.get("chat_id"),
        "logger": record.get("logger", ""),
        "exc_info": record.get("exc_info"),
    }


def _read_log_entries(filename: str, level: str | None, limit: int) -> list[dict[str, Any]]:
    """Ultime `limit` righe di un file JSONL, con filtro opzionale per livello."""
    path = Config.LOG_DIR / filename
    if not path.exists():
        return []
    tail = deque(maxlen=_MAX_SCAN_LINES)
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            raw = raw.strip()
            if raw:
                tail.append(raw)
    entries: list[dict[str, Any]] = []
    wanted = (level or "").upper()
    for raw in tail:
        parsed = _parse_log_line(raw)
        if parsed is None:
            continue
        if wanted and parsed["level"] != wanted:
            continue
        entries.append(parsed)
    return entries[-limit:]


def _log_summary() -> dict[str, int]:
    """Conteggio errori/eventi security/usage di oggi (dai rispettivi file)."""
    today = date.today().isoformat()

    def _count_today(filename: str, levels: set[str] | None = None) -> int:
        path = Config.LOG_DIR / filename
        if not path.exists():
            return 0
        count = 0
        with open(path, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                parsed = _parse_log_line(raw.strip()) if raw.strip() else None
                if not parsed or not parsed["timestamp"].startswith(today):
                    continue
                if levels and parsed["level"] not in levels:
                    continue
                count += 1
        return count

    return {
        "errors_today": _count_today("error.jsonl"),
        "security_today": _count_today("security.jsonl"),
        # Fallimenti "attesi" (OCR/audio/parsing spesa) — WARNING/ERROR nel dominio
        # usage, distinti dagli errori di sistema in error.jsonl (vedi docs/logging.md).
        "usage_failures_today": _count_today("usage.jsonl", levels={"WARNING", "ERROR"}),
    }


@admin_bp.route("/admin/logs", strict_slashes=False)
@_admin_required
def logs_viewer():
    """Viewer log JSONL per-dominio con filtro file/livello e riepilogo odierno."""
    selected = request.args.get("file", "app.jsonl")
    if selected not in LOG_FILES:
        selected = "app.jsonl"
    level = request.args.get("level") or None
    try:
        limit = min(int(request.args.get("limit", 200)), _MAX_SCAN_LINES)
    except (TypeError, ValueError):
        limit = 200

    entries = _read_log_entries(selected, level, limit)
    return render_template(
        "logs.html",
        entries=entries,
        files=LOG_FILES,
        selected_file=selected,
        selected_level=level or "",
        limit=limit,
        summary=_log_summary(),
    )
