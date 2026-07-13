"""Aggiunge la tabella transfers per gli spostamenti di denaro tra conti.

Un trasferimento è un movimento tra due conti dello stesso utente
(from_account_id -> to_account_id) che non è né una spesa né un'entrata:
non deve comparire nei report di spesa/entrata, ma deve contribuire al
saldo calcolato on-read di entrambi i conti coinvolti.

RLS abilitata sulla nuova tabella, stessa policy delle altre tabelle
finanziarie per-utente (vedi s0t1u2v3w4x5_enable_row_level_security.py).

Revision ID: u1v2w3x4y5z6
Revises: t0u1v2w3x4y5
Create Date: 2026-07-13 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "u1v2w3x4y5z6"
down_revision: Union[str, Sequence[str], None] = "t0u1v2w3x4y5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_POLICY = "tenant_isolation"


def upgrade() -> None:
    op.create_table(
        "transfers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("from_account_id", sa.Integer(), nullable=False),
        sa.Column("to_account_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("transfer_date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.chat_id"]),
        sa.ForeignKeyConstraint(["from_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["to_account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transfers_user_id", "transfers", ["user_id"])

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite/dev: nessuna RLS, il filtro applicativo WHERE user_id resta l'unica difesa.
        return

    op.execute("ALTER TABLE transfers ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {_POLICY} ON transfers
            USING (user_id = current_setting('app.user_id', true))
            WITH CHECK (user_id = current_setting('app.user_id', true))
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(f"DROP POLICY IF EXISTS {_POLICY} ON transfers")
        op.execute("ALTER TABLE transfers DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_transfers_user_id", "transfers")
    op.drop_table("transfers")
