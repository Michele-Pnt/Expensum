"""drop_system_categories

`system_categories` fu introdotta da `b2c3d4e5f6a7` come tabella seed di categorie
predefinite condivise, ma non è mai stata collegata alla business logic: nessun
modulo in `src/` l'ha mai letta o referenziata. In produzione è rimasta vuota dal
deploy della migration a oggi. Le categorie restano gestite solo per utente in
`user_categories`.

Revision ID: a7b8c9d0e1f2
Revises: z6a7b8c9d0e1
Create Date: 2026-07-21 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "z6a7b8c9d0e1"
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
    op.drop_table("system_categories")


def downgrade() -> None:
    op.create_table(
        "system_categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.PrimaryKeyConstraint("id"),
    )
    sys_cat = table("system_categories", column("name", sa.String()))
    op.bulk_insert(sys_cat, [{"name": n} for n in SYSTEM_CATEGORIES])
