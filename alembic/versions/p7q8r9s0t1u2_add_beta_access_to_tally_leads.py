"""Aggiunge tracking accesso beta automatico a tally_leads.

Revision ID: p7q8r9s0t1u2
Revises: o6p7q8r9s0t1
Create Date: 2026-07-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "p7q8r9s0t1u2"
down_revision: Union[str, Sequence[str], None] = "o6p7q8r9s0t1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tally_leads",
        sa.Column("beta_account_granted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "tally_leads",
        sa.Column("beta_account_granted_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tally_leads", "beta_account_granted_at")
    op.drop_column("tally_leads", "beta_account_granted")
