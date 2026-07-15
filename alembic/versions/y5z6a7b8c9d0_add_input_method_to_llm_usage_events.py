"""Aggiunge input_method a llm_usage_events per distinguere testo/voce/foto.

Prima 'operation' era l'unico modo per dedurre la modalità di input, ma non
basta: su Telegram 'expense_parse' mescola testo e foto (l'OCR è locale via
Tesseract, non un LLM, quindi non genera una riga propria — il testo estratto
passa dalla stessa funzione del testo digitato); sul webapp 'chat_parse'
mescola tutte e tre le modalità (testo/voce/foto) senza distinzione.

Colonna nullable e NON retroattiva: le righe storiche restano NULL, non è
possibile ricostruire la modalità di input a posteriori.

Revision ID: y5z6a7b8c9d0
Revises: x4y5z6a7b8c9
Create Date: 2026-07-14 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "y5z6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "x4y5z6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("llm_usage_events", sa.Column("input_method", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_usage_events", "input_method")
