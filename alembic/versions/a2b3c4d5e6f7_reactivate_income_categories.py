"""Reactivate legacy income categories before enabling deletion-only lifecycle.

Income categories originally exposed an archive/restore workflow.  The product now
uses the same deletion workflow as expense categories, reassigning linked incomes
to ``Altra entrata``.  Existing archived rows must therefore be visible again
before the UI/API stop exposing archive semantics.

Revision ID: a2b3c4d5e6f7
Revises: c9d1e4b7a206
Create Date: 2026-09-03
"""
from typing import Sequence, Union

from alembic import op


revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "c9d1e4b7a206"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Make all income categories selectable under the deletion-only workflow."""
    op.execute("UPDATE user_income_categories SET archived_at = NULL WHERE archived_at IS NOT NULL")


def downgrade() -> None:
    """Archive state cannot be reconstructed after a forward data migration."""
