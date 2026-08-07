"""Aggiunge category e rating alla tabella feedbacks per il check-in beta settimanale.

Il loop settimanale di validazione feature (job `_beta_feature_validation_job`,
bot.py) chiede ai beta tester di reagire (👍/👎/non usata) a poche feature chiave
e poi di lasciare un feedback libero. Le risposte finiscono nella tabella
`feedbacks` esistente, taggate con category="beta_validation" e rating
("up"/"down"/"skip") per distinguerle dai feedback liberi via /feedback
(entrambe le colonne restano NULL per quelli, nessuna migrazione dati necessaria).

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-08-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, Sequence[str], None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("feedbacks", sa.Column("category", sa.String(), nullable=True))
    op.add_column("feedbacks", sa.Column("rating", sa.String(), nullable=True))
    op.create_index("ix_feedbacks_category", "feedbacks", ["category"])


def downgrade() -> None:
    op.drop_index("ix_feedbacks_category", table_name="feedbacks")
    op.drop_column("feedbacks", "rating")
    op.drop_column("feedbacks", "category")
