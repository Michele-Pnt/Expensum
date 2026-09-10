"""Obiettivi di risparmio, mutui/finanziamenti, simulazioni mutuo e gamification.

Feature Pro, solo backend PostgreSQL (tranne la gamification, che non ha gating
Pro). Blueprint leaf: legge lo store condiviso via `current_app.config["STORE"]`,
mai import diretto di `app.py`/`factory.py` (nessun ciclo).
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from flask import Blueprint, current_app, g, jsonify, request

from src.dashboard.auth import _tg_webapp_auth
from src.dashboard.storage import _get_user_plan_type, _pg_or_401, _pg_pro_or_error

logger = logging.getLogger(__name__)

goals_bp = Blueprint("goals", __name__)


def _store():
    return current_app.config["STORE"]


# ── Savings goals ────────────────────────────────────────────────────────────

def _goal_view(storage, goal: dict) -> dict:
    """Arricchisce il dict del goal con progresso/ETA/voto calcolati on-read."""
    from src.savings_goals_service import (
        _category_name_for, compute_goal_progress, compute_monthly_score, explain_score,
    )

    progress = compute_goal_progress(storage, goal)
    score = compute_monthly_score(storage, goal, progress)
    view = dict(goal)
    view["progress"] = progress["progress_pct"]
    view["current_value"] = progress["current"]
    # Per la maggior parte dei tipi e' un no-op (stesso valore gia' su DB); per
    # emergency_fund sostituisce lo stub salvato con la mediana ricalcolata adesso.
    view["target_amount"] = progress["target_amount"]
    view["eta_date"] = progress["eta_date"].isoformat() if progress["eta_date"] else None
    view["score_label"] = score["score_label"]
    category_name = (
        _category_name_for(storage, goal.get("category_id"))
        if goal["goal_type"] == "category_spending_reduction" else None
    )
    view["explanation"] = explain_score(goal, score, markdown=False, category_name=category_name)
    return view


@goals_bp.route("/api/savings-goals", methods=["GET"])
@_tg_webapp_auth
def savings_goals_list():
    with _store().Session() as s:
        pg, err = _pg_pro_or_error(s, g.chat_id)
        if err:
            return err
        goals = pg.fetch_savings_goals(status="active")
        result = [_goal_view(pg, goal) for goal in goals]
        return jsonify({"goals": result, "plan_type": "pro"})


@goals_bp.route("/api/savings-goals", methods=["POST"])
@_tg_webapp_auth
def savings_goals_create():
    from src.savings_goals_service import GOAL_TYPES

    data = request.json or {}
    goal_type = data.get("goal_type")
    name = (data.get("name") or "").strip()
    target_amount = data.get("target_amount")

    if goal_type not in GOAL_TYPES:
        return jsonify({"error": f"goal_type deve essere uno tra {sorted(GOAL_TYPES)}"}), 400
    if not name:
        return jsonify({"error": "Il campo 'name' è obbligatorio"}), 400

    emergency_fund_months = None
    if goal_type == "emergency_fund":
        # Il target non arriva dal client: si calcola server-side dalla mediana
        # di spesa (vedi sotto), quindi qui si valida solo la scelta dei mesi.
        try:
            emergency_fund_months = int(data.get("emergency_fund_months"))
        except (TypeError, ValueError):
            emergency_fund_months = None
        if emergency_fund_months not in (3, 6, 12):
            return jsonify({"error": "emergency_fund_months deve essere 3, 6 o 12"}), 400
    else:
        try:
            target_amount = float(target_amount)
            if target_amount <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "target_amount deve essere un numero positivo"}), 400

    account_id = data.get("account_id")
    category_id = data.get("category_id")
    target_date_str = data.get("target_date")
    target_date = None
    if target_date_str:
        try:
            target_date = date.fromisoformat(target_date_str)
        except ValueError:
            return jsonify({"error": "target_date deve essere in formato YYYY-MM-DD"}), 400

    with _store().Session() as s:
        pg, err = _pg_pro_or_error(s, g.chat_id)
        if err:
            return err

        if goal_type == "account_balance":
            if account_id is None or not any(a["id"] == int(account_id) for a in pg.fetch_accounts()):
                return jsonify({"error": "account_id non valido o non di tua proprietà"}), 400
        if goal_type == "category_spending_reduction":
            if category_id is None or not any(c["id"] == int(category_id) for c in pg.get_categories()):
                return jsonify({"error": "category_id non valido o non di tua proprietà"}), 400
        # emergency_fund: account_id opzionale, ma se presente deve appartenere all'utente.
        if goal_type == "emergency_fund" and account_id is not None:
            if not any(a["id"] == int(account_id) for a in pg.fetch_accounts()):
                return jsonify({"error": "account_id non valido o non di tua proprietà"}), 400

        if goal_type == "emergency_fund":
            from src.savings_goals_service import compute_goal_progress
            probe = {
                "goal_type": "emergency_fund",
                "emergency_fund_months": emergency_fund_months,
                "account_id": int(account_id) if account_id is not None else None,
            }
            target_amount = compute_goal_progress(pg, probe)["target_amount"]
            if target_amount <= 0:
                return jsonify({"error": "Servono più spese registrate per calcolare il fondo emergenza"}), 400

        result = pg.create_savings_goal(
            goal_type=goal_type,
            name=name,
            target_amount=target_amount,
            account_id=int(account_id) if account_id is not None else None,
            category_id=int(category_id) if category_id is not None else None,
            target_date=target_date,
            emergency_fund_months=emergency_fund_months,
        )
        return jsonify(_goal_view(pg, result)), 201


@goals_bp.route("/api/savings-goals/<int:goal_id>", methods=["PUT"])
@_tg_webapp_auth
def savings_goals_update(goal_id: int):
    data = request.json or {}

    target_date = None
    if "target_date" in data and data["target_date"]:
        try:
            target_date = date.fromisoformat(data["target_date"])
        except ValueError:
            return jsonify({"error": "target_date deve essere in formato YYYY-MM-DD"}), 400

    with _store().Session() as s:
        pg, err = _pg_pro_or_error(s, g.chat_id)
        if err:
            return err

        update_fields: dict = {
            "name": data.get("name") or None,
            "target_amount": float(data["target_amount"]) if data.get("target_amount") not in (None, "") else None,
            "target_date": target_date,
        }
        if "emergency_fund_months" in data:
            try:
                months = int(data["emergency_fund_months"])
            except (TypeError, ValueError):
                return jsonify({"error": "emergency_fund_months deve essere 3, 6 o 12"}), 400
            if months not in (3, 6, 12):
                return jsonify({"error": "emergency_fund_months deve essere 3, 6 o 12"}), 400
            update_fields["emergency_fund_months"] = months
        if "account_id" in data:
            account_id = data["account_id"]
            if account_id is not None and not any(a["id"] == int(account_id) for a in pg.fetch_accounts()):
                return jsonify({"error": "account_id non valido o non di tua proprietà"}), 400
            update_fields["account_id"] = int(account_id) if account_id is not None else None

        result = pg.update_savings_goal(goal_id, **update_fields)
        if result is None:
            return jsonify({"error": "Obiettivo non trovato"}), 404
        return jsonify(_goal_view(pg, result))


@goals_bp.route("/api/savings-goals/<int:goal_id>", methods=["DELETE"])
@_tg_webapp_auth
def savings_goals_delete(goal_id: int):
    with _store().Session() as s:
        pg, err = _pg_pro_or_error(s, g.chat_id)
        if err:
            return err
        ok = pg.delete_savings_goal(goal_id)
        if not ok:
            return jsonify({"error": "Obiettivo non trovato"}), 404
        return jsonify({"status": "ok"})


@goals_bp.route("/api/savings-goals/<int:goal_id>/history", methods=["GET"])
@_tg_webapp_auth
def savings_goals_history(goal_id: int):
    with _store().Session() as s:
        pg, err = _pg_pro_or_error(s, g.chat_id)
        if err:
            return err
        history = pg.fetch_savings_goal_evaluations(goal_id, limit=12)
        return jsonify({"history": history})


@goals_bp.route("/api/savings-goals/summary", methods=["GET"])
@_tg_webapp_auth
def savings_goals_summary():
    from collections import Counter

    with _store().Session() as s:
        pg, err = _pg_pro_or_error(s, g.chat_id)
        if err:
            return err
        goals = [_goal_view(pg, goal) for goal in pg.fetch_savings_goals(status="active")]

    by_label = Counter(item["score_label"] for item in goals)
    next_goal = min(
        (item for item in goals if item.get("target_date")),
        key=lambda item: item["target_date"],
        default=None,
    )
    return jsonify({
        "count": len(goals),
        "by_score_label": dict(by_label),
        "next_deadline": next_goal,
    })


# ── Mutui/finanziamenti ──────────────────────────────────────────────────────
#
# Feature Pro, solo backend PostgreSQL (stesso gating di /api/savings-goals*).
# Il calcolo (rata/piano/TAEG) è sempre demandato a src/loan_calculator.py: mai
# duplicato qui, per non rischiare che dashboard e job mensile (bot.py) divergano.

_LOAN_TYPES = {"mutuo_casa", "prestito_auto", "prestito_personale", "altro"}
_LOAN_RATE_TYPES = {"fisso", "variabile"}
_LOAN_REVIEW_FREQUENCIES = {"trimestrale", "semestrale", "anniversario"}
_LOAN_PAYMENT_CADENCES = {"monthly", "quarterly", "semiannual", "yearly"}


def _parse_loan_date(raw: str | None, field: str) -> tuple[date | None, tuple | None]:
    """Converte una stringa ISO in date. Ritorna (None, error_response) se non valida."""
    if not raw:
        return None, None
    try:
        return date.fromisoformat(raw), None
    except ValueError:
        return None, (jsonify({"error": f"{field} deve essere in formato YYYY-MM-DD"}), 400)


def _validate_loan_payload(data: dict) -> tuple[dict | None, tuple | None]:
    """Valida il payload di creazione/simulazione loan. Ritorna (fields, None) o (None, error)."""
    loan_type = data.get("loan_type")
    name = (data.get("name") or "").strip()
    rate_type = data.get("rate_type")

    if loan_type not in _LOAN_TYPES:
        return None, (jsonify({"error": f"loan_type deve essere uno tra {sorted(_LOAN_TYPES)}"}), 400)
    if not name:
        return None, (jsonify({"error": "Il campo 'name' è obbligatorio"}), 400)
    if rate_type not in _LOAN_RATE_TYPES:
        return None, (jsonify({"error": f"rate_type deve essere uno tra {sorted(_LOAN_RATE_TYPES)}"}), 400)

    try:
        principal_amount = float(data.get("principal_amount"))
        if principal_amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return None, (jsonify({"error": "principal_amount deve essere un numero positivo"}), 400)

    try:
        duration_months = int(data.get("duration_months"))
        if duration_months <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return None, (jsonify({"error": "duration_months deve essere un intero positivo"}), 400)

    try:
        tan = float(data.get("tan"))
    except (TypeError, ValueError):
        return None, (jsonify({"error": "tan è obbligatorio ed espresso in percentuale (es. 3.25)"}), 400)

    disbursement_date, err = _parse_loan_date(data.get("disbursement_date"), "disbursement_date")
    if err:
        return None, err
    if disbursement_date is None:
        return None, (jsonify({"error": "Il campo 'disbursement_date' è obbligatorio"}), 400)

    next_review_date, err = _parse_loan_date(data.get("next_review_date"), "next_review_date")
    if err:
        return None, err

    review_frequency = data.get("review_frequency")
    if rate_type == "variabile":
        if review_frequency not in _LOAN_REVIEW_FREQUENCIES:
            return None, (
                jsonify({"error": f"review_frequency deve essere uno tra {sorted(_LOAN_REVIEW_FREQUENCIES)} per un tasso variabile"}),
                400,
            )
    else:
        review_frequency = None
        next_review_date = None

    payment_cadence = data.get("payment_cadence") or "monthly"
    if payment_cadence not in _LOAN_PAYMENT_CADENCES:
        return None, (jsonify({"error": "payment_cadence non valido"}), 400)

    def _optional_float(key: str) -> float | None:
        value = data.get(key)
        return float(value) if value not in (None, "") else None

    fields = {
        "name": name,
        "loan_type": loan_type,
        "principal_amount": principal_amount,
        "disbursement_date": disbursement_date,
        "duration_months": duration_months,
        "rate_type": rate_type,
        "tan": tan,
        "taeg": _optional_float("taeg"),
        "spread": _optional_float("spread"),
        "euribor_current": _optional_float("euribor_current"),
        "euribor_tenor": data.get("euribor_tenor") or None,
        "review_frequency": review_frequency,
        "next_review_date": next_review_date,
        "account_id": int(data["account_id"]) if data.get("account_id") not in (None, "") else None,
        "origination_fee": _optional_float("origination_fee"),
        "monthly_fee": _optional_float("monthly_fee"),
        "payment_cadence": payment_cadence,
    }
    return fields, None


def _loan_view(loan: dict) -> dict:
    """Arricchisce il dict del loan con la percentuale estinta, calcolata on-read."""
    view = dict(loan)
    principal = loan["principal_amount"]
    residual = loan.get("residual_balance", principal)
    view["pct_paid_off"] = round((1 - residual / principal) * 100, 2) if principal else 0.0
    return view


@goals_bp.route("/api/loans", methods=["GET"])
@_tg_webapp_auth
def loans_list():
    with _store().Session() as s:
        pg, err = _pg_pro_or_error(s, g.chat_id)
        if err:
            return err
        loans = [_loan_view(loan) for loan in pg.fetch_loans()]
        return jsonify({"loans": loans, "plan_type": "pro"})


@goals_bp.route("/api/loans", methods=["POST"])
@_tg_webapp_auth
def loans_create():
    data = request.json or {}
    fields, err = _validate_loan_payload(data)
    if err:
        return err

    with _store().Session() as s:
        pg, err = _pg_pro_or_error(s, g.chat_id)
        if err:
            return err
        if fields["account_id"] is not None and not any(
            a["id"] == fields["account_id"] for a in pg.fetch_accounts()
        ):
            return jsonify({"error": "account_id non valido o non di tua proprietà"}), 400
        result = pg.create_loan(**fields)
        return jsonify(_loan_view(result)), 201


@goals_bp.route("/api/loans/<int:loan_id>", methods=["PUT"])
@_tg_webapp_auth
def loans_update(loan_id: int):
    data = request.json or {}

    next_review_date, err = _parse_loan_date(data.get("next_review_date"), "next_review_date")
    if err:
        return err
    disbursement_date, err = _parse_loan_date(data.get("disbursement_date"), "disbursement_date")
    if err:
        return err

    def _optional_float(key: str) -> float | None:
        value = data.get(key)
        return float(value) if value not in (None, "") else None

    update_fields = {
        "name": (data.get("name") or "").strip() or None,
        "loan_type": data.get("loan_type") if data.get("loan_type") in _LOAN_TYPES else None,
        "principal_amount": _optional_float("principal_amount"),
        "disbursement_date": disbursement_date,
        "duration_months": int(data["duration_months"]) if data.get("duration_months") not in (None, "") else None,
        "rate_type": data.get("rate_type") if data.get("rate_type") in _LOAN_RATE_TYPES else None,
        "account_id": int(data["account_id"]) if data.get("account_id") not in (None, "") else None,
        "tan": _optional_float("tan"),
        "spread": _optional_float("spread"),
        "euribor_current": _optional_float("euribor_current"),
        "euribor_tenor": data.get("euribor_tenor") or None,
        "review_frequency": data.get("review_frequency") or None,
        "next_review_date": next_review_date,
        "taeg": _optional_float("taeg"),
        "origination_fee": _optional_float("origination_fee"),
        "monthly_fee": _optional_float("monthly_fee"),
        "status": data.get("status") or None,
    }

    with _store().Session() as s:
        pg, err = _pg_pro_or_error(s, g.chat_id)
        if err:
            return err
        result = pg.update_loan(loan_id, **update_fields)
        if result is None:
            return jsonify({"error": "Mutuo/finanziamento non trovato"}), 404
        return jsonify(_loan_view(result))


@goals_bp.route("/api/loans/<int:loan_id>", methods=["DELETE"])
@_tg_webapp_auth
def loans_delete(loan_id: int):
    with _store().Session() as s:
        # La cancellazione è un'operazione sui dati già dell'utente: non deve
        # diventare improvvisamente indisponibile per un cambio di piano.
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        ok = pg.delete_loan(loan_id)
        if not ok:
            return jsonify({"error": "Mutuo/finanziamento non trovato"}), 404
        return jsonify({"status": "ok"})


@goals_bp.route("/api/loans/<int:loan_id>/close", methods=["POST"])
@_tg_webapp_auth
def loans_close(loan_id: int):
    """Registra l'estinzione anticipata e ferma gli addebiti futuri."""
    payload = request.json or {}
    closure_date, err = _parse_loan_date(payload.get("closure_date"), "closure_date")
    if err or closure_date is None:
        return err or (jsonify({"error": "closure_date è obbligatoria"}), 400)
    with _store().Session() as s:
        pg, err = _pg_pro_or_error(s, g.chat_id)
        if err:
            return err
        result = pg.close_loan(
            loan_id, closure_date,
            residual_principal=payload.get("residual_principal"),
            accrued_interest=payload.get("accrued_interest", 0),
            overdue_installments=payload.get("overdue_installments", 0),
            administrative_costs=payload.get("administrative_costs", 0),
            insurance_refund=payload.get("insurance_refund", 0),
        )
        if result is None:
            return jsonify({"error": "Mutuo/finanziamento non trovato"}), 404
        return jsonify(_loan_view(result))


