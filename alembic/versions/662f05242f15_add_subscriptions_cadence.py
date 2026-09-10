"""Aggiunge la colonna cadence a subscriptions (gap preesistente, non collegato
alla normalizzazione voci di spesa).

`Subscription.cadence` esiste nel modello ORM (src/storage/models.py) da tempo, ma
non è mai stata generata la migration corrispondente per la tabella `subscriptions`
(esiste invece per `category_candidates`/`subscription_candidates`, con lo stesso
nome colonna — probabile confusione tra le due tabelle in una sessione precedente).
Scoperto perché blocca `fetch_subscriptions()`/`_build_quick_expenses` con
`UndefinedColumn` su ambienti dove lo schema è stato creato solo tramite Alembic
(mai un `CREATE TABLE` manuale che includesse già la colonna).

Revision ID: 662f05242f15
Revises: c1a2b3c4d5e6
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa

revision = "662f05242f15"
down_revision = "c1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("subscriptions", sa.Column("cadence", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("subscriptions", "cadence")
