"""Aggiunge campi trial a user_plans e tabella trial_lifecycle_events.

Revision ID: q8r9s0t1u2v3
Revises: p7q8r9s0t1u2
Create Date: 2026-07-08 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "q8r9s0t1u2v3"
down_revision: Union[str, Sequence[str], None] = "p7q8r9s0t1u2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_plans",
        sa.Column("is_trial", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "user_plans",
        sa.Column("trial_started_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "user_plans",
        sa.Column("trial_ends_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "trial_lifecycle_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.String(), sa.ForeignKey("users.chat_id"), nullable=False),
        sa.Column("step", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="sent"),
        sa.UniqueConstraint("chat_id", "step", "channel", name="uq_trial_lifecycle_chat_step_channel"),
    )


def downgrade() -> None:
    op.drop_table("trial_lifecycle_events")
    op.drop_column("user_plans", "trial_ends_at")
    op.drop_column("user_plans", "trial_started_at")
    op.drop_column("user_plans", "is_trial")
