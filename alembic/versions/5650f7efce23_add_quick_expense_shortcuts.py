"""Aggiunge quick_expense_shortcuts (bottoni spesa rapida creati manualmente).

Distinto dal bottone automatico (calcolato al volo, mai persistito) — qui l'utente
sceglie esplicitamente nome/categoria/conto una volta, restano fissi finché non li
cancella. Contiene testo libero (`name`): stessa RLS per-tenant delle altre tabelle
finanziarie per-utente (pattern da baad13e21af4_add_expense_label_clusters.py).

Revision ID: 5650f7efce23
Revises: 662f05242f15
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa

revision = "5650f7efce23"
down_revision = "662f05242f15"
branch_labels = None
depends_on = None

_POLICY = "tenant_isolation"


def upgrade() -> None:
    op.create_table(
        "quick_expense_shortcuts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.chat_id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("user_categories.id"), nullable=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_quick_expense_shortcuts_user_id",
        "quick_expense_shortcuts",
        ["user_id"],
    )

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("ALTER TABLE quick_expense_shortcuts ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {_POLICY} ON quick_expense_shortcuts
            USING (user_id = current_setting('app.user_id', true))
            WITH CHECK (user_id = current_setting('app.user_id', true))
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(f"DROP POLICY IF EXISTS {_POLICY} ON quick_expense_shortcuts")
        op.execute("ALTER TABLE quick_expense_shortcuts DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_quick_expense_shortcuts_user_id", table_name="quick_expense_shortcuts")
    op.drop_table("quick_expense_shortcuts")
