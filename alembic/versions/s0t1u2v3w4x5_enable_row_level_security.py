"""Abilita la Row-Level Security sulle tabelle finanziarie per-utente.

Isolamento multi-tenant a livello di database: il ruolo runtime DML-only
(`expensum_app`) vede solo le righe del proprio tenant, filtrate da
`user_id = current_setting('app.user_id')`. La variabile di sessione è impostata
per-transazione da src/storage/rls.py.

Il ruolo OWNER (`expensum`, che gira le migration e le sessioni psql manuali)
bypassa la RLS by-default: usiamo ENABLE (non FORCE), così l'admin continua a
vedere tutto e le migration di backfill non si rompono. La protezione si applica
al ruolo runtime, che è quello con cui gira l'app in produzione.

Solo PostgreSQL: su SQLite (dev/test) la RLS non esiste e la migration è un no-op.

Revision ID: s0t1u2v3w4x5
Revises: r9s0t1u2v3w4
Create Date: 2026-07-11 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "s0t1u2v3w4x5"
down_revision: Union[str, Sequence[str], None] = "r9s0t1u2v3w4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tabelle con una colonna `user_id` che identifica il tenant (chat_id).
_RLS_TABLES = (
    "expenses",
    "incomes",
    "accounts",
    "user_categories",
    "subscriptions",
    "saved_reports",
)

_POLICY = "tenant_isolation"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite/dev: nessuna RLS. Le stesse garanzie sono coperte dal filtro
        # applicativo `WHERE user_id = ...` già presente nel layer storage.
        return

    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # USING → righe visibili in SELECT/UPDATE/DELETE.
        # WITH CHECK → impedisce INSERT/UPDATE di righe intestate ad altri tenant.
        # current_setting(..., true) = missing_ok: se la variabile non è impostata
        # ritorna NULL e nessuna riga passa il filtro (fail-closed).
        op.execute(
            f"""
            CREATE POLICY {_POLICY} ON {table}
                USING (user_id = current_setting('app.user_id', true))
                WITH CHECK (user_id = current_setting('app.user_id', true))
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table in _RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {_POLICY} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
