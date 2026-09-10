"""Add user-scoped income categories and backfill the legacy bridge.

Revision ID: c0a1b2c3d4e5
Revises: baad13e21af4
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa


revision = "c0a1b2c3d4e5"
down_revision = "baad13e21af4"
branch_labels = None
depends_on = None

_DEFAULTS = (
    "Stipendio", "Bonus lavorativo", "Rimborso", "Regalo",
    "Cashback", "Dividendi", "Interessi", "Altra entrata",
)
_ALIASES = {"bonus": "Bonus lavorativo", "bonus aziendale": "Bonus lavorativo"}
_POLICY = "tenant_isolation"


def _normalized(value: str | None) -> str:
    """Normalize only known legacy aliases, preserving custom historical names."""
    if value is None or not value.strip():
        return "Altra entrata"
    cleaned = value.strip()
    lowered = cleaned.casefold()
    if lowered in _ALIASES:
        return _ALIASES[lowered]
    for name in _DEFAULTS:
        if name.casefold() == lowered:
            return name
    return cleaned


def _ensure_category(bind, user_id: str, name: str) -> int:
    """Get or create a category id; safe on repeated migration execution."""
    found = bind.execute(sa.text(
        "SELECT id FROM user_income_categories "
        "WHERE user_id = :uid AND lower(name) = lower(:name) LIMIT 1"
    ), {"uid": user_id, "name": name}).scalar()
    if found is not None:
        return int(found)
    bind.execute(sa.text(
        "INSERT INTO user_income_categories (user_id, name) VALUES (:uid, :name)"
    ), {"uid": user_id, "name": name})
    return int(bind.execute(sa.text(
        "SELECT id FROM user_income_categories "
        "WHERE user_id = :uid AND lower(name) = lower(:name) LIMIT 1"
    ), {"uid": user_id, "name": name}).scalar_one())


def upgrade() -> None:
    bind = op.get_bind()
    op.create_table(
        "user_income_categories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.chat_id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("monthly_budget", sa.Numeric(12, 2), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("description_summary", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("budget_suggestion_dismissed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id", "name", name="uq_user_income_categories_user_name"),
    )
    op.create_index("ix_user_income_categories_user_id", "user_income_categories", ["user_id"])
    op.create_table(
        "user_income_category_notion_links",
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("user_income_categories.id"), primary_key=True),
        sa.Column("notion_page_id", sa.String(), nullable=True, unique=True),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.Column("average", sa.Numeric(12, 2), nullable=True),
    )
    # SQLite cannot ALTER TABLE ADD COLUMN with a foreign-key constraint. Batch
    # mode rebuilds only this table and keeps the expansion migration testable on
    # the local development backend as required by the release plan.
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("incomes") as batch_op:
            batch_op.add_column(sa.Column("income_category_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_incomes_income_category_id", "user_income_categories",
                ["income_category_id"], ["id"],
            )
    else:
        op.add_column("incomes", sa.Column(
            "income_category_id", sa.Integer(), sa.ForeignKey("user_income_categories.id"), nullable=True,
        ))
    op.create_index("ix_incomes_income_category_id", "incomes", ["income_category_id"])

    rows = bind.execute(sa.text(
        "SELECT id, user_id, income_type FROM incomes WHERE income_category_id IS NULL"
    )).mappings().all()
    user_ids = {str(row["user_id"]) for row in rows}
    for user_id in user_ids:
        for name in _DEFAULTS:
            _ensure_category(bind, user_id, name)
    for row in rows:
        category_id = _ensure_category(bind, str(row["user_id"]), _normalized(row["income_type"]))
        bind.execute(sa.text(
            "UPDATE incomes SET income_category_id = :category_id WHERE id = :income_id"
        ), {"category_id": category_id, "income_id": row["id"]})

    if bind.dialect.name == "postgresql":
        for table in ("user_income_categories",):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(
                f"CREATE POLICY {_POLICY} ON {table} "
                "USING (user_id = current_setting('app.user_id', true)) "
                "WITH CHECK (user_id = current_setting('app.user_id', true))"
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(f"DROP POLICY IF EXISTS {_POLICY} ON user_income_categories")
        op.execute("ALTER TABLE user_income_categories DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_incomes_income_category_id", table_name="incomes")
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("incomes") as batch_op:
            batch_op.drop_constraint("fk_incomes_income_category_id", type_="foreignkey")
            batch_op.drop_column("income_category_id")
    else:
        op.drop_column("incomes", "income_category_id")
    op.drop_table("user_income_category_notion_links")
    op.drop_index("ix_user_income_categories_user_id", table_name="user_income_categories")
    op.drop_table("user_income_categories")
