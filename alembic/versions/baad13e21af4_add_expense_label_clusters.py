"""Aggiunge expense_label_clusters e la FK label_cluster_id su expenses.

Metadato di sola aggregazione grafici (voce di spesa normalizzata) — la descrizione
originale della spesa (Expense.name) non viene mai toccata. Vedi
src/expense_label_normalizer.py per la logica di matching.

`expense_label_clusters` contiene testo libero dell'utente (`anchor_text` e le chiavi
di `variant_counts`), quindi riceve subito la stessa RLS per-tenant delle altre tabelle
finanziarie per-utente (pattern da b8c9d0e1f2a3_add_loans_and_rls_retrofit.py) — qui
niente gap da colmare in un secondo momento, la tabella è nuova.

Revision ID: baad13e21af4
Revises: b29df51a6e74
Create Date: 2026-08-30
"""
from alembic import op
import sqlalchemy as sa

revision = "baad13e21af4"
down_revision = "b29df51a6e74"
branch_labels = None
depends_on = None

_POLICY = "tenant_isolation"


def upgrade() -> None:
    op.create_table(
        "expense_label_clusters",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.chat_id"), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("user_categories.id"), nullable=True),
        sa.Column("anchor_text", sa.String(), nullable=False),
        sa.Column("variant_counts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_expense_label_clusters_user_category",
        "expense_label_clusters",
        ["user_id", "category_id"],
    )
    op.add_column(
        "expenses",
        sa.Column(
            "label_cluster_id", sa.Integer(),
            sa.ForeignKey("expense_label_clusters.id"), nullable=True,
        ),
    )

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite/dev: nessuna RLS, stesso no-op delle altre migration RLS. Le garanzie
        # restano il filtro applicativo `WHERE user_id = ...` già nel layer storage.
        return

    op.execute("ALTER TABLE expense_label_clusters ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {_POLICY} ON expense_label_clusters
            USING (user_id = current_setting('app.user_id', true))
            WITH CHECK (user_id = current_setting('app.user_id', true))
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(f"DROP POLICY IF EXISTS {_POLICY} ON expense_label_clusters")
        op.execute("ALTER TABLE expense_label_clusters DISABLE ROW LEVEL SECURITY")

    op.drop_column("expenses", "label_cluster_id")
    op.drop_index("ix_expense_label_clusters_user_category", table_name="expense_label_clusters")
    op.drop_table("expense_label_clusters")
