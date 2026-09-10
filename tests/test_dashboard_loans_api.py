"""
tests/test_dashboard_loans_api.py — Endpoint /api/loans*.

Flask test client -> import pesante dell'app -> marcato e2e (non gira di default,
vedi pytest.ini). Stesso pattern di tests/test_dashboard_savings_goals_api.py.
"""
from datetime import date

import pytest

pytestmark = pytest.mark.e2e


def _csrf_token(client):
    return client.get("/api/csrf-token").json["csrf_token"]


def _login(client, store, chat_id: str):
    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = chat_id
        sess["token_version"] = store.get_token_version(chat_id)


def _make_pro_postgres_user(store, chat_id: str) -> str:
    store.add_user(chat_id=chat_id, username="pro-user", storage_backend="postgres")
    store.set_user_plan(chat_id, "pro")
    return chat_id


_FIXED_LOAN_PAYLOAD = {
    "name": "Mutuo casa",
    "loan_type": "mutuo_casa",
    "principal_amount": 200000,
    "disbursement_date": "2026-01-01",
    "duration_months": 300,
    "rate_type": "fisso",
    "tan": 3.0,
}

_VARIABLE_LOAN_PAYLOAD = {
    "name": "Prestito auto",
    "loan_type": "prestito_auto",
    "principal_amount": 20000,
    "disbursement_date": "2026-01-01",
    "duration_months": 60,
    "rate_type": "variabile",
    "tan": 4.0,
    "review_frequency": "trimestrale",
}


class TestGating:
    def test_free_user_gets_403(self, client):
        from src.dashboard.app import store

        chat_id = "loans_free_user"
        store.add_user(chat_id=chat_id, username="free-user", storage_backend="postgres")
        _login(client, store, chat_id)

        resp = client.get("/api/loans")
        assert resp.status_code == 403
        assert resp.json["plan_type"] == "free"

    def test_unauthenticated_gets_401(self, client):
        resp = client.get("/api/loans")
        assert resp.status_code == 401


class TestCrud:
    def test_create_list_update_delete_loan(self, client):
        from src.dashboard.app import store

        chat_id = "loans_pro_user"
        _make_pro_postgres_user(store, chat_id)
        _login(client, store, chat_id)
        csrf = _csrf_token(client)

        create_resp = client.post("/api/loans", json=_FIXED_LOAN_PAYLOAD, headers={"X-CSRFToken": csrf})
        assert create_resp.status_code == 201
        loan_id = create_resp.json["id"]
        assert create_resp.json["name"] == "Mutuo casa"
        assert create_resp.json["current_installment"] == pytest.approx(948.42, abs=0.5)
        assert create_resp.json["pct_paid_off"] == 0.0

        list_resp = client.get("/api/loans")
        assert list_resp.status_code == 200
        assert len(list_resp.json["loans"]) == 1

        update_resp = client.put(
            f"/api/loans/{loan_id}", json={"name": "Mutuo ristrutturato"}, headers={"X-CSRFToken": csrf},
        )
        assert update_resp.status_code == 200
        assert update_resp.json["name"] == "Mutuo ristrutturato"

        delete_resp = client.delete(f"/api/loans/{loan_id}", headers={"X-CSRFToken": csrf})
        assert delete_resp.status_code == 200

        list_after = client.get("/api/loans")
        assert list_after.json["loans"] == []

    def test_create_rejects_invalid_loan_type(self, client):
        from src.dashboard.app import store

        chat_id = "loans_pro_invalid_type"
        _make_pro_postgres_user(store, chat_id)
        _login(client, store, chat_id)
        csrf = _csrf_token(client)

        payload = dict(_FIXED_LOAN_PAYLOAD, loan_type="not_a_real_type")
        resp = client.post("/api/loans", json=payload, headers={"X-CSRFToken": csrf})
        assert resp.status_code == 400

    def test_variable_loan_requires_review_frequency(self, client):
        from src.dashboard.app import store

        chat_id = "loans_pro_variable_no_freq"
        _make_pro_postgres_user(store, chat_id)
        _login(client, store, chat_id)
        csrf = _csrf_token(client)

        payload = dict(_VARIABLE_LOAN_PAYLOAD)
        payload.pop("review_frequency")
        resp = client.post("/api/loans", json=payload, headers={"X-CSRFToken": csrf})
        assert resp.status_code == 400

    def test_create_rejects_invalid_account_id(self, client):
        from src.dashboard.app import store

        chat_id = "loans_pro_bad_account"
        _make_pro_postgres_user(store, chat_id)
        _login(client, store, chat_id)
        csrf = _csrf_token(client)

        payload = dict(_FIXED_LOAN_PAYLOAD, account_id=9999)
        resp = client.post("/api/loans", json=payload, headers={"X-CSRFToken": csrf})
        assert resp.status_code == 400

    def test_update_returns_404_for_unknown_loan(self, client):
        from src.dashboard.app import store

        chat_id = "loans_pro_404"
        _make_pro_postgres_user(store, chat_id)
        _login(client, store, chat_id)
        csrf = _csrf_token(client)

        resp = client.put("/api/loans/999999", json={"name": "x"}, headers={"X-CSRFToken": csrf})
        assert resp.status_code == 404

    def test_delete_returns_404_for_unknown_loan(self, client):
        from src.dashboard.app import store

        chat_id = "loans_pro_404_delete"
        _make_pro_postgres_user(store, chat_id)
        _login(client, store, chat_id)
        csrf = _csrf_token(client)

        resp = client.delete("/api/loans/999999", headers={"X-CSRFToken": csrf})
        assert resp.status_code == 404


