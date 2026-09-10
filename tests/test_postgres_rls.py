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
    """Crea due tenant con dati finanziari e categorie entrata (OWNER, bypassa RLS)."""
    with admin_engine.begin() as conn:
        # Pulizia idempotente
        for uid in (USER_A, USER_B):
            conn.execute(text("DELETE FROM expenses WHERE user_id = :u"), {"u": uid})
            conn.execute(text("DELETE FROM incomes WHERE user_id = :u"), {"u": uid})
        conn.execute(text(
            "DELETE FROM savings_goal_evaluations WHERE user_id IN (:a, :b)"
        ), {"a": USER_A, "b": USER_B})
        conn.execute(text("DELETE FROM savings_goals WHERE user_id IN (:a, :b)"), {
            "a": USER_A,
            "b": USER_B,
        })
        conn.execute(text(
            "DELETE FROM user_income_category_notion_links WHERE category_id IN "
            "(SELECT id FROM user_income_categories WHERE user_id IN (:a, :b))"
        ), {"a": USER_A, "b": USER_B})
        for uid in (USER_A, USER_B):
            conn.execute(text("DELETE FROM user_income_categories WHERE user_id = :u"), {"u": uid})
            conn.execute(text("DELETE FROM accounts WHERE user_id = :u"), {"u": uid})
            conn.execute(text("DELETE FROM users WHERE chat_id = :u"), {"u": uid})

        seeded: dict[str, int] = {}
        for uid in (USER_A, USER_B):
            conn.execute(
                text(
                    "INSERT INTO users "
                    "(chat_id, storage_backend, preferred_language, currency, timezone) "
                    "VALUES (:u, 'postgres', 'it', 'EUR', 'Europe/Rome')"
                ),
                {"u": uid},
            )
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
            goal_id = conn.execute(
                text(
                    "INSERT INTO savings_goals "
                    "(user_id, goal_type, name, target_amount, start_date) "
                    "VALUES (:u, 'generic', :n, 100, CURRENT_DATE) RETURNING id"
                ),
                {"u": uid, "n": f"obiettivo-{uid}"},
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO savings_goal_evaluations "
                    "(goal_id, user_id, period_month, progress_pct, score_label) "
                    "VALUES (:g, :u, date_trunc('month', CURRENT_DATE)::date, 10, 'in_pace')"
                ),
                {"g": goal_id, "u": uid},
            )
            category_id = conn.execute(
                text("INSERT INTO user_income_categories (user_id, name) "
                     "VALUES (:u, :n) RETURNING id"),
                {"u": uid, "n": f"categoria-{uid}"},
            ).scalar_one()
            conn.execute(
                text("INSERT INTO user_income_category_notion_links "
                     "(category_id, notion_page_id) VALUES (:c, :n)"),
                {"c": category_id, "n": f"notion-{uid}"},
            )
            seeded[f"account_{uid}"] = acc_id
            seeded[f"category_{uid}"] = category_id
    yield seeded
    with admin_engine.begin() as conn:
        for uid in (USER_A, USER_B):
            conn.execute(text("DELETE FROM expenses WHERE user_id = :u"), {"u": uid})
            conn.execute(text("DELETE FROM incomes WHERE user_id = :u"), {"u": uid})
        conn.execute(text(
            "DELETE FROM savings_goal_evaluations WHERE user_id IN (:a, :b)"
        ), {"a": USER_A, "b": USER_B})
        conn.execute(text("DELETE FROM savings_goals WHERE user_id IN (:a, :b)"), {
            "a": USER_A,
            "b": USER_B,
        })
        conn.execute(text(
            "DELETE FROM user_income_category_notion_links WHERE category_id IN "
            "(SELECT id FROM user_income_categories WHERE user_id IN (:a, :b))"
        ), {"a": USER_A, "b": USER_B})
        for uid in (USER_A, USER_B):
            conn.execute(text("DELETE FROM user_income_categories WHERE user_id = :u"), {"u": uid})
            conn.execute(text("DELETE FROM accounts WHERE user_id = :u"), {"u": uid})
            conn.execute(text("DELETE FROM users WHERE chat_id = :u"), {"u": uid})


