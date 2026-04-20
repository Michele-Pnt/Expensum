"""
tests/test_category_sync_e2e.py — Test end-to-end per il sistema user_categories / system_categories.

Copre:
  1. system_categories — tabella seeded con le 32 categorie di default
  2. Postgres path — compute_category_averages: spese → medie → user_categories
  3. Notion path   — sync_categories_to_local: mock API → user_categories
  4. Router        — refresh_category_averages instrada correttamente per backend
  5. Upsert idempotenza — upsert_user_categories aggiorna senza duplicati
  6. Lookup helpers — get_notion_page_id_for_category, get_category_by_notion_page_id

Usa SQLite in-memory: nessuna dipendenza da DB reale o servizi esterni.
"""

import pytest
from datetime import date
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.user_store import Base, User, UserStore
from src.storage.models import Expense, SystemCategory, UserCategory
from src.category_sync import (
    compute_category_averages,
    sync_categories_to_local,
    refresh_category_averages,
)

SYSTEM_CATEGORIES_COUNT = 32  # categorie definite nella migration b2c3d4e5f6a7

# ---------------------------------------------------------------------------
# Fixture condivise
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    # Seed system_categories (replica ciò che fa la migration Alembic)
    _seed_system_categories(eng)
    return eng


def _seed_system_categories(eng):
    names = [
        "Alimentari", "Ristoranti", "Bar/Caffè", "Trasporti", "Benzina",
        "Taxi", "Parcheggio", "Salute", "Farmacia", "Casa", "Bollette",
        "Affitto", "Intrattenimento", "Cinema", "Gaming", "Streaming",
        "Musica", "Sport", "Palestra", "Abbigliamento", "Cosmesi",
        "Tecnologia", "Viaggi", "Regali", "Istruzione", "Libri",
        "Animali", "Lavanderia", "Tabacchi", "Banca/Finanza",
        "Assicurazione", "Altro",
    ]
    Session = sessionmaker(bind=eng)
    with Session() as s:
        s.add_all([SystemCategory(name=n) for n in names])
        s.commit()


@pytest.fixture
def store(engine):
    """UserStore connesso all'engine SQLite in-memory condiviso."""
    s = UserStore.__new__(UserStore)
    s.engine = engine
    s.Session = sessionmaker(bind=engine)
    return s


@pytest.fixture
def db_session(engine):
    """Session raw per ispezione diretta delle tabelle."""
    Session = sessionmaker(bind=engine)
    session = Session()

    session.add(User(chat_id="user_pg", username="pg_user", is_active=True, storage_backend="postgres"))
    session.add(User(chat_id="user_nt", username="nt_user", is_active=True, storage_backend="notion"))
    session.commit()

    yield session

    session.close()


# ---------------------------------------------------------------------------
# 1. system_categories — seed corretto
# ---------------------------------------------------------------------------

class TestSystemCategoriesSeeded:
    def test_count(self, db_session):
        cats = db_session.query(SystemCategory).all()
        assert len(cats) == SYSTEM_CATEGORIES_COUNT

    def test_contains_expected_names(self, db_session):
        names = {c.name for c in db_session.query(SystemCategory).all()}
        for expected in ("Alimentari", "Trasporti", "Salute", "Altro"):
            assert expected in names, f"'{expected}' mancante da system_categories"

    def test_names_are_unique(self, db_session):
        names = [c.name for c in db_session.query(SystemCategory).all()]
        assert len(names) == len(set(names)), "system_categories contiene duplicati"


# ---------------------------------------------------------------------------
# 2. Postgres path — compute_category_averages
# ---------------------------------------------------------------------------

