"""Abilita RLS per gli obiettivi di risparmio esistenti.

Le tabelle ``savings_goals`` e ``savings_goal_evaluations`` sono state create dopo
la migration RLS originaria. Una migration successiva ne documentava il retrofit,
ma non le aveva incluse nell'elenco effettivamente applicato. Questa migration
forward-only chiude il gap anche per database nuovi e ripristina in modo idempotente
la policy standard per-tenant su installazioni gia' esistenti.

Revision ID: f9e8d7c6b5a4
Revises: f8e7e7a858b3
Create Date: 2026-09-03
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f9e8d7c6b5a4"
down_revision: Union[str, Sequence[str], None] = "f8e7e7a858b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_POLICY = "tenant_isolation"
_TABLES = ("savings_goals", "savings_goal_evaluations")


def upgrade() -> None:
    """Applica la policy RLS per utente alle tabelle degli obiettivi."""
    if op.get_bind().dialect.name != "postgresql":
        return

    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {_POLICY} ON {table}")
        op.execute(
            f"""
            CREATE POLICY {_POLICY} ON {table}
                USING (user_id = current_setting('app.user_id', true))
                WITH CHECK (user_id = current_setting('app.user_id', true))
            """
        )


def downgrade() -> None:
    """Rimuove la policy introdotta con questa migration."""
    if op.get_bind().dialect.name != "postgresql":
        return

    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS {_POLICY} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