@pyt_skip
def test_income_category_rls_schema_is_ready(admin_engine):
    """Le tabelle categorie/link e la RLS devono esistere dopo c0/c1."""
    with admin_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT relname, relrowsecurity FROM pg_class "
            "WHERE oid IN (to_regclass('user_income_categories'), "
            "to_regclass('user_income_category_notion_links'))"
        )).all()

    assert dict(rows) == {
        "user_income_categories": True,
        "user_income_category_notion_links": True,
    }


@pyt_skip
def test_income_category_sync_outbox_uses_rls(admin_engine):
    """The durable Notion reconciliation outbox is tenant-isolated as well."""
    with admin_engine.connect() as conn:
        enabled = conn.execute(text(
            "SELECT relrowsecurity FROM pg_class "
            "WHERE oid = to_regclass('income_category_notion_sync_tasks')"
        )).scalar_one()
        columns = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'income_category_notion_sync_tasks'"
        )).scalars().all()

    assert enabled is True
    assert "page_ids" in columns


@pyt_skip
def test_income_category_outbox_with_check_blocks_other_tenant_category(
    app_sessionmaker, seed_two_tenants,
):
    """Tenant A cannot queue a task targeting a category owned by tenant B."""
    from sqlalchemy.exc import DBAPIError, ProgrammingError
    from src.storage import rls

    session = app_sessionmaker()
    rls.bind_user(session, USER_A)
    try:
        with pytest.raises((DBAPIError, ProgrammingError)):
            session.execute(
                text(
                    "INSERT INTO income_category_notion_sync_tasks "
                    "(user_id, category_id, operation, previous_name, next_name, created_at) "
                    "VALUES (:u, :c, 'rename', 'prima', 'dopo', CURRENT_TIMESTAMP)"
                ),
                {"u": USER_A, "c": seed_two_tenants[f"category_{USER_B}"]},
            )
            session.flush()
    finally:
        session.rollback()
        session.close()


@pyt_skip
def test_savings_goals_rls_schema_is_ready(admin_engine):
    """Le tabelle degli obiettivi devono applicare RLS anche su uno schema nuovo."""
    with admin_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT relname, relrowsecurity FROM pg_class "
            "WHERE oid IN (to_regclass('savings_goals'), "
            "to_regclass('savings_goal_evaluations'))"
        )).all()

    assert dict(rows) == {
        "savings_goals": True,
        "savings_goal_evaluations": True,
    }


@pyt_skip
def test_rls_suite_uses_the_expensum_app_runtime_role(app_sessionmaker):
    """Il test RLS deve girare con il ruolo runtime, non con l'owner che la bypassa."""
    session = app_sessionmaker()
    try:
        current_user = session.execute(text("SELECT current_user")).scalar_one()
    finally:
        session.close()

    assert current_user == "expensum_app"


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
def test_savings_goal_rls_hides_other_tenant_rows(app_sessionmaker, seed_two_tenants):
    """Il tenant A non vede obiettivi né valutazioni di B senza un filtro applicativo."""
    from src.storage import rls

    session = app_sessionmaker()
    rls.bind_user(session, USER_A)
    try:
        goals = session.execute(text("SELECT user_id FROM savings_goals")).scalars().all()
        evaluations = session.execute(
            text("SELECT user_id FROM savings_goal_evaluations")
        ).scalars().all()
    finally:
        session.close()

    assert set(goals) == {USER_A}
    assert set(evaluations) == {USER_A}


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


@pyt_skip
def test_income_category_rls_hides_other_tenant_categories(app_sessionmaker, seed_two_tenants):
    """Il tenant A vede soltanto il proprio catalogo categorie entrata senza WHERE."""
    from src.storage import rls

    session = app_sessionmaker()
    rls.bind_user(session, USER_A)
    try:
        rows = session.execute(text("SELECT user_id FROM user_income_categories")).scalars().all()
    finally:
        session.close()

    assert set(rows) == {USER_A}


