"""CRUD categorie di entrata, multi-backend (Postgres/Notion).

Blueprint leaf: legge lo store condiviso via `current_app.config["STORE"]`, mai
import diretto di `app.py`/`factory.py` (nessun ciclo).
"""
from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request

from src.dashboard.auth import _get_user_by_chat_id, _tg_webapp_auth
from src.dashboard.category_descriptions import _synthesize_category_description
from src.dashboard.storage import _build_financial_storage, _pg_or_401

income_categories_bp = Blueprint("income_categories", __name__)


def _store():
    return current_app.config["STORE"]


@income_categories_bp.route("/api/income-categories", methods=["GET"])
@_tg_webapp_auth
def income_categories_list():
    """List active user-owned income categories for selectors and management UI."""
    include_archived = request.args.get("include_archived") == "true"
    user = _get_user_by_chat_id(g.chat_id)
    if user is None:
        return jsonify({"error": "Utente non trovato"}), 404
    if user.storage_backend == "postgres":
        with _store().Session() as s:
            pg, err = _pg_or_401(s, g.chat_id)
            if err:
                return err
            rows = pg.get_income_categories(include_archived)
    else:
        rows = _build_financial_storage(user).get_income_categories(include_archived)
    return jsonify({"income_categories": rows})


@income_categories_bp.route("/api/income-categories", methods=["POST"])
@_tg_webapp_auth
def income_categories_create():
    """Create a tenant-owned income category."""
    data = request.json or {}
    from src.input_sanitizer import InjectionDetectedError, sanitize_category_metadata

    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Il nome categoria è obbligatorio"}), 400
    user = _get_user_by_chat_id(g.chat_id)
    if user is None:
        return jsonify({"error": "Utente non trovato"}), 404
    description = (data.get("description") or "").strip() or None
    try:
        name = sanitize_category_metadata(name, g.chat_id, field="name")
        if description:
            description = sanitize_category_metadata(description, g.chat_id, field="description")
    except InjectionDetectedError:
        return jsonify({"error": "Testo categoria non valido"}), 400
    description_summary = _synthesize_category_description(description) if description else None
    try:
        if user.storage_backend == "postgres":
            with _store().Session() as s:
                pg, err = _pg_or_401(s, g.chat_id)
                if err:
                    return err
                result = pg.create_income_category(name, description=description,
                    description_summary=description_summary)
        else:
            result = _build_financial_storage(user).create_income_category(
                name, description=description, description_summary=description_summary)
    except ValueError:
        return jsonify({"error": "Categoria entrata già esistente"}), 409
    return jsonify(result), 201


@income_categories_bp.route("/api/income-categories/<int:category_id>", methods=["PUT"])
@_tg_webapp_auth
def income_categories_update(category_id: int):
    """Update one income category after tenant ownership enforcement in storage."""
    user = _get_user_by_chat_id(g.chat_id)
    if user is None:
        return jsonify({"error": "Utente non trovato"}), 404
    from src.input_sanitizer import InjectionDetectedError, sanitize_category_metadata

    data = request.json or {}
    name = data.get("name") or None
    description = data.get("description")
    try:
        if name is not None:
            name = sanitize_category_metadata(name.strip(), g.chat_id, field="name")
        if description is not None:
            description = description.strip() or None
            if description:
                description = sanitize_category_metadata(
                    description, g.chat_id, field="description",
                )
    except InjectionDetectedError:
        return jsonify({"error": "Testo categoria non valido"}), 400
    description_summary = _synthesize_category_description(description) if description else None
    fields = {"name": name}
    if description is not None:
        fields.update({"description": description, "description_summary": description_summary})
    try:
        if user.storage_backend == "postgres":
            with _store().Session() as s:
                pg, err = _pg_or_401(s, g.chat_id)
                if err:
                    return err
                result = pg.update_income_category(category_id, **fields)
        else:
            result = _build_financial_storage(user).update_income_category(
                category_id, **fields
            )
    except ValueError:
        return jsonify({"error": "Categoria entrata già esistente"}), 409
    if result is None:
        return jsonify({"error": "Categoria entrata non trovata"}), 404
    return jsonify(result)


@income_categories_bp.route("/api/income-categories/<int:category_id>", methods=["DELETE"])
@_tg_webapp_auth
def income_categories_delete(category_id: int):
    """Delete an income category after reassigning linked rows to ``Altra entrata``."""
    user = _get_user_by_chat_id(g.chat_id)
    if user is None:
        return jsonify({"error": "Utente non trovato"}), 404
    try:
        if user.storage_backend == "postgres":
            with _store().Session() as s:
                pg, err = _pg_or_401(s, g.chat_id)
                if err:
                    return err
                result = pg.delete_income_category(category_id)
        else:
            result = _build_financial_storage(user).delete_income_category(category_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if result is None:
        return jsonify({"error": "Categoria entrata non trovata"}), 404
    return jsonify(result)
