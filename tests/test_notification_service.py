"""tests/test_notification_service.py — Centro notifiche in-app (src/notification_service.py).

Usa SQLite in-memory tramite la fixture `mock_db_session` (stesso pattern di
tests/test_gamification_hooks.py): la tabella `notifications` ha una FK reale
verso `users.chat_id`, quindi serve un utente persistito prima di creare notifiche.
Tier `integration` per via del DB, nessuna dipendenza esterna da mockare.
"""

from datetime import datetime

import pytest

from src.notification_service import (
    count_unread,
    create_notification,
    list_notifications,
    mark_all_read,
    mark_read,
)
from src.storage.models import Notification

pytestmark = pytest.mark.integration


@pytest.fixture
def store(mock_db_session):
    mock_db_session.add_user(chat_id="u1")
    mock_db_session.add_user(chat_id="u2")
    return mock_db_session


class TestCreateNotification:
    def test_creates_and_persists_notification(self, store):
        with store.Session() as session:
            notif = create_notification(
                session, "u1", "budget_reached", "Budget Alimentari raggiunto",
                "Hai speso €100 su €100 per Alimentari questo mese.",
            )
            assert notif.id is not None
            assert notif.user_id == "u1"
            assert notif.type == "budget_reached"
            assert notif.priority == "info"
            assert notif.read_at is None

        with store.Session() as session:
            rows = session.query(Notification).filter_by(user_id="u1").all()
            assert len(rows) == 1

    def test_accepts_valid_priority(self, store):
        with store.Session() as session:
            notif = create_notification(
                session, "u1", "budget_exceeded", "Budget superato", "body",
                priority="critical",
            )
            assert notif.priority == "critical"

    def test_unknown_priority_falls_back_to_info(self, store):
        """Non deve mai bloccare l'evento che genera la notifica: tipo/priority
        ignoti passano, solo la priority viene sanata a 'info'."""
        with store.Session() as session:
            notif = create_notification(
                session, "u1", "some_new_type", "Titolo", "body",
                priority="urgentissimo",
            )
            assert notif.priority == "info"
            assert notif.type == "some_new_type"

    def test_stores_payload_dict(self, store):
        with store.Session() as session:
            notif = create_notification(
                session, "u1", "monthly_report", "Report pronto", "body",
                payload={"share_token": "abc123"},
            )
            assert notif.payload == {"share_token": "abc123"}

    def test_chat_id_cast_to_string(self, store):
        """chat_id può arrivare come int da Telegram: la colonna è String."""
        with store.Session() as session:
            notif = create_notification(session, 12345, "admin_message", "T", "b")
            assert notif.user_id == "12345"


class TestListNotifications:
    def test_orders_most_recent_first(self, store):
        with store.Session() as session:
            create_notification(session, "u1", "admin_message", "Primo", "b")
            create_notification(session, "u1", "admin_message", "Secondo", "b")
            create_notification(session, "u1", "admin_message", "Terzo", "b")

        with store.Session() as session:
            results = list_notifications(session, "u1")
            assert [n.title for n in results] == ["Terzo", "Secondo", "Primo"]

    def test_filters_by_user(self, store):
        with store.Session() as session:
            create_notification(session, "u1", "admin_message", "Per u1", "b")
            create_notification(session, "u2", "admin_message", "Per u2", "b")

        with store.Session() as session:
            results = list_notifications(session, "u1")
            assert len(results) == 1
            assert results[0].title == "Per u1"

    def test_unread_only_filter(self, store):
        with store.Session() as session:
            n1 = create_notification(session, "u1", "admin_message", "Non letta", "b")
            n2 = create_notification(session, "u1", "admin_message", "Letta", "b")
            n2.read_at = datetime.utcnow()
            session.commit()

        with store.Session() as session:
            results = list_notifications(session, "u1", unread_only=True)
            assert [n.title for n in results] == ["Non letta"]

    def test_respects_limit(self, store):
        with store.Session() as session:
            for i in range(5):
                create_notification(session, "u1", "admin_message", f"N{i}", "b")

        with store.Session() as session:
            results = list_notifications(session, "u1", limit=2)
            assert len(results) == 2

    def test_before_id_pages_backward(self, store):
        with store.Session() as session:
            create_notification(session, "u1", "admin_message", "N1", "b")
            n2 = create_notification(session, "u1", "admin_message", "N2", "b")
            create_notification(session, "u1", "admin_message", "N3", "b")

        with store.Session() as session:
            results = list_notifications(session, "u1", before_id=n2.id + 1)
            titles = [n.title for n in results]
            assert "N3" not in titles


class TestCountUnread:
    def test_counts_only_unread_for_user(self, store):
        with store.Session() as session:
            create_notification(session, "u1", "admin_message", "A", "b")
            n2 = create_notification(session, "u1", "admin_message", "B", "b")
            create_notification(session, "u2", "admin_message", "C", "b")
            n2.read_at = datetime.utcnow()
            session.commit()

        with store.Session() as session:
            assert count_unread(session, "u1") == 1
            assert count_unread(session, "u2") == 1

    def test_zero_when_no_notifications(self, store):
        with store.Session() as session:
            assert count_unread(session, "u1") == 0


class TestMarkRead:
    def test_marks_existing_unread_notification(self, store):
        with store.Session() as session:
            notif = create_notification(session, "u1", "admin_message", "A", "b")
            notif_id = notif.id

        with store.Session() as session:
            assert mark_read(session, "u1", notif_id) is True

        with store.Session() as session:
            row = session.get(Notification, notif_id)
            assert row.read_at is not None

    def test_idempotent_on_already_read(self, store):
        with store.Session() as session:
            notif = create_notification(session, "u1", "admin_message", "A", "b")
            notif_id = notif.id

        with store.Session() as session:
            assert mark_read(session, "u1", notif_id) is True
            first_read_at = session.get(Notification, notif_id).read_at

        with store.Session() as session:
            assert mark_read(session, "u1", notif_id) is True
            assert session.get(Notification, notif_id).read_at == first_read_at

    def test_returns_false_for_missing_notification(self, store):
        with store.Session() as session:
            assert mark_read(session, "u1", 9999) is False

    def test_returns_false_for_other_users_notification(self, store):
        """Un utente non può segnare come letta una notifica altrui."""
        with store.Session() as session:
            notif = create_notification(session, "u2", "admin_message", "A", "b")
            notif_id = notif.id

        with store.Session() as session:
            assert mark_read(session, "u1", notif_id) is False
            row = session.get(Notification, notif_id)
            assert row.read_at is None


class TestMarkAllRead:
    def test_marks_all_unread_for_user_and_returns_count(self, store):
        with store.Session() as session:
            create_notification(session, "u1", "admin_message", "A", "b")
            create_notification(session, "u1", "admin_message", "B", "b")
            create_notification(session, "u2", "admin_message", "C", "b")

        with store.Session() as session:
            updated = mark_all_read(session, "u1")
            assert updated == 2

        with store.Session() as session:
            assert count_unread(session, "u1") == 0
            assert count_unread(session, "u2") == 1

    def test_zero_when_nothing_to_mark(self, store):
        with store.Session() as session:
            assert mark_all_read(session, "u1") == 0