@pyt_skip
def test_income_category_link_rls_hides_other_tenant_links(app_sessionmaker, seed_two_tenants):
    """Il tenant A vede solo il link Notion della categoria di cui è proprietario."""
    from src.storage import rls

    session = app_sessionmaker()
    rls.bind_user(session, USER_A)
    try:
        rows = session.execute(
            text("SELECT category_id FROM user_income_category_notion_links")
        ).scalars().all()
    finally:
        session.close()

    assert rows == [seed_two_tenants[f"category_{USER_A}"]]


@pyt_skip
def test_income_category_with_check_blocks_cross_tenant_insert(app_sessionmaker, seed_two_tenants):
    """Il ruolo app non può creare nel catalogo di B mentre è associato al tenant A."""
    from sqlalchemy.exc import DBAPIError, ProgrammingError
    from src.storage import rls

    session = app_sessionmaker()
    rls.bind_user(session, USER_A)
    try:
        with pytest.raises((DBAPIError, ProgrammingError)):
            session.execute(
                text("INSERT INTO user_income_categories (user_id, name) "
                     "VALUES (:u, 'intruso')"),
                {"u": USER_B},
            )
            session.flush()
    finally:
        session.rollback()
        session.close()


@pyt_skip
def test_income_category_delete_runs_under_rls_for_the_bound_tenant(
    app_sessionmaker, seed_two_tenants
):
    """La cancellazione reale non deve richiedere privilegi OWNER né toccare B."""
    from src.storage import rls
    from src.storage.postgres_storage import PostgresStorage

    category_id = seed_two_tenants[f"category_{USER_A}"]
    session = app_sessionmaker()
    rls.bind_user(session, USER_A)
    try:
        result = PostgresStorage(session, USER_A).delete_income_category(category_id)
        remaining = session.execute(
            text("SELECT name FROM user_income_categories ORDER BY name")
        ).scalars().all()
    finally:
        session.close()

    assert result == {"incomes": 0}
    assert "Altra entrata" in remaining
    assert f"categoria-{USER_A}" not in remaining


@pyt_skip
def test_income_category_link_with_check_blocks_other_tenant_parent(
    app_sessionmaker, seed_two_tenants
):
    """Il tenant A non può collegare una categoria di B alla cache Notion."""
    from sqlalchemy.exc import DBAPIError, ProgrammingError
    from src.storage import rls

    session = app_sessionmaker()
    rls.bind_user(session, USER_A)
    try:
        with pytest.raises((DBAPIError, ProgrammingError)):
            session.execute(
                text("INSERT INTO user_income_category_notion_links (category_id, notion_page_id) "
                     "VALUES (:c, 'intruso-link')"),
                {"c": seed_two_tenants[f"category_{USER_B}"]},
            )
            session.flush()
    finally:
        session.rollback()
        session.close()


@pyt_skip
def test_income_with_check_blocks_cross_tenant_income_category(
    app_sessionmaker, seed_two_tenants
):
    """Il tenant A non può assegnare un'entrata alla categoria appartenente a B."""
    from sqlalchemy.exc import DBAPIError, ProgrammingError
    from src.storage import rls

    session = app_sessionmaker()
    rls.bind_user(session, USER_A)
    try:
        with pytest.raises((DBAPIError, ProgrammingError)):
            session.execute(
                text("INSERT INTO incomes "
                     "(user_id, income_date, amount, name, account_id, income_category_id) "
                     "VALUES (:u, CURRENT_DATE, 5, 'intruso', :a, :c)"),
                {
                    "u": USER_A,
                    "a": seed_two_tenants[f"account_{USER_A}"],
                    "c": seed_two_tenants[f"category_{USER_B}"],
                },
            )
            session.flush()
    finally:
        session.rollback()
        session.close()