class TestScheduleAndSimulate:
    def test_schedule_returns_full_plan_for_new_loan(self, client):
        from src.dashboard.app import store

        chat_id = "loans_pro_schedule"
        _make_pro_postgres_user(store, chat_id)
        _login(client, store, chat_id)
        csrf = _csrf_token(client)

        create_resp = client.post("/api/loans", json=_FIXED_LOAN_PAYLOAD, headers={"X-CSRFToken": csrf})
        loan_id = create_resp.json["id"]

        resp = client.get(f"/api/loans/{loan_id}/schedule")
        assert resp.status_code == 200
        assert len(resp.json["schedule"]) == 300

    def test_simulate_does_not_persist(self, client):
        from src.dashboard.app import store

        chat_id = "loans_pro_simulate"
        _make_pro_postgres_user(store, chat_id)
        _login(client, store, chat_id)
        csrf = _csrf_token(client)

        resp = client.post("/api/loans/simulate", json=_FIXED_LOAN_PAYLOAD, headers={"X-CSRFToken": csrf})
        assert resp.status_code == 200
        assert resp.json["installment"] == pytest.approx(948.42, abs=0.5)

        list_resp = client.get("/api/loans")
        assert list_resp.json["loans"] == []


class TestMortgageSustainabilityApi:
    def test_evaluation_includes_storage_derived_prefill(self, client, monkeypatch):
        from src.dashboard.app import store
        from src.storage.postgres_storage import PostgresStorage

        chat_id = "mortgage_sustainability_prefill_user"
        _make_pro_postgres_user(store, chat_id)
        _login(client, store, chat_id)
        csrf = _csrf_token(client)

        # Mesi chiusi relativi a oggi: con date fisse il test scade da solo appena
        # il calendario supera la finestra osservata dal servizio.
        def closed_month(months_ago: int, day: int) -> date:
            today = date.today()
            absolute = today.year * 12 + today.month - 1 - months_ago
            return date(absolute // 12, absolute % 12 + 1, day)

        monkeypatch.setattr(
            PostgresStorage,
            "fetch_all_transactions",
            lambda self, start, end: [
                {"date": closed_month(2, 10), "amount": 200, "category": "Casa"},
                {"date": closed_month(1, 10), "amount": 300, "category": "Casa"},
            ],
        )
        monkeypatch.setattr(
            PostgresStorage,
            "fetch_income",
            # Solo le entrate da stipendio contano come reddito sostenibile.
            lambda self, start, end: [
                {"date": closed_month(2, 1), "amount": 2500, "income_type": "Stipendio"},
                {"date": closed_month(1, 1), "amount": 2500, "income_type": "Stipendio"},
            ],
        )

        evaluated = client.post(
            "/api/mortgage-simulations/evaluate",
            json={"principal": 200000, "tan_annual": 3, "duration_months": 300},
            headers={"X-CSRFToken": csrf},
        )

        assert evaluated.status_code == 200
        assert evaluated.json["prefill"] == {
            "monthly_income": 2500.0,
            "essential_monthly_expenses": 250.0,
            "monthly_savings_target": 2250.0,
            "history_months": 2,
            "source": "ultimi mesi chiusi",
            "active_goals": [],
            "goal_strategy": "maintain",
        }

    def test_evaluation_can_be_saved_as_a_draft_without_creating_a_loan(self, client):
        from src.dashboard.app import store

        chat_id = "mortgage_sustainability_user"
        _make_pro_postgres_user(store, chat_id)
        _login(client, store, chat_id)
        csrf = _csrf_token(client)
        payload = {
            "name": "Prima casa", "principal": 200000, "tan_annual": 3,
            "duration_months": 300, "rate_type": "fisso", "monthly_income": 4000,
            "essential_monthly_expenses": 1700, "monthly_savings_target": 500,
        }

        evaluated = client.post(
            "/api/mortgage-simulations/evaluate", json=payload, headers={"X-CSRFToken": csrf},
        )
        assert evaluated.status_code == 200
        assert evaluated.json["result"]["status"] in {"sostenibile", "da_valutare", "a_rischio"}

        saved = client.post(
            "/api/mortgage-simulations", json={**payload, "result": evaluated.json["result"]},
            headers={"X-CSRFToken": csrf},
        )
        assert saved.status_code == 201
        assert client.get("/api/loans").json["loans"] == []
        assert len(client.get("/api/mortgage-simulations").json["simulations"]) == 1

    def test_draft_can_be_read_updated_and_duplicated(self, client):
        from src.dashboard.app import store

        chat_id = "mortgage_draft_lifecycle_user"
        _make_pro_postgres_user(store, chat_id)
        _login(client, store, chat_id)
        csrf = _csrf_token(client)
        payload = {"name": "Prima casa", "principal": 200000, "tan_annual": 3,
                   "duration_months": 300, "rate_type": "fisso"}
        saved = client.post("/api/mortgage-simulations", json=payload, headers={"X-CSRFToken": csrf})
        draft_id = saved.json["id"]

        assert client.get(f"/api/mortgage-simulations/{draft_id}").status_code == 200
        changed = client.put(f"/api/mortgage-simulations/{draft_id}", json={**payload, "name": "Casa aggiornata"}, headers={"X-CSRFToken": csrf})
        assert changed.status_code == 200
        assert changed.json["name"] == "Casa aggiornata"
        copied = client.post(f"/api/mortgage-simulations/{draft_id}/duplicate", headers={"X-CSRFToken": csrf})
        assert copied.status_code == 201
        assert copied.json["id"] != draft_id

    def test_active_draft_converts_once_without_historical_charges(self, client):
        """La conversione crea il contratto, non le rate passate, ed è idempotente."""
        from src.dashboard.app import store

        chat_id = "mortgage_draft_conversion_user"
        _make_pro_postgres_user(store, chat_id)
        _login(client, store, chat_id)
        csrf = _csrf_token(client)
        simulation = {
            "name": "Prima casa", "principal": 200000, "tan_annual": 3,
            "duration_months": 300, "rate_type": "fisso",
        }
        saved = client.post("/api/mortgage-simulations", json=simulation, headers={"X-CSRFToken": csrf})
        draft_id = saved.json["id"]

        converted = client.post(
            f"/api/mortgage-simulations/{draft_id}/convert",
            json={**_FIXED_LOAN_PAYLOAD, "name": "Prima casa"},
            headers={"X-CSRFToken": csrf},
        )
        assert converted.status_code == 201
        assert client.get(f"/api/loans/{converted.json['id']}/schedule").json["schedule"]
        detail = client.get(f"/api/mortgage-simulations/{draft_id}")
        assert detail.json["status"] == "archived"
        assert detail.json["converted_loan_id"] == converted.json["id"]
        repeated = client.post(
            f"/api/mortgage-simulations/{draft_id}/convert",
            json={**_FIXED_LOAN_PAYLOAD, "name": "Prima casa"},
            headers={"X-CSRFToken": csrf},
        )
        assert repeated.status_code == 409

    def test_conversion_rejects_an_account_not_owned_by_the_user(self, client):
        from src.dashboard.app import store

        chat_id = "mortgage_draft_conversion_account_user"
        _make_pro_postgres_user(store, chat_id)
        _login(client, store, chat_id)
        csrf = _csrf_token(client)
        saved = client.post(
            "/api/mortgage-simulations",
            json={"name": "Prima casa", "principal": 200000, "tan_annual": 3,
                  "duration_months": 300, "rate_type": "fisso"},
            headers={"X-CSRFToken": csrf},
        )

        response = client.post(
            f"/api/mortgage-simulations/{saved.json['id']}/convert",
            json={**_FIXED_LOAN_PAYLOAD, "account_id": 999999},
            headers={"X-CSRFToken": csrf},
        )
        assert response.status_code == 400
