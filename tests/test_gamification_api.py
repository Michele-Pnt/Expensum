"""
tests/test_gamification_api.py — Gli endpoint REST di gamification.

Il payload di questi endpoint è pensato per essere renderizzato da una UI che
ancora non esiste: i test verificano che contenga tutto il necessario (catalogo
completo, non solo gli sbloccati; progresso parziale; motivo dell'indisponibilità)
e che non richieda al client di conoscere il catalogo per interpretarlo.
"""

import pytest

pytestmark = pytest.mark.e2e


def _login(client, store, chat_id="chat_gam", backend="postgres", plan="free"):
    """Crea un utente e apre una sessione browser valida per il test client."""
    store.add_user(chat_id=chat_id, username="tester", storage_backend=backend)
    store.set_user_plan(chat_id, plan, payment_reference="test")
    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = chat_id
        sess["token_version"] = store.get_token_version(chat_id)
    return chat_id


@pytest.fixture
def store():
    from src.dashboard.app import store as app_store
    return app_store


class TestAuthentication:
    def test_achievements_requires_auth(self, client):
        assert client.get("/api/gamification/achievements").status_code == 401

    def test_summary_requires_auth(self, client):
        assert client.get("/api/gamification/summary").status_code == 401

    def test_seen_requires_auth(self, client):
        assert client.post("/api/gamification/seen", json={}).status_code == 401


class TestAchievementsPayload:
    def test_returns_full_catalogue_for_a_new_user(self, client, store):
        _login(client, store, chat_id="gam_new")

        payload = client.get("/api/gamification/achievements").json

        assert payload["profile"]["level"] == 1
        assert payload["profile"]["total_xp"] == 0
        assert payload["profile"]["unlocked_count"] == 0
        total = sum(f["total"] for f in payload["families"])
        assert total > 40, "il catalogo completo, non solo quello che ho già preso"

    def test_every_achievement_is_self_describing(self, client, store):
        """La UI non deve conoscere il catalogo per renderizzarlo."""
        _login(client, store, chat_id="gam_desc")

        payload = client.get("/api/gamification/achievements").json
        item = payload["families"][0]["achievements"][0]

        assert set(item) >= {
            "code", "title", "description", "icon", "xp", "state", "progress",
        }
        assert item["title"] and item["description"]

    def test_progress_reflects_counters(self, client, store):
        from src.gamification import engine
        from src.gamification import metrics as M

        chat_id = _login(client, store, chat_id="gam_prog")
        engine.bump_metrics(store, chat_id, absolute={M.EXPENSES_TOTAL: 10})

        payload = client.get("/api/gamification/achievements").json
        volume = next(f for f in payload["families"] if f["code"] == "volume")
        first = volume["achievements"][0]

        assert first["state"] == "locked"
        assert first["progress"]["current"] == 10
        assert first["progress"]["pct"] == 40.0

    def test_unlocked_achievement_is_marked(self, client, store):
        from src.gamification import engine
        from src.gamification import metrics as M

        chat_id = _login(client, store, chat_id="gam_unlocked")
        engine.bump_metrics(store, chat_id, absolute={M.EXPENSES_TOTAL: 25})
        engine.evaluate(store, chat_id, families=("volume",))

        payload = client.get("/api/gamification/achievements").json
        volume = next(f for f in payload["families"] if f["code"] == "volume")
        first = next(a for a in volume["achievements"] if a["code"] == "volume_expenses_25")

        assert first["state"] == "unlocked"
        assert first["unlocked_at"] is not None
        assert payload["profile"]["unlocked_count"] == 1

    def test_goals_family_unavailable_for_free_user(self, client, store):
        _login(client, store, chat_id="gam_free", plan="free")

        payload = client.get("/api/gamification/achievements").json
        goals = next(f for f in payload["families"] if f["code"] == "goals")

        assert goals["state"] == "unavailable"
        assert goals["unavailable_reason"] == "requires_postgres_pro"
        assert goals["achievements"], "resta visibile come teaser, non sparisce"

    def test_goals_family_available_for_pro_postgres_user(self, client, store):
        _login(client, store, chat_id="gam_pro", plan="pro", backend="postgres")

        payload = client.get("/api/gamification/achievements").json
        goals = next(f for f in payload["families"] if f["code"] == "goals")
        assert goals["state"] == "available"

    def test_locale_switches_the_texts(self, client, store):
        _login(client, store, chat_id="gam_locale")

        it = client.get("/api/gamification/achievements?locale=it").json
        en = client.get("/api/gamification/achievements?locale=en").json

        assert it["locale"] == "it"
        assert en["locale"] == "en"
        it_first = it["families"][0]["achievements"][0]
        en_first = en["families"][0]["achievements"][0]
        assert it_first["code"] == en_first["code"]
        assert it_first["description"] != en_first["description"]

    def test_unknown_locale_falls_back_to_italian(self, client, store):
        _login(client, store, chat_id="gam_badlocale")
        assert client.get("/api/gamification/achievements?locale=xx").json["locale"] == "it"


class TestSummary:
    def test_lists_closest_achievements(self, client, store):
        from src.gamification import engine
        from src.gamification import metrics as M

        chat_id = _login(client, store, chat_id="gam_sum")
        engine.bump_metrics(store, chat_id, absolute={M.EXPENSES_TOTAL: 20})

        payload = client.get("/api/gamification/summary").json

        assert payload["profile"]["level"] == 1
        assert payload["next_up"][0]["code"] == "volume_expenses_25"
        assert len(payload["next_up"]) <= 3


class TestMarkSeen:
    def test_clears_unseen_unlocks(self, client, store):
        from src.gamification import engine
        from src.gamification import metrics as M

        chat_id = _login(client, store, chat_id="gam_seen")
        engine.bump_metrics(store, chat_id, absolute={M.EXPENSES_TOTAL: 25})
        engine.evaluate(store, chat_id, families=("volume",))

        assert client.get("/api/gamification/summary").json["unseen_unlocks"]

        csrf = client.get("/api/csrf-token").json["csrf_token"]
        response = client.post(
            "/api/gamification/seen",
            json={"codes": None},
            headers={"X-CSRFToken": csrf},
        )
        assert response.status_code == 200
        assert response.json["updated"] == 1
        assert client.get("/api/gamification/summary").json["unseen_unlocks"] == []

    def test_rejects_malformed_codes(self, client, store):
        _login(client, store, chat_id="gam_badseen")
        csrf = client.get("/api/csrf-token").json["csrf_token"]

        response = client.post(
            "/api/gamification/seen",
            json={"codes": "non-una-lista"},
            headers={"X-CSRFToken": csrf},
        )
        assert response.status_code == 400
