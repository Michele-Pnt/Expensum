"""Require ownership of the referenced category in the Notion outbox.

Revision ID: f0e1d2c3b4a5
Revises: e0f1a2b3c4d5
Create Date: 2026-09-04
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f0e1d2c3b4a5"
down_revision: Union[str, Sequence[str], None] = "e0f1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "income_category_notion_sync_tasks"
_POLICY = "tenant_isolation"


def _policy_sql() -> str:
    """Return the policy shared by fresh installs and upgrades."""
    return (
        f"CREATE POLICY {_POLICY} ON {_TABLE} "
        "USING (user_id = current_setting('app.user_id', true) "
        "AND EXISTS (SELECT 1 FROM user_income_categories c "
        "WHERE c.id = category_id AND c.user_id = current_setting('app.user_id', true))) "
        "WITH CHECK (user_id = current_setting('app.user_id', true) "
        "AND EXISTS (SELECT 1 FROM user_income_categories c "
        "WHERE c.id = category_id AND c.user_id = current_setting('app.user_id', true)))"
    )


def upgrade() -> None:
    """Replace the original outbox policy with category ownership enforcement."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DROP POLICY IF EXISTS {_POLICY} ON {_TABLE}")
    op.execute(_policy_sql())


def downgrade() -> None:
    """Restore the original user-id-only policy for a deliberate downgrade."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DROP POLICY IF EXISTS {_POLICY} ON {_TABLE}")
    op.execute(
        f"CREATE POLICY {_POLICY} ON {_TABLE} "
        "USING (user_id = current_setting('app.user_id', true)) "
        "WITH CHECK (user_id = current_setting('app.user_id', true))"
    )