@goals_bp.route("/api/loans/<int:loan_id>/partial-repayment", methods=["POST"])
@_tg_webapp_auth
def loans_partial_repayment(loan_id: int):
    """Registra un versamento straordinario sul capitale del mutuo."""
    data = request.json or {}
    repayment_date, err = _parse_loan_date(data.get("repayment_date"), "repayment_date")
    try:
        amount = float(data.get("amount"))
        mode = str(data.get("mode"))
    except (TypeError, ValueError):
        return jsonify({"error": "amount e mode sono obbligatori"}), 400
    if err or repayment_date is None:
        return err or (jsonify({"error": "repayment_date è obbligatoria"}), 400)
    with _store().Session() as s:
        pg, err = _pg_pro_or_error(s, g.chat_id)
        if err:
            return err
        try:
            result = pg.partially_repay_loan(loan_id, repayment_date, amount, mode)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if result is None:
            return jsonify({"error": "Mutuo non trovato o già estinto"}), 404
        return jsonify(result)


@goals_bp.route("/api/loans/<int:loan_id>/schedule", methods=["GET"])
@_tg_webapp_auth
def loans_schedule(loan_id: int):
    with _store().Session() as s:
        pg, err = _pg_pro_or_error(s, g.chat_id)
        if err:
            return err
        schedule = pg.fetch_loan_schedule(loan_id)
        return jsonify({"schedule": schedule})


