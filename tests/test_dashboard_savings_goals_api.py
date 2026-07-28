"""
tests/test_dashboard_savings_goals_api.py — Endpoint /api/savings-goals*.

Flask test client -> import pesante dell'app -> marcato e2e (non gira di default,
vedi pytest.ini). Autenticazione via sessione browser (stesso pattern degli altri
test e2e che colpiscono endpoint autenticati con @_tg_webapp_auth).
"""
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


class TestGating:
    def test_free_user_gets_403(self, client):
        from src.dashboard.app import store

        chat_id = "goals_free_user"
        store.add_user(chat_id=chat_id, username="free-user", storage_backend="postgres")
        _login(client, store, chat_id)

        resp = client.get("/api/savings-goals")
        assert resp.status_code == 403
        assert resp.json["plan_type"] == "free"

    def test_notion_user_gets_401(self, client):
        """Gli utenti Notion non hanno affatto accesso alla webapp (vedi
        _user_has_web_access in app.py): la sessione non viene risolta a un
        chat_id valido, quindi _tg_webapp_auth blocca con 401 prima ancora di
        arrivare al gating Pro+Postgres specifico di questo endpoint."""
        from src.dashboard.app import store

        chat_id = "goals_notion_user"
        store.add_user(chat_id=chat_id, username="notion-user", storage_backend="notion")
        store.set_user_plan(chat_id, "pro")
        _login(client, store, chat_id)

        resp = client.get("/api/savings-goals")
        assert resp.status_code == 401

    def test_unauthenticated_gets_401(self, client):
        resp = client.get("/api/savings-goals")
        assert resp.status_code == 401


class TestCrud:
    def test_create_list_update_delete_goal(self, client):
        from src.dashboard.app import store

        chat_id = "goals_pro_user"
        _make_pro_postgres_user(store, chat_id)
        _login(client, store, chat_id)
        csrf = _csrf_token(client)

        create_resp = client.post(
            "/api/savings-goals",
            json={"goal_type": "net_savings", "name": "Fondo emergenza", "target_amount": 5000},
            headers={"X-CSRFToken": csrf},
        )
        assert create_resp.status_code == 201
        goal_id = create_resp.json["id"]
        assert create_resp.json["name"] == "Fondo emergenza"
        assert "progress" in create_resp.json

        list_resp = client.get("/api/savings-goals")
        assert list_resp.status_code == 200
        assert len(list_resp.json["goals"]) == 1

        update_resp = client.put(
            f"/api/savings-goals/{goal_id}",
            json={"target_amount": 6000},
            headers={"X-CSRFToken": csrf},
        )
        assert update_resp.status_code == 200
        assert update_resp.json["target_amount"] == 6000.0

        delete_resp = client.delete(f"/api/savings-goals/{goal_id}", headers={"X-CSRFToken": csrf})
        assert delete_resp.status_code == 200

        list_after = client.get("/api/savings-goals")
        assert list_after.json["goals"] == []

    def test_create_rejects_invalid_goal_type(self, client):
        from src.dashboard.app import store

        chat_id = "goals_pro_invalid_type"
        _make_pro_postgres_user(store, chat_id)
        _login(client, store, chat_id)
        csrf = _csrf_token(client)

        resp = client.post(
            "/api/savings-goals",
            json={"goal_type": "not_a_real_type", "name": "X", "target_amount": 100},
            headers={"X-CSRFToken": csrf},
        )
        assert resp.status_code == 400

    def test_account_balance_requires_valid_account_id(self, client):
        from src.dashboard.app import store

        chat_id = "goals_pro_bad_account"
        _make_pro_postgres_user(store, chat_id)
        _login(client, store, chat_id)
        csrf = _csrf_token(client)

        resp = client.post(
            "/api/savings-goals",
            json={"goal_type": "account_balance", "name": "X", "target_amount": 100, "account_id": 9999},
            headers={"X-CSRFToken": csrf},
        )
        assert resp.status_code == 400

    def test_update_returns_404_for_unknown_goal(self, client):
        from src.dashboard.app import store

        chat_id = "goals_pro_404"
        _make_pro_postgres_user(store, chat_id)
        _login(client, store, chat_id)
        csrf = _csrf_token(client)

        resp = client.put(
            "/api/savings-goals/999999", json={"name": "x"}, headers={"X-CSRFToken": csrf},
        )
        assert resp.status_code == 404

    def test_delete_returns_404_for_unknown_goal(self, client):
        from src.dashboard.app import store

        chat_id = "goals_pro_404_delete"
        _make_pro_postgres_user(store, chat_id)
        _login(client, store, chat_id)
        csrf = _csrf_token(client)

        resp = client.delete("/api/savings-goals/999999", headers={"X-CSRFToken": csrf})
        assert resp.status_code == 404


class TestSummaryAndHistory:
    def test_summary_reflects_active_goals(self, client):
        from src.dashboard.app import store

        chat_id = "goals_pro_summary"
        _make_pro_postgres_user(store, chat_id)
        _login(client, store, chat_id)
        csrf = _csrf_token(client)

        client.post(
            "/api/savings-goals",
            json={"goal_type": "net_savings", "name": "G1", "target_amount": 1000},
            headers={"X-CSRFToken": csrf},
        )
        resp = client.get("/api/savings-goals/summary")
        assert resp.status_code == 200
        assert resp.json["count"] == 1

    def test_history_empty_for_new_goal(self, client):
        from src.dashboard.app import store

        chat_id = "goals_pro_history"
        _make_pro_postgres_user(store, chat_id)
        _login(client, store, chat_id)
        csrf = _csrf_token(client)

        create_resp = client.post(
            "/api/savings-goals",
            json={"goal_type": "net_savings", "name": "G1", "target_amount": 1000},
            headers={"X-CSRFToken": csrf},
        )
        goal_id = create_resp.json["id"]

        resp = client.get(f"/api/savings-goals/{goal_id}/history")
        assert resp.status_code == 200
        assert resp.json["history"] == []
