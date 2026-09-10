"""Notifiche in-app: lista, contatore non lette, segna come letta/tutte lette.

Blueprint leaf: legge lo store condiviso via `current_app.config["STORE"]`, mai
import diretto di `app.py`/`factory.py` (nessun ciclo).
"""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from src.dashboard.auth import _resolve_request_chat_id
from src.notification_service import count_unread, list_notifications, mark_all_read, mark_read

notifications_bp = Blueprint("notifications", __name__)


def _store():
    return current_app.config["STORE"]


def _serialize_notification(notification) -> dict:
    return {
        "id": notification.id,
        "type": notification.type,
        "title": notification.title,
        "body": notification.body,
        "payload": notification.payload,
        "priority": notification.priority,
        "read": notification.read_at is not None,
        "created_at": notification.created_at.isoformat() if notification.created_at else None,
    }


@notifications_bp.route("/api/notifications", methods=["GET"])
def api_notifications_list():
    """Lista paginata delle notifiche in-app dell'utente, più recenti prima."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    unread_only = request.args.get("unread_only") == "1"
    before_id = request.args.get("before_id", type=int)
    limit = min(request.args.get("limit", default=20, type=int) or 20, 50)

    with _store().Session() as session:
        notifications = list_notifications(
            session, chat_id, unread_only=unread_only, limit=limit, before_id=before_id,
        )
        return jsonify({"notifications": [_serialize_notification(n) for n in notifications]})


@notifications_bp.route("/api/notifications/unread-count", methods=["GET"])
def api_notifications_unread_count():
    """Contatore notifiche non lette, per il badge della campanella."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    with _store().Session() as session:
        return jsonify({"unread_count": count_unread(session, chat_id)})


@notifications_bp.route("/api/notifications/<int:notification_id>/read", methods=["POST"])
def api_notifications_mark_read(notification_id: int):
    """Segna una singola notifica come letta."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    with _store().Session() as session:
        found = mark_read(session, chat_id, notification_id)
        if not found:
            return jsonify({"error": "Notifica non trovata"}), 404
        return jsonify({"ok": True})


@notifications_bp.route("/api/notifications/read-all", methods=["POST"])
def api_notifications_mark_all_read():
    """Segna tutte le notifiche dell'utente come lette."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    with _store().Session() as session:
        updated = mark_all_read(session, chat_id)
        return jsonify({"ok": True, "updated": updated})
