"""system_and_user_categories

Revision ID: b2c3d4e5f6a7
Revises: 1135fb2161e3
Create Date: 2026-04-18 00:00:00.000000

Sostituisce la tabella categories (per-user flat) con:
  - system_categories: categorie predefinite condivise, immutabili
  - user_categories:   categorie effettive per utente (Notion mirror o Postgres)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = '1135fb2161e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SYSTEM_CATEGORIES = [
    "Alimentari", "Ristoranti", "Bar/Caffè", "Trasporti", "Benzina",
    "Taxi", "Parcheggio", "Salute", "Farmacia", "Casa", "Bollette",
    "Affitto", "Intrattenimento", "Cinema", "Gaming", "Streaming",
    "Musica", "Sport", "Palestra", "Abbigliamento", "Cosmesi",
    "Tecnologia", "Viaggi", "Regali", "Istruzione", "Libri",
    "Animali", "Lavanderia", "Tabacchi", "Banca/Finanza",
    "Assicurazione", "Altro",
]


def upgrade() -> None:
    # 1. Crea system_categories
    op.create_table(
        'system_categories',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(), nullable=False, unique=True),
        sa.PrimaryKeyConstraint('id'),
    )

    # 2. Pre-carica le categorie di sistema
    sys_cat = table('system_categories', column('name', sa.String()))
    op.bulk_insert(sys_cat, [{'name': n} for n in SYSTEM_CATEGORIES])

    # 3. Crea user_categories
    op.create_table(
        'user_categories',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('average', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('notion_page_id', sa.String(), nullable=True),
        sa.Column('synced_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.chat_id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'name', name='uq_user_categories_user_name'),
    )
    op.create_index('ix_user_categories_user_id', 'user_categories', ['user_id'])

    # 4. Migra dati esistenti da categories → user_categories (se la tabella esiste)
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'categories' in inspector.get_table_names():
        bind.execute(sa.text(
            "INSERT INTO user_categories (user_id, name, average) "
            "SELECT user_id, name, 0.0 FROM categories"
        ))
        op.drop_table('categories')


def downgrade() -> None:
    op.create_table(
        'categories',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.chat_id']),
        sa.PrimaryKeyConstraint('id'),
    )
    bind = op.get_bind()
    bind.execute(sa.text(
        "INSERT INTO categories (user_id, name) "
        "SELECT user_id, name FROM user_categories"
    ))
    op.drop_index('ix_user_categories_user_id', 'user_categories')
    op.drop_table('user_categories')
    op.drop_table('system_categories')