class TestComputeCategoryAverages:
    def _add_expenses(self, session, user_id, rows):
        for r in rows:
            session.add(Expense(
                user_id=user_id,
                expense_date=r["date"],
                amount=r["amount"],
                name=r.get("name", "Voce"),
                category_name=r["category"],
                account_id="acc_1",
            ))
        session.commit()

    def _seed_user_categories(self, session, user_id, names):
        """Pre-inserisce righe in user_categories (average=0): simula il setup iniziale."""
        for name in names:
            session.add(UserCategory(user_id=user_id, name=name, average=0.0))
        session.commit()

    def test_single_category_single_month(self, db_session, store):
        self._seed_user_categories(db_session, "user_pg", ["Alimentari"])
        self._add_expenses(db_session, "user_pg", [
            {"date": date(2026, 4, 5), "amount": 30.0, "category": "Alimentari"},
            {"date": date(2026, 4, 12), "amount": 70.0, "category": "Alimentari"},
        ])

        compute_category_averages("user_pg", db_session, store)

        # 1 mese unico → media = totale / 1
        row = db_session.query(UserCategory).filter_by(
            user_id="user_pg", name="Alimentari"
        ).first()
        assert row is not None
        assert row.average == pytest.approx(100.0)

    def test_single_category_multiple_months(self, db_session, store):
        self._seed_user_categories(db_session, "user_pg", ["Trasporti"])
        self._add_expenses(db_session, "user_pg", [
            {"date": date(2026, 1, 10), "amount": 120.0, "category": "Trasporti"},
            {"date": date(2026, 2, 15), "amount": 60.0, "category": "Trasporti"},
            {"date": date(2026, 3, 20), "amount": 90.0, "category": "Trasporti"},
        ])

        compute_category_averages("user_pg", db_session, store)

        row = db_session.query(UserCategory).filter_by(
            user_id="user_pg", name="Trasporti"
        ).first()
        assert row.average == pytest.approx(90.0)  # 270 / 3 mesi

    def test_multiple_categories(self, db_session, store):
        self._seed_user_categories(db_session, "user_pg", ["Alimentari", "Cinema"])
        self._add_expenses(db_session, "user_pg", [
            {"date": date(2026, 4, 1), "amount": 200.0, "category": "Alimentari"},
            {"date": date(2026, 4, 1), "amount": 50.0,  "category": "Cinema"},
        ])

        compute_category_averages("user_pg", db_session, store)

        alimentari = db_session.query(UserCategory).filter_by(user_id="user_pg", name="Alimentari").first()
        cinema = db_session.query(UserCategory).filter_by(user_id="user_pg", name="Cinema").first()
        assert alimentari.average == pytest.approx(200.0)
        assert cinema.average == pytest.approx(50.0)

    def test_category_filter_updates_only_target(self, db_session, store):
        self._seed_user_categories(db_session, "user_pg", ["Salute", "Farmacia"])
        self._add_expenses(db_session, "user_pg", [
            {"date": date(2026, 4, 1), "amount": 100.0, "category": "Salute"},
            {"date": date(2026, 4, 2), "amount": 80.0,  "category": "Farmacia"},
        ])
        compute_category_averages("user_pg", db_session, store)

        # Aggiunge nuova spesa solo su Salute
        self._add_expenses(db_session, "user_pg", [
            {"date": date(2026, 4, 10), "amount": 100.0, "category": "Salute"},
        ])
        compute_category_averages("user_pg", db_session, store, category_filter="Salute")

        db_session.expire_all()
        salute = db_session.query(UserCategory).filter_by(user_id="user_pg", name="Salute").first()
        farmacia = db_session.query(UserCategory).filter_by(user_id="user_pg", name="Farmacia").first()

        assert salute.average == pytest.approx(200.0)   # 100+100 / 1 mese
        assert farmacia.average == pytest.approx(80.0)  # invariata

    def test_does_not_touch_other_users(self, db_session, store):
        db_session.add(User(chat_id="user_other", is_active=True, storage_backend="postgres"))
        db_session.add(Expense(
            user_id="user_other", expense_date=date(2026, 4, 1),
            amount=500.0, name="X", category_name="Tecnologia", account_id="acc_x",
        ))
        db_session.commit()

        compute_category_averages("user_pg", db_session, store)

        other_cats = db_session.query(UserCategory).filter_by(user_id="user_other").all()
        assert len(other_cats) == 0


# ---------------------------------------------------------------------------
# 3. Notion path — sync_categories_to_local
# ---------------------------------------------------------------------------

def _make_notion_page(page_id: str, name: str, average: float) -> dict:
    return {
        "id": page_id,
        "properties": {
            "Nome": {"type": "title", "title": [{"plain_text": name}]},
            "average": {"type": "number", "number": average},
        },
    }


def _notion_client_mock(pages: list, has_more: bool = False) -> Mock:
    client = Mock()
    client.categories_db_id = "db_test"
    client._get_data_source_id.return_value = "ds_test"
    client._query_with_retry.return_value = {
        "results": pages,
        "has_more": has_more,
        "next_cursor": None,
    }
    return client


