from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.integration


def test_get_storage_expires_cached_postgres_session(monkeypatch):
    """Una PostgresStorage cachata deve fare expire_all() ad ogni riuso.

    Senza questo refresh, un edit fatto dalla webapp (sessione SQLAlchemy diversa) su
    una riga già caricata nella identity map della sessione cachata dal bot resta
    invisibile fino allo scadere del TTL (bug: data abbonamento non propagata).
    """
    import bot
    from src.storage.postgres_storage import PostgresStorage

    fake_session = MagicMock()
    fake_storage = MagicMock(spec=PostgresStorage)
    fake_storage._session = fake_session

    chat_id = "999999"
    monkeypatch.setitem(bot._storage_clients, chat_id, fake_storage)

    result = bot._get_storage(chat_id)

    assert result is fake_storage
    fake_session.expire_all.assert_called_once()


def test_get_storage_notion_backend_untouched(monkeypatch):
    """Il refresh riguarda solo PostgresStorage: il client Notion cachato non deve
    ricevere alcuna chiamata extra (nessuna sessione DB da invalidare)."""
    import bot

    fake_notion_storage = MagicMock()
    chat_id = "999998"
    monkeypatch.setitem(bot._storage_clients, chat_id, fake_notion_storage)

    result = bot._get_storage(chat_id)

    assert result is fake_notion_storage
    fake_notion_storage.assert_not_called()
