"""Aggiunge description e description_summary alla tabella user_categories.

Revision ID: d1e2f3a4b5c6
Revises: c9d0e1f2a3b4
Create Date: 2026-07-28 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_categories", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("user_categories", sa.Column("description_summary", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_categories", "description_summary")
    op.drop_column("user_categories", "description")