class TestSyncCategoriesToLocal:
    def test_basic_sync(self, db_session, store):
        pages = [
            _make_notion_page("page1", "Alimentari", 120.0),
            _make_notion_page("page2", "Trasporti", 55.5),
        ]
        client = _notion_client_mock(pages)

        n = sync_categories_to_local(client, "user_nt", store)

        assert n == 2
        names = store.get_user_category_names("user_nt")
        assert set(names) == {"Alimentari", "Trasporti"}

    def test_notion_page_id_saved(self, db_session, store):
        pages = [_make_notion_page("page_abc", "Salute", 30.0)]
        client = _notion_client_mock(pages)

        sync_categories_to_local(client, "user_nt", store)

        pid = store.get_notion_page_id_for_category("user_nt", "Salute")
        assert pid == "page_abc"

    def test_average_saved_correctly(self, db_session, store):
        pages = [_make_notion_page("p1", "Cinema", 42.75)]
        client = _notion_client_mock(pages)

        sync_categories_to_local(client, "user_nt", store)

        row = db_session.query(UserCategory).filter_by(user_id="user_nt", name="Cinema").first()
        assert row.average == pytest.approx(42.75)

    def test_formula_type_average(self, db_session, store):
        """Verifica che anche il tipo 'formula' per average venga letto."""
        page = {
            "id": "p_formula",
            "properties": {
                "Nome": {"type": "title", "title": [{"plain_text": "Gaming"}]},
                "average": {"type": "formula", "formula": {"type": "number", "number": 88.0}},
            },
        }
        client = _notion_client_mock([page])

        sync_categories_to_local(client, "user_nt", store)

        row = db_session.query(UserCategory).filter_by(user_id="user_nt", name="Gaming").first()
        assert row.average == pytest.approx(88.0)

    def test_skips_sconosciuta_entries(self, db_session, store):
        """Pagine senza titolo non devono essere inserite."""
        page = {
            "id": "p_empty",
            "properties": {
                "Nome": {"type": "title", "title": []},  # titolo vuoto
                "average": {"type": "number", "number": 0.0},
            },
        }
        client = _notion_client_mock([page])

        n = sync_categories_to_local(client, "user_nt", store)

        assert n == 0

    def test_no_categories_db_id_returns_zero(self, db_session, store):
        client = Mock()
        client.categories_db_id = None

        n = sync_categories_to_local(client, "user_nt", store)

        assert n == 0

    def test_api_error_returns_zero(self, db_session, store):
        client = Mock()
        client.categories_db_id = "db_test"
        client._get_data_source_id.side_effect = RuntimeError("timeout")

        n = sync_categories_to_local(client, "user_nt", store)

        assert n == 0

    def test_pagination_fetches_all_pages(self, db_session, store):
        """Verifica che has_more=True faccia iterare sulla seconda pagina."""
        page_1 = _make_notion_page("p1", "Alimentari", 100.0)
        page_2 = _make_notion_page("p2", "Sport", 40.0)

        client = Mock()
        client.categories_db_id = "db_test"
        client._get_data_source_id.return_value = "ds_test"
        client._query_with_retry.side_effect = [
            {"results": [page_1], "has_more": True, "next_cursor": "cur_1"},
            {"results": [page_2], "has_more": False, "next_cursor": None},
        ]

        n = sync_categories_to_local(client, "user_nt", store)

        assert n == 2
        assert set(store.get_user_category_names("user_nt")) == {"Alimentari", "Sport"}


# ---------------------------------------------------------------------------
# 4. Router — refresh_category_averages
# ---------------------------------------------------------------------------

