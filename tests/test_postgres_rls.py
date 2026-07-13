"""
Tier di test Postgres (marker `pg`) — valida contro il DB locale 1:1 tre cose che
SQLite non può coprire:

  1. RLS positiva  — un tenant vede solo le proprie righe tramite il layer storage.
  2. RLS negativa  — una query SENZA `WHERE user_id` dal ruolo app vede comunque
                     solo il proprio tenant: prova che l'isolamento è imposto dal
                     DATABASE (RLS), non solo dal filtro applicativo. È lo scenario
                     "SQL injection / filtro dimenticato".
  3. WITH CHECK    — il ruolo app non può inserire righe intestate ad altri tenant.

Prerequisiti:
    ./scripts/dev_db.sh up
    ./scripts/dev_db.sh migrate
    export $(grep -v '^#' .env.local | xargs)   # o: set -a && source .env.local && set +a

Esecuzione:  pytest -m pg
Se il container non è attivo o le env var mancano, i test vengono skippati.
"""
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.pg

APP_URL = os.getenv("TEST_DATABASE_URL")
ADMIN_URL = os.getenv("TEST_DATABASE_URL_ADMIN")

USER_A = "rls_test_user_A"
USER_B = "rls_test_user_B"


def _reachable(url: str) -> bool:
    if not url:
        return False
    try:
        eng = create_engine(url)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        eng.dispose()
        return True
    except Exception:
        return False


pyt_skip = pytest.mark.skipif(
    not (_reachable(ADMIN_URL) and _reachable(APP_URL)),
    reason="Postgres locale non raggiungibile: avvia ./scripts/dev_db.sh up && migrate e carica .env.local",
)


@pytest.fixture(scope="module")
def admin_engine():
    """Engine col ruolo OWNER: bypassa la RLS, usato per il setup/teardown dei dati."""
    eng = create_engine(ADMIN_URL, future=True)
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def app_sessionmaker():
    """Sessionmaker col ruolo runtime DML-only: soggetto a RLS, come in produzione."""
    eng = create_engine(APP_URL, future=True)
    # L'import registra il listener RLS (after_begin → set_config app.user_id).
    import src.storage.rls  # noqa: F401
    yield sessionmaker(bind=eng, expire_on_commit=False)
    eng.dispose()


@pytest.fixture
def seed_two_tenants(admin_engine):
    """Crea due utenti con un conto e una spesa ciascuno (come OWNER, bypassa RLS)."""
    with admin_engine.begin() as conn:
        # Pulizia idempotente
        for uid in (USER_A, USER_B):
            conn.execute(text("DELETE FROM expenses WHERE user_id = :u"), {"u": uid})
            conn.execute(text("DELETE FROM accounts WHERE user_id = :u"), {"u": uid})
            conn.execute(text("DELETE FROM users WHERE chat_id = :u"), {"u": uid})
        for uid in (USER_A, USER_B):
            conn.execute(text("INSERT INTO users (chat_id) VALUES (:u)"), {"u": uid})
            acc_id = conn.execute(
                text("INSERT INTO accounts (user_id, name, opening_balance) "
                     "VALUES (:u, 'Conto', 0) RETURNING id"),
                {"u": uid},
            ).scalar()
            conn.execute(
                text("INSERT INTO expenses (user_id, expense_date, amount, name, account_id) "
                     "VALUES (:u, CURRENT_DATE, 10, :n, :a)"),
                {"u": uid, "n": f"spesa-{uid}", "a": acc_id},
            )
    yield
    with admin_engine.begin() as conn:
        for uid in (USER_A, USER_B):
            conn.execute(text("DELETE FROM expenses WHERE user_id = :u"), {"u": uid})
            conn.execute(text("DELETE FROM accounts WHERE user_id = :u"), {"u": uid})
            conn.execute(text("DELETE FROM users WHERE chat_id = :u"), {"u": uid})


@pyt_skip
def test_rls_negative_query_without_where_is_isolated(app_sessionmaker, seed_two_tenants):
    """Il test del milione: una query SENZA filtro user_id vede solo il proprio tenant."""
    from src.storage import rls

    session = app_sessionmaker()
    rls.bind_user(session, USER_A)
    try:
        # Nessun WHERE user_id: senza RLS conterebbe le righe di TUTTI i tenant.
        rows = session.execute(text("SELECT user_id FROM expenses")).scalars().all()
    finally:
        session.close()

    assert set(rows) == {USER_A}, f"RLS non isola: viste righe di altri tenant → {set(rows)}"


@pyt_skip
def test_rls_positive_storage_reads_only_own_rows(app_sessionmaker, seed_two_tenants):
    """Attraverso il layer storage, il tenant A non vede la spesa di B."""
    from src.storage.postgres_storage import PostgresStorage
    from datetime import date

    session = app_sessionmaker()
    try:
        storage = PostgresStorage(session=session, user_id=USER_A)
        txs = storage.fetch_all_transactions(date(2000, 1, 1), date(2100, 1, 1))
        names = {t["name"] for t in txs}
    finally:
        session.close()

    assert names == {f"spesa-{USER_A}"}
    assert f"spesa-{USER_B}" not in names


@pyt_skip
def test_rls_with_check_blocks_cross_tenant_insert(app_sessionmaker, seed_two_tenants):
    """Il ruolo app, loggato come A, non può inserire una riga intestata a B."""
    from sqlalchemy.exc import DBAPIError, ProgrammingError
    from src.storage import rls

    session = app_sessionmaker()
    rls.bind_user(session, USER_A)
    try:
        with pytest.raises((DBAPIError, ProgrammingError)):
            session.execute(
                text("INSERT INTO expenses (user_id, expense_date, amount, name) "
                     "VALUES (:u, CURRENT_DATE, 5, 'intruso')"),
                {"u": USER_B},
            )
            session.flush()
    finally:
        session.rollback()
        session.close()
