"""Aggiunge tabella tally_leads (backup locale submit form waitlist beta).

Revision ID: o6p7q8r9s0t1
Revises: n5o6p7q8r9s0
Create Date: 2026-07-06 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "o6p7q8r9s0t1"
down_revision: Union[str, Sequence[str], None] = "n5o6p7q8r9s0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tally_leads",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tally_submission_id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("raw_payload", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.Column("synced_to_brevo", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_tally_leads_tally_submission_id",
        "tally_leads",
        ["tally_submission_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_tally_leads_tally_submission_id", table_name="tally_leads")
    op.drop_table("tally_leads")
