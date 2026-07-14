"""Aggiunge il tracking server-side del tour guidato webapp su users.

Prima lo stato del tour (10 step demo, frontend/src/context/TourContext.tsx)
viveva solo in localStorage del browser: nessuna persistenza server, quindi la
dashboard admin non poteva sapere chi salta il tour o a quale step si ferma.

Gli eventi arrivano da POST /api/track (tour_started/tour_step_viewed/
tour_skipped/tour_completed), solo quando l'utente ha una sessione autenticata
valida (niente scritture per visitatori anonimi).

Revision ID: x4y5z6a7b8c9
Revises: w3x4y5z6a7b8
Create Date: 2026-07-14 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "x4y5z6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "w3x4y5z6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("tour_step", sa.String(), nullable=True))
    op.add_column("users", sa.Column("tour_status", sa.String(), nullable=True))
    op.add_column("users", sa.Column("tour_completed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "tour_completed_at")
    op.drop_column("users", "tour_status")
    op.drop_column("users", "tour_step")
