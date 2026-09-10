"""
tests/test_notion_client.py — Test per la discovery dei database Notion.

discover_databases() ritorna una tupla (discovered_map: dict, all_candidates: list).
"""

import pytest
from unittest.mock import MagicMock, call, patch
from notion_client.errors import APIResponseError
from src.notion_client import NotionFinanceClient

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_notion_client():
    with patch("notion_client.Client") as mock:
        yield mock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_page_result(page_id: str, title: str) -> dict:
    """Costruisce un risultato di tipo 'page' compatibile con la Notion search API."""
    return {
        "object": "page",
        "id": page_id,
        "properties": {
            "title": {
                "type": "title",
                "title": [{"plain_text": title}],
            }
        },
    }


_SEVEN_DATABASES = [
    {"type": "child_database", "id": "exp_id", "child_database": {"title": "Expense"}},
    {"type": "child_database", "id": "inc_id", "child_database": {"title": "Income"}},
    {"type": "child_database", "id": "cat_id", "child_database": {"title": "Categories"}},
    {"type": "child_database", "id": "mb_id",  "child_database": {"title": "Monthly Balance"}},
    {"type": "child_database", "id": "acc_id", "child_database": {"title": "Accounts"}},
    {"type": "child_database", "id": "sub_id", "child_database": {"title": "Subscriptions"}},
    {"type": "child_database", "id": "pay_id", "child_database": {"title": "Pay/Transfer"}},
]


# ---------------------------------------------------------------------------
# Strategia 0 — traversal mirato: root → "Databases" → child_database
# ---------------------------------------------------------------------------

def test_discover_databases_strategy_0(mock_notion_client):
    """Strategy 0: trova tutti i DB reali dentro la sub-page 'Databases' della root."""
    mock_instance = mock_notion_client.return_value

    # 1. search trova la pagina root "Dashboard Expensum Finance"
    mock_instance.search.return_value = {
        "results": [_make_page_result("root_id", "Dashboard Expensum Finance")]
    }

    # 2. blocks.children.list: due chiamate distinte per root e per sub-page Databases
    def children_side_effect(block_id, **kwargs):
        if block_id == "root_id":
            return {"results": [
                {"type": "child_page", "id": "dbs_page_id", "child_page": {"title": "Databases"}},
                {"type": "child_page", "id": "other_id",   "child_page": {"title": "Views"}},
            ]}
        if block_id == "dbs_page_id":
            return {"results": _SEVEN_DATABASES}
        return {"results": []}

    mock_instance.blocks.children.list.side_effect = children_side_effect

    discovered, candidates = NotionFinanceClient.discover_databases("fake_token")

    assert len(discovered) == 7
    assert discovered["expense_db_id"] == "exp_id"
    assert discovered["categories_db_id"] == "cat_id"
    assert discovered["income_db_id"] == "inc_id"
    assert discovered["accounts_db_id"] == "acc_id"
    assert discovered["subscriptions_db_id"] == "sub_id"
    assert discovered["monthly_balance_db_id"] == "mb_id"
    assert discovered["pay_transfer_db_id"] == "pay_id"


@patch("src.notion_client.Client")
def test_replace_income_type_updates_only_matching_legacy_pages(mock_client_class):
    """Rinominare/eliminare una categoria non deve toccare altre entrate Notion."""
    client = NotionFinanceClient(api_key="test", income_db_id="income-db")
    client._get_data_source_id = MagicMock(return_value="income-source")
    client._get_property_name = MagicMock(return_value="Income Type")
    client._query_with_retry = MagicMock(return_value={
        "results": [
            {"id": "match", "properties": {"Income Type": {"select": {"name": "Freelance"}}}},
            {"id": "other", "properties": {"Income Type": {"select": {"name": "Stipendio"}}}},
        ],
        "has_more": False,
    })
    client._client.pages.retrieve.return_value = {
        "properties": {"Income Type": {"select": {"name": "Freelance"}}},
    }

    updated = client.replace_income_type("Freelance", "Altra entrata")

    assert updated == 1
    client._client.pages.update.assert_called_once_with(
        page_id="match",
        properties={"Income Type": {"select": {"name": "Altra entrata"}}},
    )


@patch("src.notion_client.Client")
def test_replace_income_type_page_ids_updates_only_the_snapshot(mock_client_class):
    """A durable outbox must not touch rows added after its snapshot was taken."""
    client = NotionFinanceClient(api_key="test", income_db_id="income-db")
    client._get_property_name = MagicMock(return_value="Income Type")
    client._client.pages.retrieve.side_effect = [
        {"properties": {"Income Type": {"select": {"name": "Freelance"}}}},
        {"properties": {"Income Type": {"select": {"name": "Freelance"}}}},
    ]

    updated = client.replace_income_type_page_ids(
        ["original-one", "original-two"], "Freelance", "Altra entrata",
    )

    assert updated == 2
    assert client._client.pages.update.call_args_list == [
        call(
            page_id="original-one",
            properties={"Income Type": {"select": {"name": "Altra entrata"}}},
        ),
        call(
            page_id="original-two",
            properties={"Income Type": {"select": {"name": "Altra entrata"}}},
        ),
    ]


