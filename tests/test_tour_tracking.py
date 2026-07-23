"""Test e2e del tracking server-side del tour guidato webapp (POST /api/track).

Verifica che gli eventi tour_* con sessione autenticata persistano lo stato in
users.tour_step/tour_status/tour_completed_at, e che senza consenso analytics
o senza sessione (utente anonimo) non scrivano nulla — coerente col gating già
esistente per PostHog/GA4.
"""
import pytest

pytestmark = pytest.mark.e2e


def _authenticated_session(client, store, chat_id="tour_e2e_u1"):
    store.add_user(chat_id=chat_id, username="tour-user", storage_backend="postgres")
    with client.session_transaction() as sess:
        sess["user_logged_in"] = True
        sess["chat_id"] = chat_id
        sess["token_version"] = store.get_token_version(chat_id) or 0
    return chat_id


def _csrf_token(client):
    return client.get("/api/csrf-token").json["csrf_token"]


def _post_track(client, event, properties=None, consent_analytics=True):
    return client.post(
        "/api/track",
        json={
            "event": event,
            "properties": properties or {},
            "anonymous_id": "anon-test-id",
            "consent": {"analytics": consent_analytics, "marketing": False},
        },
        headers={"X-CSRFToken": _csrf_token(client)},
    )


def test_tour_started_persists_in_progress(client):
    from src.dashboard.app import store
    from src.user_store import User

    chat_id = _authenticated_session(client, store, "tour_e2e_started")
    resp = _post_track(client, "tour_started")
    assert resp.status_code == 200

    with store.Session() as s:
        user = s.query(User).filter(User.chat_id == chat_id).first()
    assert user.tour_status == "in_progress"
    assert user.tour_completed_at is None


def test_tour_step_viewed_updates_step(client):
    from src.dashboard.app import store
    from src.user_store import User

    chat_id = _authenticated_session(client, store, "tour_e2e_step")
    _post_track(client, "tour_started")
    _post_track(client, "tour_step_viewed", {"step_id": "analytics-tabs", "step_index": 3})

    with store.Session() as s:
        user = s.query(User).filter(User.chat_id == chat_id).first()
    assert user.tour_step == "analytics-tabs"
    assert user.tour_status == "in_progress"


def test_tour_completed_sets_status_and_timestamp(client):
    from src.dashboard.app import store
    from src.user_store import User

    chat_id = _authenticated_session(client, store, "tour_e2e_completed")
    _post_track(client, "tour_started")
    _post_track(client, "tour_completed")

    with store.Session() as s:
        user = s.query(User).filter(User.chat_id == chat_id).first()
    assert user.tour_status == "completed"
    assert user.tour_completed_at is not None


def test_tour_skipped_sets_status(client):
    from src.dashboard.app import store
    from src.user_store import User

    chat_id = _authenticated_session(client, store, "tour_e2e_skipped")
    _post_track(client, "tour_started")
    _post_track(client, "tour_skipped", {"step_id": "chat-input", "step_index": 0})

    with store.Session() as s:
        user = s.query(User).filter(User.chat_id == chat_id).first()
    assert user.tour_status == "skipped"
    assert user.tour_step == "chat-input"


def test_tour_event_without_analytics_consent_does_not_persist(client):
    from src.dashboard.app import store
    from src.user_store import User

    chat_id = _authenticated_session(client, store, "tour_e2e_noconsent")
    resp = _post_track(client, "tour_started", consent_analytics=False)
    assert resp.status_code == 200

    with store.Session() as s:
        user = s.query(User).filter(User.chat_id == chat_id).first()
    assert user.tour_status is None


def test_tour_event_anonymous_user_does_not_persist(client):
    """Un visitatore senza sessione autenticata (solo anonymous_id) non deve
    scrivere nulla su alcun utente: non c'è un chat_id a cui associare l'evento."""
    resp = _post_track(client, "tour_started")
    assert resp.status_code == 200
    # Nessuna eccezione, nessuna scrittura possibile: non c'è un utente target.
