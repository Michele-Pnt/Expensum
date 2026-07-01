"""Test per src/breach_notifier.py — comunicazione violazione agli interessati (Art. 34)."""

import asyncio

import pytest

import src.breach_notifier as breach_notifier
from src.breach_notifier import notify_users_of_breach
from src.user_store import AuditLog

pytestmark = pytest.mark.integration


class _FakeTelegramClient:
    """Fake di TelegramClient: registra gli invii e può fallire su chat_id scelti."""

    sent: list[str] = []
    fail_for: set[str] = set()

    def __init__(self, chat_id=None):
        self._chat_id = chat_id

    async def send_report(self, text: str) -> None:
        if self._chat_id in self.fail_for:
            raise RuntimeError("invio fallito (simulato)")
        _FakeTelegramClient.sent.append(self._chat_id)


@pytest.fixture(autouse=True)
def _patch_telegram(monkeypatch):
    _FakeTelegramClient.sent = []
    _FakeTelegramClient.fail_for = set()
    monkeypatch.setattr(breach_notifier, "TelegramClient", _FakeTelegramClient)
    yield


def _seed_active_users(store, n: int) -> None:
    for i in range(n):
        store.add_user(chat_id=f"200{i}", email=f"user{i}@example.com")


def test_dry_run_counts_without_sending(mock_db_session):
    store = mock_db_session
    _seed_active_users(store, 3)
    ref = store.create_breach_record("test", risk_level="high")

    result = asyncio.run(
        notify_users_of_breach(store, ref, "Comunicazione di test", dry_run=True)
    )

    assert result.total_recipients == 3
    assert result.telegram_sent == 0
    assert _FakeTelegramClient.sent == []
    # Il record NON deve risultare notificato dopo un dry run.
    assert store.get_breach_record(ref).users_notified is False


def test_send_success_updates_record_and_audit(mock_db_session):
    store = mock_db_session
    _seed_active_users(store, 3)
    ref = store.create_breach_record("test", risk_level="high")

    result = asyncio.run(
        notify_users_of_breach(store, ref, "Abbiamo rilevato una violazione...")
    )

    assert result.telegram_sent == 3
    assert result.telegram_failed == 0
    assert len(_FakeTelegramClient.sent) == 3

    record = store.get_breach_record(ref)
    assert record.users_notified is True
    assert record.users_notified_at is not None

    with store.Session() as s:
        entry = s.query(AuditLog).filter_by(action="breach_notification").first()
        assert entry is not None
        assert entry.resource == ref
        assert entry.metadata_json["telegram_sent"] == 3


def test_per_user_failure_does_not_block_others(mock_db_session):
    store = mock_db_session
    _seed_active_users(store, 3)
    _FakeTelegramClient.fail_for = {"2001"}  # solo il secondo utente fallisce
    ref = store.create_breach_record("test", risk_level="high")

    result = asyncio.run(
        notify_users_of_breach(store, ref, "Comunicazione violazione")
    )

    assert result.telegram_sent == 2
    assert result.telegram_failed == 1
    assert result.failed_chat_ids == ["2001"]
    # Nonostante il fallimento parziale, il record è marcato come notificato.
    assert store.get_breach_record(ref).users_notified is True
