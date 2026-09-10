"""Aggiunge expense_label_overrides, anchor_locked e la preferenza di raggruppamento.

Rende durevoli le correzioni manuali dell'utente al raggruppamento automatico delle
voci di spesa ("Unisci"/"Dividi" dal grafico Analytics): senza una regola persistita,
la spesa successiva con lo stesso testo verrebbe ri-accorpata dal matching fuzzy
(`partial_ratio("ape", "ape 50 tagliando")` = 100), vanificando la correzione.

- `expense_label_overrides`: forza un testo normalizzato a un cluster preciso.
  Consultata da `assign_label_cluster` PRIMA del fuzzy. Contiene testo libero
  dell'utente (`normalized_text`), quindi riceve subito la stessa RLS per-tenant delle
  altre tabelle finanziarie (pattern da baad13e21af4_add_expense_label_clusters.py).
- `expense_label_clusters.anchor_locked`: l'etichetta scelta dall'utente non viene più
  sostituita dalla variante più frequente.
- `users.analytics_group_labels`: switch "raggruppa" / "per nome" nei grafici.

Revision ID: c9d1e4b7a206
Revises: f9e8d7c6b5a4
Create Date: 2026-09-03
"""
from alembic import op
import sqlalchemy as sa

revision = "c9d1e4b7a206"
down_revision = "f9e8d7c6b5a4"
branch_labels = None
depends_on = None

_POLICY = "tenant_isolation"


def upgrade() -> None:
    op.create_table(
        "expense_label_overrides",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.chat_id"), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("user_categories.id"), nullable=True),
        sa.Column("normalized_text", sa.String(), nullable=False),
        sa.Column(
            "cluster_id", sa.Integer(),
            sa.ForeignKey("expense_label_clusters.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_expense_label_overrides_lookup",
        "expense_label_overrides",
        ["user_id", "category_id", "normalized_text"],
    )
    op.create_index(
        "ix_expense_label_overrides_cluster", "expense_label_overrides", ["cluster_id"],
    )
    # Indici parziali: in Postgres due NULL su category_id non collidono, quindi un
    # unique semplice non proteggerebbe le spese senza categoria dai duplicati.
    op.create_index(
        "uq_expense_label_overrides_cat",
        "expense_label_overrides",
        ["user_id", "category_id", "normalized_text"],
        unique=True,
        postgresql_where=sa.text("category_id IS NOT NULL"),
        sqlite_where=sa.text("category_id IS NOT NULL"),
    )
    op.create_index(
        "uq_expense_label_overrides_nocat",
        "expense_label_overrides",
        ["user_id", "normalized_text"],
        unique=True,
        postgresql_where=sa.text("category_id IS NULL"),
        sqlite_where=sa.text("category_id IS NULL"),
    )

    op.add_column(
        "expense_label_clusters",
        sa.Column("anchor_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("analytics_group_labels", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
    )

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite/dev: nessuna RLS, stesso no-op delle altre migration RLS. Le garanzie
        # restano il filtro applicativo `WHERE user_id = ...` già nel layer storage.
        return

    op.execute("ALTER TABLE expense_label_overrides ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {_POLICY} ON expense_label_overrides
            USING (user_id = current_setting('app.user_id', true))
            WITH CHECK (user_id = current_setting('app.user_id', true))
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(f"DROP POLICY IF EXISTS {_POLICY} ON expense_label_overrides")
        op.execute("ALTER TABLE expense_label_overrides DISABLE ROW LEVEL SECURITY")

    op.drop_column("users", "analytics_group_labels")
    op.drop_column("expense_label_clusters", "anchor_locked")
    op.drop_index("uq_expense_label_overrides_nocat", table_name="expense_label_overrides")
    op.drop_index("uq_expense_label_overrides_cat", table_name="expense_label_overrides")
    op.drop_index("ix_expense_label_overrides_cluster", table_name="expense_label_overrides")
    op.drop_index("ix_expense_label_overrides_lookup", table_name="expense_label_overrides")
    op.drop_table("expense_label_overrides")