@goals_bp.route("/api/loans/simulate", methods=["POST"])
@_tg_webapp_auth
def loans_simulate():
    """What-if stateless per il wizard di setup: nessuna persistenza, stesso motore
    di calcolo (src/loan_calculator.py) usato dal loan reale una volta creato.
    """
    from decimal import Decimal
    from src.loan_calculator import calculate_installment, calculate_taeg

    data = request.json or {}
    fields, err = _validate_loan_payload(data)
    if err:
        return err

    with _store().Session() as s:
        # Solo gating Pro/Postgres, nessuna scrittura: la simulazione non tocca il DB.
        _pg, err = _pg_pro_or_error(s, g.chat_id)
        if err:
            return err

    principal = Decimal(str(fields["principal_amount"]))
    tan = Decimal(str(fields["tan"]))
    installment = calculate_installment(principal, tan, fields["duration_months"])
    taeg = calculate_taeg(
        principal, tan, fields["duration_months"],
        upfront_fee=Decimal(str(fields["origination_fee"] or 0)),
        monthly_fee=Decimal(str(fields["monthly_fee"] or 0)),
    )
    return jsonify({
        "installment": float(installment),
        "taeg_estimate": float(taeg),
        "total_interest": float(installment * fields["duration_months"] - principal),
    })


