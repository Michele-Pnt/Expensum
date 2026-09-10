"""Aggiunge position a quick_expense_shortcuts (riordino a tocca-e-trascina in chat).

Revision ID: 8f7ca225f00d
Revises: 5650f7efce23
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa

revision = "8f7ca225f00d"
down_revision = "5650f7efce23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "quick_expense_shortcuts",
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )
    # server_default solo per popolare le righe esistenti in modo sicuro — il
    # modello non lo dichiara (l'app assegna sempre position esplicitamente).
    op.alter_column("quick_expense_shortcuts", "position", server_default=None)


def downgrade() -> None:
    op.drop_column("quick_expense_shortcuts", "position")
