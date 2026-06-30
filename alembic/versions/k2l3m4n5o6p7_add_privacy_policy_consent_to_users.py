"""Aggiunge colonne di consenso privacy policy a users (GDPR Art. 7 accountability).

Revision ID: k2l3m4n5o6p7
Revises: j1k2l3m4n5o6
Create Date: 2026-06-30 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "k2l3m4n5o6p7"
down_revision: Union[str, Sequence[str], None] = "j1k2l3m4n5o6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("privacy_policy_version_accepted", sa.String, nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("privacy_accepted_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "privacy_accepted_at")
    op.drop_column("users", "privacy_policy_version_accepted")
