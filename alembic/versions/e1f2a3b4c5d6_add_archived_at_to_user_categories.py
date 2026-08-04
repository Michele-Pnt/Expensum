"""Aggiunge archived_at e budget_suggestion_dismissed_at a user_categories.

`archived_at` è l'alternativa non distruttiva alla cancellazione di una categoria:
le foreign key da expenses/subscriptions/savings_goals sono RESTRICT, quindi finora
cancellare una categoria con anche una sola spesa collegata falliva. Archiviandola,
la categoria sparisce dalle scelte future (parser LLM, menù, obiettivi, suggerimenti
budget) ma lo storico resta intatto e i report già emessi non cambiano.

`budget_suggestion_dismissed_at` rende persistente il rifiuto di un suggerimento di
budget, che prima viveva solo nello stato React e ricompariva a ogni reload.

Nessun backfill: NULL significa "attiva" e "mai rifiutato", cioè il comportamento
odierno per tutte le righe esistenti.

Revision ID: e1f2a3b4c5d6
Revises: d1e2f3a4b5c6
Create Date: 2026-08-02 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_categories", sa.Column("archived_at", sa.DateTime(), nullable=True))
    op.add_column(
        "user_categories",
        sa.Column("budget_suggestion_dismissed_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_categories", "budget_suggestion_dismissed_at")
    op.drop_column("user_categories", "archived_at")