def _evaluate_mortgage_sustainability(pg, data: dict) -> tuple[dict | None, tuple | None]:
    """Valuta il mutuo con il motore puro e restituisce snapshot JSON-safe."""
    from src.mortgage_sustainability import evaluate_mortgage_sustainability
    from src.mortgage_sustainability_service import (
        build_sustainability_input,
        build_sustainability_prefill,
    )

    normalized = dict(data)
    normalized["principal"] = data.get("principal", data.get("principal_amount"))
    normalized["tan_annual"] = data.get("tan_annual", data.get("tan"))
    required = ("principal", "tan_annual", "duration_months")
    if any(normalized.get(field) in (None, "") for field in required):
        return None, (jsonify({"error": "principal, tan_annual e duration_months sono obbligatori"}), 400)
    try:
        profile = build_sustainability_input(pg, normalized)
        result = evaluate_mortgage_sustainability(profile)
        prefill = build_sustainability_prefill(pg, normalized)
    except (TypeError, ValueError, ArithmeticError) as exc:
        return None, (jsonify({"error": f"Dati simulazione non validi: {exc}"}), 400)
    return {"input": normalized, "result": result.to_dict(), "prefill": prefill}, None


@goals_bp.route("/api/mortgage-simulations/evaluate", methods=["POST"])
@_tg_webapp_auth
def mortgage_simulations_evaluate():
    """Valutazione realtime, senza scrivere bozze, mutui o budget."""
    with _store().Session() as s:
        pg, err = _pg_pro_or_error(s, g.chat_id)
        if err:
            return err
        payload, err = _evaluate_mortgage_sustainability(pg, request.json or {})
        if err:
            return err
        return jsonify(payload)


