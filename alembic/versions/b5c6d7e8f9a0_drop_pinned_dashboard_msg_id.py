"""Drop users.pinned_dashboard_msg_id — Telegram non pinna più una dashboard.

Il push automatico giornaliero e il refresh post-modifica sono stati rimossi:
Telegram torna a essere solo cattura + notifica con link, la lettura vive nella
webapp. La colonna serviva solo a tracciare il message_id del messaggio pinnato.

Va applicata SOLO dopo aver eseguito `scripts/unpin_daily_dashboards.py` in
produzione (unpinna i messaggi esistenti prima che l'app perda il riferimento).

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-09-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, Sequence[str], None] = "a4b5c6d7e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove the pinned-dashboard message id tracking column."""
    op.drop_column("users", "pinned_dashboard_msg_id")


def downgrade() -> None:
    """Restore the column (data not recoverable: values were message ids only)."""
    op.add_column(
        "users",
        sa.Column("pinned_dashboard_msg_id", sa.BigInteger(), nullable=True),
    )
