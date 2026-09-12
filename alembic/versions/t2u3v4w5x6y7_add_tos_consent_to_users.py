"""Aggiunge colonne di consenso termini di servizio a users (GDPR Art. 7 accountability).

Revision ID: t2u3v4w5x6y7
Revises: c6d7e8f9a0b1
Create Date: 2026-09-11 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "t2u3v4w5x6y7"
down_revision: Union[str, Sequence[str], None] = "c6d7e8f9a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("tos_version_accepted", sa.String, nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("tos_accepted_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "tos_accepted_at")
    op.drop_column("users", "tos_version_accepted")
