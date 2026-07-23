"""Aggiunge la tabella user_streaks per il reward Pro della streak giornaliera.

Traccia, per utente, lo stato della streak "≥2 transazioni/giorno" organizzata
in cicli sequenziali a target crescente (14 → 28 → 42gg...), separati da una
pausa che coincide col reward Pro concesso al completamento di ogni ciclo
(cycle_state='reward_active' fino a reward_active_until). Tabella per-utente
(FK su users), senza RLS: non contiene dati finanziari, solo metadati di
gamification (nessun importo/categoria/merchant).

Revision ID: f7g8h9i0j1k2
Revises: e45ace44cf53
Create Date: 2026-07-23 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f7g8h9i0j1k2"
down_revision: Union[str, Sequence[str], None] = "e45ace44cf53"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_streaks",
        sa.Column("chat_id", sa.String(), nullable=False),
        sa.Column("current_streak_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("streak_target_days", sa.Integer(), nullable=False, server_default="14"),
        sa.Column("cycle_state", sa.String(), nullable=False, server_default="counting"),
        sa.Column("reward_active_until", sa.DateTime(), nullable=True),
        sa.Column("last_qualifying_date", sa.Date(), nullable=True),
        sa.Column("today_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("today_date", sa.Date(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["users.chat_id"]),
        sa.PrimaryKeyConstraint("chat_id"),
    )


def downgrade() -> None:
    op.drop_table("user_streaks")
