"""Aggiunge le tabelle savings_goals e savings_goal_evaluations.

Revision ID: c9d0e1f2a3b4
Revises: b9c0d1e2f3a4
Create Date: 2026-07-27 00:00:00.000000

Feature "Obiettivi di risparmio" (Pro, solo backend PostgreSQL). `savings_goals`
tiene la definizione dell'obiettivo (vedi src/storage/models.py::SavingsGoal per
i 5 tipi supportati); `savings_goal_evaluations` storicizza solo il voto mensile
e l'ETA calcolati dal job schedulato (src/savings_goals_service.py) — il valore
"adesso" resta sempre calcolato on-read, non c'è nulla da migrare da dati legacy.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "savings_goals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("goal_type", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("target_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("current_snapshot", sa.Numeric(12, 2), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("last_evaluated_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.chat_id"]),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["user_categories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("target_amount > 0", name="ck_savings_goals_target_positive"),
    )
    op.create_index("ix_savings_goals_user_id", "savings_goals", ["user_id"])
    op.create_index("ix_savings_goals_user_status", "savings_goals", ["user_id", "status"])

    op.create_table(
        "savings_goal_evaluations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("goal_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("progress_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("score_label", sa.String(length=20), nullable=False),
        sa.Column("eta_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["goal_id"], ["savings_goals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.chat_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("goal_id", "period_month", name="uq_savings_goal_evaluations_goal_period"),
    )
    op.create_index("ix_savings_goal_evaluations_goal_id", "savings_goal_evaluations", ["goal_id"])
    op.create_index("ix_savings_goal_evaluations_user_id", "savings_goal_evaluations", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_savings_goal_evaluations_user_id", "savings_goal_evaluations")
    op.drop_index("ix_savings_goal_evaluations_goal_id", "savings_goal_evaluations")
    op.drop_table("savings_goal_evaluations")
    op.drop_index("ix_savings_goals_user_status", "savings_goals")
    op.drop_index("ix_savings_goals_user_id", "savings_goals")
    op.drop_table("savings_goals")