@goals_bp.route("/api/mortgage-simulations", methods=["GET", "POST"])
@_tg_webapp_auth
def mortgage_simulations():
    """Elenca o salva bozze; il risultato viene sempre ricalcolato lato server."""
    with _store().Session() as s:
        pg, err = _pg_pro_or_error(s, g.chat_id)
        if err:
            return err
        if request.method == "GET":
            return jsonify({"simulations": pg.fetch_mortgage_simulations()})
        data = request.json or {}
        name = (data.get("name") or "Simulazione mutuo").strip()
        payload, err = _evaluate_mortgage_sustainability(pg, data)
        if err:
            return err
        simulation = pg.create_mortgage_simulation(name, payload["input"], payload["result"])
        return jsonify(simulation), 201


@goals_bp.route("/api/mortgage-simulations/<int:simulation_id>", methods=["GET", "PUT", "DELETE"])
@_tg_webapp_auth
def mortgage_simulation_detail(simulation_id: int):
    """Legge, aggiorna o elimina una bozza appartenente all'utente autenticato."""
    with _store().Session() as s:
        pg, err = _pg_pro_or_error(s, g.chat_id)
        if err:
            return err
        if request.method == "GET":
            simulation = pg.get_mortgage_simulation(simulation_id)
            return jsonify(simulation) if simulation else (jsonify({"error": "Simulazione non trovata"}), 404)
        if request.method == "PUT":
            data = request.json or {}
            payload, err = _evaluate_mortgage_sustainability(pg, data)
            if err:
                return err
            simulation = pg.update_mortgage_simulation(
                simulation_id, (data.get("name") or "Simulazione mutuo").strip(), payload["input"], payload["result"],
            )
            return jsonify(simulation) if simulation else (jsonify({"error": "Simulazione non trovata"}), 404)
        if not pg.delete_mortgage_simulation(simulation_id):
            return jsonify({"error": "Simulazione non trovata"}), 404
        return jsonify({"status": "ok"})


