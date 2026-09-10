"""Aggiunge emergency_fund_months a savings_goals per il nuovo tipo emergency_fund.

Revision ID: b29df51a6e74
Revises: a17ce34f3d63
Create Date: 2026-08-27
"""
from alembic import op
import sqlalchemy as sa

revision = "b29df51a6e74"
down_revision = "a17ce34f3d63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("savings_goals", sa.Column("emergency_fund_months", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("savings_goals", "emergency_fund_months")
