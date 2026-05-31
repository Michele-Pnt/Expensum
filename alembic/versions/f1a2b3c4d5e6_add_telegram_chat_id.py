"""add_telegram_chat_id

Revision ID: f1a2b3c4d5e6
Revises: e5f6a7b8c9d0
Create Date: 2026-05-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Aggiunge telegram_chat_id come campo separato dalla PK.

    Permette agli utenti web (chat_id='web_xxx') di collegare il proprio
    account Telegram senza migrare la PK. Per gli utenti già registrati
    via Telegram il campo viene popolato con il loro chat_id.
    """
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('telegram_chat_id', sa.String(), nullable=True))
        batch_op.create_unique_constraint('uq_users_telegram_chat_id', ['telegram_chat_id'])

    # Backfill: per gli utenti Telegram esistenti telegram_chat_id = chat_id
    op.execute("UPDATE users SET telegram_chat_id = chat_id WHERE chat_id NOT LIKE 'web_%'")


def downgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_constraint('uq_users_telegram_chat_id', type_='unique')
        batch_op.drop_column('telegram_chat_id')