@goals_bp.route("/api/mortgage-simulations/<int:simulation_id>/duplicate", methods=["POST"])
@_tg_webapp_auth
def mortgage_simulation_duplicate(simulation_id: int):
    """Duplica una bozza appartenente all'utente autenticato."""
    with _store().Session() as s:
        pg, err = _pg_pro_or_error(s, g.chat_id)
        if err:
            return err
        simulation = pg.duplicate_mortgage_simulation(simulation_id)
        if simulation is None:
            return jsonify({"error": "Simulazione non trovata"}), 404
        return jsonify(simulation), 201


@goals_bp.route("/api/mortgage-simulations/<int:simulation_id>/convert", methods=["POST"])
@_tg_webapp_auth
def mortgage_simulation_convert(simulation_id: int):
    """Converte una bozza attiva nel mutuo reale dell'utente."""
    data = request.json or {}
    fields, err = _validate_loan_payload(data)
    if err:
        return err
    with _store().Session() as s:
        pg, err = _pg_pro_or_error(s, g.chat_id)
        if err:
            return err
        if fields["account_id"] is not None and not any(
            account["id"] == fields["account_id"] for account in pg.fetch_accounts()
        ):
            return jsonify({"error": "account_id non valido o non di tua proprietà"}), 400
        loan = pg.convert_mortgage_simulation(simulation_id, fields)
        if loan is None:
            return jsonify({"error": "Simulazione non disponibile per la conversione"}), 409
        return jsonify(loan), 201


