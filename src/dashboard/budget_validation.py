"""Parsing importi monetari e coerenza tra budget categoria e budget generale.

Modulo leaf: legge lo store condiviso via `current_app.config["STORE"]`, mai
import diretto di `app.py`/`factory.py`. Usato sia dalle preferenze utente e
dal setup/onboarding (`app.py`) sia dalle categorie di spesa
(`blueprints/space_routes.py`).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from flask import current_app, jsonify

_GENERAL_BUDGET_ERROR = (
    "La somma dei budget categoria non puo' superare il budget mensile generale."
)


def _store():
    return current_app.config["STORE"]


def _parse_money(value: object, field_name: str) -> tuple[Decimal | None, tuple[object, int] | None]:
    """Converte un input monetario opzionale in Decimal a due decimali."""
    if value in (None, ""):
        return None, None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None, (jsonify({"error": f"{field_name} deve essere un numero"}), 400)
    if not amount.is_finite():
        return None, (jsonify({"error": f"{field_name} deve essere un numero finito"}), 400)
    if amount < 0:
        return None, (jsonify({"error": f"{field_name} non puo' essere negativo"}), 400)
    return amount.quantize(Decimal("0.01")), None


def _category_budget_total_for_user(chat_id: str, override: dict[str, Decimal | None] | None = None) -> Decimal:
    """Somma i budget categoria attivi, applicando eventuali valori non ancora salvati."""
    overrides = override or {}
    seen_names: set[str] = set()
    total = Decimal("0.00")
    for category in _store().get_user_categories_with_budget(chat_id):
        name = category["name"]
        seen_names.add(name)
        raw_budget = overrides.get(name, category.get("monthly_budget"))
        budget = Decimal(str(raw_budget or "0"))
        if budget > 0:
            total += budget
    for name, raw_budget in overrides.items():
        if name in seen_names:
            continue
        budget = Decimal(str(raw_budget or "0"))
        if budget > 0:
            total += budget
    return total.quantize(Decimal("0.01"))


def _validate_category_budgets_with_general_budget(
    chat_id: str,
    category_name: str,
    category_budget: Decimal | None,
) -> tuple[object, int] | None:
    """Blocca budget categoria che renderebbero incoerente il budget generale."""
    preferences = _store().get_user_preferences(chat_id)
    general_budget = preferences.get("monthly_budget")
    if general_budget in (None, ""):
        return None
    general = Decimal(str(general_budget)).quantize(Decimal("0.01"))
    category_total = _category_budget_total_for_user(
        chat_id,
        {category_name: category_budget},
    )
    if category_total > general:
        return jsonify({
            "error": _GENERAL_BUDGET_ERROR,
            "maximum_total": float(general),
            "category_budget_total": float(category_total),
        }), 400
    return None
