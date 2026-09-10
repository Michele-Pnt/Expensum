"""Notion adapter contracts for local authoritative income categories."""

from datetime import date
from unittest.mock import MagicMock

import pytest

from src.storage.notion_storage import NotionStorage


pytestmark = pytest.mark.integration


def test_notion_adapter_uses_tenant_scoped_local_category_id(mock_db_session) -> None:
    """Notion keeps its select while the local category resolver owns the ID."""
    store = mock_db_session
    store.add_user(chat_id="notion-a", username="a", storage_backend="notion")
    store.add_user(chat_id="notion-b", username="b", storage_backend="notion")
    client = MagicMock()
    client.create_income.return_value = {"id": "notion-income"}
    adapter = NotionStorage(client, store=store, user_id="notion-a")
    other = NotionStorage(MagicMock(), store=store, user_id="notion-b")

    category = adapter.create_income_category("Consulenza")
    foreign = other.create_income_category("Riservata")
    result = adapter.create_income(
        date(2026, 9, 2), 120, "Cliente", "notion-account",
        income_category_id=category["id"], income_category_name="Obsoleto",
    )

    assert result["income_category_id"] == category["id"]
    assert result["income_category"] == "Consulenza"
    client.create_income.assert_called_once_with(
        date(2026, 9, 2), 120, "Cliente", "notion-account", "Consulenza",
    )
    with pytest.raises(ValueError, match="Income category not found"):
        adapter.create_income(date(2026, 9, 2), 1, "No", "a", income_category_id=foreign["id"])

    renamed = adapter.update_income_category(category["id"], name="Consulenza Pro")
    assert renamed is not None and renamed["name"] == "Consulenza Pro"
    client.replace_income_type.assert_called_once_with("Consulenza", "Consulenza Pro")

    deleted = adapter.delete_income_category(category["id"])
    assert deleted == {"incomes": client.replace_income_type.return_value}
    client.replace_income_type.assert_called_with("Consulenza Pro", "Altra entrata")


def test_notion_fetch_income_uses_one_category_lookup_for_known_rows(mock_db_session, monkeypatch) -> None:
    """A batch of known Notion incomes must not reload the local cache per row."""
    store = mock_db_session
    store.add_user(chat_id="notion-batch", username="batch", storage_backend="notion")
    client = MagicMock()
    client.fetch_income.return_value = [
        {"id": "one", "income_type": "Consulenza"},
        {"id": "two", "income_type": "Consulenza"},
    ]
    adapter = NotionStorage(client, store=store, user_id="notion-batch")
    adapter.create_income_category("Consulenza")
    original = store.get_user_income_categories
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "get_user_income_categories", counted)
    rows = adapter.fetch_income(date(2026, 9, 1), date(2026, 9, 2))

    assert calls == 1
    assert [row["income_category"]["name"] if isinstance(row["income_category"], dict) else row["income_category"] for row in rows] == ["Consulenza", "Consulenza"]
    assert all(row["income_category_id"] is not None for row in rows)


def test_notion_legacy_income_converges_to_a_local_category_and_rename_rejects_case_duplicate(mock_db_session) -> None:
    """Unknown legacy values become tenant-owned metadata and case duplicates are rejected."""
    store = mock_db_session
    store.add_user(chat_id="notion-legacy", username="legacy", storage_backend="notion")
    client = MagicMock()
    client.fetch_income.return_value = [{"id": "legacy", "income_type": "Consulenza storica"}]
    adapter = NotionStorage(client, store=store, user_id="notion-legacy")

    fetched = adapter.fetch_income(date(2026, 9, 1), date(2026, 9, 2))[0]
    assert fetched["income_category"] == "Consulenza storica"
    assert fetched["income_category_id"] is not None

    first = adapter.create_income_category("Freelance")
    second = adapter.create_income_category("Rimborso straordinario")
    with pytest.raises(ValueError, match="already exists"):
        adapter.update_income_category(second["id"], name="freelance")
    assert adapter.get_income_categories(True)


def test_notion_rename_persists_retry_state_after_partial_remote_failure(mock_db_session) -> None:
    """A failed remote rename stays resumable and blocks a divergent local rename."""
    from src.storage.models import IncomeCategoryNotionSyncTask

    store = mock_db_session
    store.add_user(chat_id="notion-outbox", username="outbox", storage_backend="notion")
    client = MagicMock()
    adapter = NotionStorage(client, store=store, user_id="notion-outbox")
    category = adapter.create_income_category("Freelance")
    client.replace_income_type.side_effect = RuntimeError("temporary Notion failure")

    with pytest.raises(RuntimeError, match="temporary Notion failure"):
        adapter.update_income_category(category["id"], name="Consulenza")

    with store._user_session("notion-outbox") as session:
        task = session.query(IncomeCategoryNotionSyncTask).one()
        assert (task.operation, task.previous_name, task.next_name) == (
            "rename", "Freelance", "Consulenza",
        )
    assert next(
        row for row in adapter.get_income_categories() if row["id"] == category["id"]
    )["name"] == "Freelance"

    client.replace_income_type.side_effect = None
    client.replace_income_type.return_value = 2
    completed = adapter.update_income_category(category["id"], name="Consulenza")

    assert completed is not None and completed["name"] == "Consulenza"
    with store._user_session("notion-outbox") as session:
        assert session.query(IncomeCategoryNotionSyncTask).count() == 0


def test_notion_delete_partial_failure_keeps_a_single_local_category_view(mock_db_session) -> None:
    """Rows already moved in Notion stay attributed to the old category until retry completes."""
    store = mock_db_session
    store.add_user(chat_id="notion-delete-outbox", username="outbox", storage_backend="notion")
    client = MagicMock()
    adapter = NotionStorage(client, store=store, user_id="notion-delete-outbox")
    category = adapter.create_income_category("Freelance")
    client.get_income_type_page_ids.return_value = ["old", "already-updated"]
    client.replace_income_type_page_ids.side_effect = RuntimeError("partial remote failure")

    with pytest.raises(RuntimeError, match="partial remote failure"):
        adapter.delete_income_category(category["id"])

    client.fetch_income.return_value = [
        {"id": "old", "income_type": "Freelance"},
        {"id": "already-updated", "income_type": "Altra entrata"},
        {"id": "pre-existing-fallback", "income_type": "Altra entrata"},
    ]
    rows = adapter.fetch_income(date(2026, 9, 1), date(2026, 9, 2))

    assert [row["income_category"] for row in rows] == [
        "Freelance", "Freelance", "Altra entrata",
    ]


def test_notion_outbox_can_be_retried_without_another_category_mutation(mock_db_session) -> None:
    """The durable retry entrypoint finishes a queued rename without a new user action."""
    from src.storage.models import IncomeCategoryNotionSyncTask

    store = mock_db_session
    store.add_user(chat_id="notion-autonomous-retry", username="outbox", storage_backend="notion")
    client = MagicMock()
    adapter = NotionStorage(client, store=store, user_id="notion-autonomous-retry")
    category = adapter.create_income_category("Freelance")
    client.replace_income_type.side_effect = RuntimeError("temporary Notion failure")

    with pytest.raises(RuntimeError, match="temporary Notion failure"):
        adapter.update_income_category(category["id"], name="Consulenza")

    client.replace_income_type.side_effect = None
    client.replace_income_type.return_value = 2
    assert adapter.retry_pending_income_category_syncs() == 1
    with store._user_session("notion-autonomous-retry") as session:
        assert session.query(IncomeCategoryNotionSyncTask).count() == 0
