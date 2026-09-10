"""Persist retries for Notion income-category reconciliation.

Revision ID: e0f1a2b3c4d5
Revises: a2b3c4d5e6f7
Create Date: 2026-09-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e0f1a2b3c4d5"
down_revision: Union[str, Sequence[str], None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_POLICY = "tenant_isolation"


def upgrade() -> None:
    """Create the tenant-scoped outbox used by the Notion storage adapter."""
    op.create_table(
        "income_category_notion_sync_tasks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.chat_id"), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("user_income_categories.id"), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("previous_name", sa.String(), nullable=False),
        sa.Column("next_name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("category_id", name="uq_income_category_notion_sync_task_category"),
    )
    op.create_index(
        "ix_income_category_notion_sync_tasks_user_id",
        "income_category_notion_sync_tasks", ["user_id"],
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE income_category_notion_sync_tasks ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {_POLICY} ON income_category_notion_sync_tasks "
        "USING (user_id = current_setting('app.user_id', true) "
        "AND EXISTS (SELECT 1 FROM user_income_categories c "
        "WHERE c.id = category_id AND c.user_id = current_setting('app.user_id', true))) "
        "WITH CHECK (user_id = current_setting('app.user_id', true) "
        "AND EXISTS (SELECT 1 FROM user_income_categories c "
        "WHERE c.id = category_id AND c.user_id = current_setting('app.user_id', true)))"
    )


def downgrade() -> None:
    """Remove the durable Notion reconciliation outbox."""
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP POLICY IF EXISTS {_POLICY} ON income_category_notion_sync_tasks")
        op.execute("ALTER TABLE income_category_notion_sync_tasks DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_income_category_notion_sync_tasks_user_id", table_name="income_category_notion_sync_tasks")
    op.drop_table("income_category_notion_sync_tasks")