@patch("src.notion_client.Client")
def test_replace_income_type_page_ids_preserves_concurrent_edits_and_missing_pages(mock_client_class):
    """Retry changes only still-matching pages and treats a deleted page as reconciled."""
    client = NotionFinanceClient(api_key="test", income_db_id="income-db")
    client._get_property_name = MagicMock(return_value="Income Type")
    client._client.pages.retrieve.side_effect = [
        {"properties": {"Income Type": {"select": {"name": "Freelance"}}}},
        {"properties": {"Income Type": {"select": {"name": "Stipendio"}}}},
        APIResponseError("object_not_found", 404, "gone", {}, ""),
    ]

    updated = client.replace_income_type_page_ids(
        ["still-old", "edited-elsewhere", "deleted"], "Freelance", "Altra entrata",
    )

    assert updated == 1
    client._client.pages.update.assert_called_once_with(
        page_id="still-old",
        properties={"Income Type": {"select": {"name": "Altra entrata"}}},
    )


def test_discover_databases_strategy_0_skips_linked_views(mock_notion_client):
    """Strategy 0 deve ignorare le linked views al top level della root."""
    mock_instance = mock_notion_client.return_value

    mock_instance.search.return_value = {
        "results": [_make_page_result("root_id", "Dashboard Expensum Finance")]
    }

    def children_side_effect(block_id, **kwargs):
        if block_id == "root_id":
            return {"results": [
                {"type": "child_page", "id": "dbs_page_id", "child_page": {"title": "Databases"}},
                # Le linked views al top level NON devono essere scoperte
                {"type": "child_database", "id": "WRONG_linked_view", "child_database": {"title": "View of Accounts"}},
            ]}
        if block_id == "dbs_page_id":
            return {"results": _SEVEN_DATABASES}
        return {"results": []}

    mock_instance.blocks.children.list.side_effect = children_side_effect

    discovered, _ = NotionFinanceClient.discover_databases("fake_token")

    # Strategy 0 legge solo i figli di dbs_page_id, non quelli della root
    assert "WRONG_linked_view" not in discovered.values()
    assert discovered["accounts_db_id"] == "acc_id"


# ---------------------------------------------------------------------------
# Strategia 1 — scansione del template (template_page_id esplicito)
# ---------------------------------------------------------------------------

def test_discover_databases_strategy_1_with_template_id(mock_notion_client):
    """Strategy 1: discovery tramite template_page_id.

    Il flusso reale è:
      1. _list_children("tpl_123") → trova la sub-page "Databases"
      2. _list_children("dbs_page_id") → trova i 7 child_database

    Il mock deve rispecchiare questa struttura a due livelli.
    """
    mock_instance = mock_notion_client.return_value

    def children_side_effect(block_id, **kwargs):
        if block_id == "tpl_123":
            return {
                "results": [
                    {"type": "child_page", "id": "dbs_page_id", "child_page": {"title": "Databases"}},
                ],
                "has_more": False,
            }
        if block_id == "dbs_page_id":
            return {"results": _SEVEN_DATABASES, "has_more": False}
        return {"results": [], "has_more": False}

    mock_instance.blocks.children.list.side_effect = children_side_effect

    discovered, candidates = NotionFinanceClient.discover_databases(
        "fake_token", template_page_id="tpl_123"
    )

    assert len(discovered) == 7
    assert discovered["expense_db_id"] == "exp_id"
    assert discovered["categories_db_id"] == "cat_id"
    assert len(candidates) == 7


# ---------------------------------------------------------------------------
# Strategia 2 — ricerca globale (fallback)
# ---------------------------------------------------------------------------

def test_discover_databases_strategy_2_global_search(mock_notion_client):
    """Strategy 2: fallback su search globale quando Strategy 0 e 1 falliscono."""
    mock_instance = mock_notion_client.return_value

    def search_side_effect(query=None, **kwargs):
        # Strategy 0: root non trovata
        if query == "Dashboard Expensum Finance":
            return {"results": []}
        # Strategy 2: search globale → restituisce una pagina finance che contiene i DB
        return {
            "results": [
                {"object": "page", "id": "finance_page_id",
                 "properties": {"title": {"type": "title", "title": [{"plain_text": "Finance Dashboard"}]}}},
            ]
        }

    mock_instance.search.side_effect = search_side_effect

    # blocks.children.list sulla pagina finance restituisce i 7 DB
    mock_instance.blocks.children.list.return_value = {"results": _SEVEN_DATABASES}

    discovered, _ = NotionFinanceClient.discover_databases("fake_token")

    assert discovered["expense_db_id"] == "exp_id"
    assert mock_instance.search.called
