"""Aggiunge la tabella category_candidates per la categorizzazione adattiva.

Revision ID: s1t2u3v4w5x6
Revises: r9s0t1u2v3w4
Create Date: 2026-07-21 00:00:00.000000

Traccia i pattern di spesa ricorrenti non ancora promossi a categoria reale
(vedi src/category_matcher.py). Tabella nuova, nessun dato legacy da migrare.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "s1t2u3v4w5x6"
down_revision: Union[str, Sequence[str], None] = "r9s0t1u2v3w4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "category_candidates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("normalized_name", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("fallback_category_id", sa.Integer(), nullable=True),
        sa.Column("occurrences", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_score", sa.Numeric(4, 3), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("promoted_category_id", sa.Integer(), nullable=True),
        sa.Column("promoted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.chat_id"]),
        sa.ForeignKeyConstraint(["fallback_category_id"], ["user_categories.id"]),
        sa.ForeignKeyConstraint(["promoted_category_id"], ["user_categories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "normalized_name", name="uq_category_candidates_user_normalized"),
    )
    op.create_index("ix_category_candidates_user_id", "category_candidates", ["user_id"])
    op.create_index("ix_category_candidates_status", "category_candidates", ["status"])


def downgrade() -> None:
    op.drop_index("ix_category_candidates_status", "category_candidates")
    op.drop_index("ix_category_candidates_user_id", "category_candidates")
    op.drop_table("category_candidates")