@goals_bp.route("/api/mortgage-simulations/apply-budget", methods=["POST"])
@_tg_webapp_auth
def mortgage_simulations_apply_budget():
    """Ricalcola la proposta e applica solo i budget selezionati dall'utente."""
    with _store().Session() as s:
        pg, err = _pg_pro_or_error(s, g.chat_id)
        if err:
            return err
        payload, err = _evaluate_mortgage_sustainability(pg, request.json or {})
        if err:
            return err
        proposal = payload["result"]["budget_reallocation"]
        if proposal["uncovered_reduction"] > 0:
            return jsonify({"error": "Le categorie selezionate non coprono la riduzione necessaria"}), 400
        items = proposal["items"]
        updated = pg.apply_category_budgets(items)
        if updated is None:
            return jsonify({"error": "Una categoria selezionata non è valida"}), 400
        return jsonify({"categories": updated, "result": payload["result"]})


@goals_bp.route("/api/loans/<int:loan_id>/buffer-goal", methods=["POST"])
@_tg_webapp_auth
def loans_create_buffer_goal(loan_id: int):
    """Crea un obiettivo cuscinetto opzionale basato su rate complete."""
    data = request.json or {}
    try:
        months = int(data.get("months"))
        if months <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "months deve essere un intero positivo"}), 400
    target_date, err = _parse_loan_date(data.get("target_date"), "target_date")
    if err:
        return err
    with _store().Session() as s:
        pg, err = _pg_pro_or_error(s, g.chat_id)
        if err:
            return err
        loan = next((item for item in pg.fetch_loans() if item["id"] == loan_id), None)
        if loan is None:
            return jsonify({"error": "Mutuo/finanziamento non trovato"}), 404
        target = (loan["current_installment"] + (loan.get("monthly_fee") or 0)) * months
        goal = pg.create_savings_goal(
            goal_type="net_savings", name=f"Fondo Emergenza Mutuo: {loan['name']}",
            target_amount=target, target_date=target_date,
        )
        return jsonify(_goal_view(pg, goal)), 201


