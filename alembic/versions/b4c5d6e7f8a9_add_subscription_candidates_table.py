"""Crea la tabella subscription_candidates per il rilevamento abbonamenti ricorrenti.

Mirror di category_candidates (vedi s1t2u3v4w5x6_add_category_candidates_table.py)
ma per pattern di spesa ricorrenti candidati a diventare Subscription. Popolata in
tempo reale da un hook a ogni nuova spesa (src/subscription_detector.py) e, per lo
storico esistente, dal backfill una tantum in
scripts/backfill_subscription_candidates.py (fuori dalla transazione Alembic, come
già fatto per la gamification).

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-08-03 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, Sequence[str], None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscription_candidates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.chat_id"), nullable=False),
        sa.Column("category_name", sa.String(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("cadence", sa.String(length=20), nullable=True),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_occurrence_date", sa.Date(), nullable=False),
        sa.Column("last_occurrence_date", sa.Date(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("promoted_subscription_id", sa.Integer(), sa.ForeignKey("subscriptions.id"), nullable=True),
        sa.Column("promoted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index(
        "ix_subscription_candidates_user_id", "subscription_candidates", ["user_id"]
    )
    op.create_index(
        "ix_subscription_candidates_status", "subscription_candidates", ["status"]
    )


def downgrade() -> None:
    op.drop_index("ix_subscription_candidates_status", table_name="subscription_candidates")
    op.drop_index("ix_subscription_candidates_user_id", table_name="subscription_candidates")
    op.drop_table("subscription_candidates")
