"""Aggiunge le bozze di simulazione mutuo con isolamento RLS per utente.

Revision ID: d2e3f4a5b6c7
Revises: b8c9d0e1f2a3
Create Date: 2026-08-20 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mortgage_simulations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("result_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.chat_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mortgage_simulations_user_id", "mortgage_simulations", ["user_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE mortgage_simulations ENABLE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY tenant_isolation ON mortgage_simulations
                USING (user_id = current_setting('app.user_id', true))
                WITH CHECK (user_id = current_setting('app.user_id', true))
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON mortgage_simulations")
        op.execute("ALTER TABLE mortgage_simulations DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_mortgage_simulations_user_id", "mortgage_simulations")
    op.drop_table("mortgage_simulations")
