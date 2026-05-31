"""Aggiunge expires_at a oauth_sessions con TTL 15 minuti.

Revision ID: i0j1k2l3m4n5
Revises: h9i0j1k2l3m4
Create Date: 2026-05-24 00:02:00.000000
"""
from typing import Sequence, Union
from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision: str = "i0j1k2l3m4n5"
down_revision: Union[str, Sequence[str], None] = "h9i0j1k2l3m4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "oauth_sessions",
        sa.Column(
            "expires_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_column("oauth_sessions", "expires_at")