class TestRefreshCategoryAverages:
    def test_notion_user_routes_to_sync(self, store):
        user = Mock(storage_backend="notion")
        store.get_user = Mock(return_value=user)
        notion_client = Mock()

        with patch("src.category_sync.sync_categories_to_local") as mock_sync:
            refresh_category_averages("user_nt", store, notion_client=notion_client)
            mock_sync.assert_called_once_with(notion_client, "user_nt", store)

    def test_postgres_user_routes_to_compute(self, store):
        user = Mock(storage_backend="postgres")
        store.get_user = Mock(return_value=user)
        session = Mock()

        with patch("src.category_sync.compute_category_averages") as mock_compute:
            refresh_category_averages("user_pg", store, session=session)
            mock_compute.assert_called_once_with("user_pg", session, store)

    def test_notion_user_without_client_logs_warning(self, store, caplog):
        import logging
        user = Mock(storage_backend="notion")
        store.get_user = Mock(return_value=user)

        with caplog.at_level(logging.WARNING, logger="financial_agent.category_sync"):
            refresh_category_averages("user_nt", store, notion_client=None)

        assert any("notion_client" in r.message for r in caplog.records)

    def test_postgres_user_without_session_logs_warning(self, store, caplog):
        import logging
        user = Mock(storage_backend="postgres")
        store.get_user = Mock(return_value=user)

        with caplog.at_level(logging.WARNING, logger="financial_agent.category_sync"):
            refresh_category_averages("user_pg", store, session=None)

        assert any("session" in r.message for r in caplog.records)

    def test_unknown_user_logs_warning(self, store, caplog):
        import logging
        store.get_user = Mock(return_value=None)

        with caplog.at_level(logging.WARNING, logger="financial_agent.category_sync"):
            refresh_category_averages("ghost_user", store)

        assert any("ghost_user" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 5. Upsert idempotenza
# ---------------------------------------------------------------------------

class TestUpsertIdempotenza:
    def test_upsert_insert_then_update(self, db_session, store):
        cats = [{"name": "Alimentari", "average": 100.0, "notion_page_id": "p1"}]
        store.upsert_user_categories("user_nt", cats)

        rows = db_session.query(UserCategory).filter_by(user_id="user_nt").all()
        assert len(rows) == 1
        assert rows[0].average == 100.0

        # Secondo upsert con average aggiornato
        cats[0]["average"] = 150.0
        store.upsert_user_categories("user_nt", cats)

        db_session.expire_all()
        rows = db_session.query(UserCategory).filter_by(user_id="user_nt").all()
        assert len(rows) == 1, "upsert non deve creare duplicati"
        assert rows[0].average == pytest.approx(150.0)

    def test_upsert_multiple_categories_no_duplicates(self, db_session, store):
        cats = [
            {"name": "Alimentari", "average": 100.0},
            {"name": "Trasporti", "average": 60.0},
        ]
        store.upsert_user_categories("user_nt", cats)
        store.upsert_user_categories("user_nt", cats)  # seconda chiamata identica

        rows = db_session.query(UserCategory).filter_by(user_id="user_nt").all()
        assert len(rows) == 2


# ---------------------------------------------------------------------------
# 6. Lookup helpers
# ---------------------------------------------------------------------------

class TestLookupHelpers:
    def _seed(self, store, user_id):
        store.upsert_user_categories(user_id, [
            {"name": "Salute", "average": 80.0, "notion_page_id": "page_salute"},
            {"name": "Farmacia", "average": 25.0, "notion_page_id": "page_farmacia"},
        ])

    def test_get_notion_page_id_exact_match(self, db_session, store):
        self._seed(store, "user_nt")
        pid = store.get_notion_page_id_for_category("user_nt", "Salute")
        assert pid == "page_salute"

    def test_get_notion_page_id_case_insensitive(self, db_session, store):
        self._seed(store, "user_nt")
        pid = store.get_notion_page_id_for_category("user_nt", "salute")
        assert pid == "page_salute"

    def test_get_notion_page_id_partial_match(self, db_session, store):
        self._seed(store, "user_nt")
        pid = store.get_notion_page_id_for_category("user_nt", "Farm")
        assert pid == "page_farmacia"

    def test_get_notion_page_id_not_found_returns_none(self, db_session, store):
        self._seed(store, "user_nt")
        pid = store.get_notion_page_id_for_category("user_nt", "Categoria Inesistente")
        assert pid is None

    def test_get_category_by_notion_page_id_found(self, db_session, store):
        self._seed(store, "user_nt")
        result = store.get_category_by_notion_page_id("user_nt", "page_salute")
        assert result["name"] == "Salute"
        assert result["average"] == pytest.approx(80.0)

    def test_get_category_by_notion_page_id_not_found_returns_fallback(self, db_session, store):
        result = store.get_category_by_notion_page_id("user_nt", "page_inesistente")
        assert result["name"] == "Sconosciuta"
        assert result["average"] == 0.0