# ── Gamification ─────────────────────────────────────────────────────────────
#
# Nessun gating Pro: achievement e XP sono per tutti. Le famiglie non ottenibili
# con il backend/piano dell'utente non spariscono dal payload, vengono marcate
# `unavailable` — così la UI futura può usarle come teaser invece di nasconderle.

def _complete_reached_goals_safe(chat_id: str) -> list[dict]:
    """Chiude gli obiettivi raggiunti dopo una transazione dalla webapp.

    Usa `is_goal_reached`, che calcola solo il valore corrente senza ricostruire le
    serie mensili dell'ETA: il costo resta contenuto anche sul percorso di
    salvataggio. Non solleva mai — un errore qui non deve far fallire la spesa.

    Il job mensile resta la rete di sicurezza e continua a produrre voti e storico
    per il report, che non cambia.
    """
    from src.gamification import engine as gamification

    try:
        from src.savings_goals_service import detect_completed_goals

        store = _store()
        unlocks: list[dict] = []
        with store.Session() as s:
            pg, err = _pg_or_401(s, chat_id)
            if err:
                return []
            for goal in detect_completed_goals(pg):
                pg.update_savings_goal(
                    goal["id"], status="completed", completed_at=datetime.utcnow(),
                )
                unlocks += [
                    u.as_dict() for u in gamification.record_event(
                        store, chat_id, "savings_goal_completed",
                        dedup_key=f"goal:{goal['id']}",
                    )
                ]
        return unlocks
    except Exception as exc:  # noqa: BLE001 — la gamification non deve mai propagare
        logger.warning(
            "Rilevamento obiettivi fallito per %s: %s", chat_id, exc,
            extra={"domain": "gamification", "event": "goal_realtime_check_failed",
                   "meta": {"chat_id": str(chat_id)}},
        )
        return []


def _gamification_context(chat_id: str) -> tuple[str, str]:
    """Backend e piano dell'utente, che decidono quali famiglie sono ottenibili."""
    from src.user_store import User

    backend = "postgres"
    try:
        with _store().Session() as s:
            user = s.query(User).filter_by(chat_id=chat_id).first()
            backend = (user.storage_backend if user else None) or "postgres"
    except Exception:  # noqa: BLE001 — il default non impedisce di rispondere
        pass
    return backend, _get_user_plan_type(chat_id)


def _requested_locale() -> str:
    locale = (request.args.get("locale") or "it").lower()
    return locale if locale in ("it", "en") else "it"


@goals_bp.route("/api/gamification/achievements", methods=["GET"])
@_tg_webapp_auth
def gamification_achievements():
    """Catalogo completo con stato e progresso dell'utente."""
    from src.gamification import engine as gamification

    backend, plan_type = _gamification_context(g.chat_id)
    return jsonify(gamification.get_user_state(
        _store(), g.chat_id,
        locale=_requested_locale(), backend=backend, plan_type=plan_type,
    ))


@goals_bp.route("/api/gamification/summary", methods=["GET"])
@_tg_webapp_auth
def gamification_summary():
    """Versione compatta: profilo, prossimi traguardi e sblocchi non ancora visti."""
    from src.gamification import engine as gamification

    backend, plan_type = _gamification_context(g.chat_id)
    return jsonify(gamification.get_summary(
        _store(), g.chat_id,
        locale=_requested_locale(), backend=backend, plan_type=plan_type,
    ))


@goals_bp.route("/api/gamification/seen", methods=["POST"])
@_tg_webapp_auth
def gamification_mark_seen():
    """Marca come visti gli sblocchi indicati (tutti se `codes` è assente o null)."""
    from src.gamification import engine as gamification

    data = request.json or {}
    codes = data.get("codes")
    if codes is not None and not isinstance(codes, list):
        return jsonify({"error": "codes deve essere una lista di stringhe o null"}), 400
    updated = gamification.mark_seen(_store(), g.chat_id, codes)
    return jsonify({"status": "ok", "updated": updated})
