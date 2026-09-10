"""Persist the Notion page snapshot for income-category reconciliation.

Revision ID: a4b5c6d7e8f9
Revises: f0e1d2c3b4a5
Create Date: 2026-09-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, Sequence[str], None] = "f0e1d2c3b4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the nullable, backend-portable page id snapshot."""
    op.add_column(
        "income_category_notion_sync_tasks",
        sa.Column("page_ids", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """Remove the stored Notion page id snapshot."""
    op.drop_column("income_category_notion_sync_tasks", "page_ids")
