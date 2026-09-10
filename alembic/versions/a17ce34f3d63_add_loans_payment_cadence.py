"""Aggiunge payment_cadence a loans (colonna presente nel modello ma mai migrata).

Revision ID: a17ce34f3d63
Revises: e3f4a5b6c7d8
Create Date: 2026-08-27
"""
from alembic import op
import sqlalchemy as sa

revision = "a17ce34f3d63"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("loans", sa.Column("payment_cadence", sa.String(length=20), nullable=False, server_default="monthly"))


def downgrade() -> None:
    op.drop_column("loans", "payment_cadence")
