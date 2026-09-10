"""Harden income category case uniqueness and parent-derived link RLS.

Revision ID: c1a2b3c4d5e6
Revises: c0a1b2c3d4e5
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa


revision = "c1a2b3c4d5e6"
down_revision = "c0a1b2c3d4e5"
branch_labels = None
depends_on = None


def _merge_duplicate_links(bind, keep_id: int, duplicate_ids: list[int]) -> None:
    """Move compatible Notion cache metadata to ``keep_id`` without loss.

    A category has at most one cache row.  Two distinct Notion page IDs (or two
    non-null, different cached averages) cannot be represented by that schema,
    so the migration stops before changing any row.  Nullable fields otherwise
    merge into the canonical link and the newest sync timestamp is retained.
    """
    category_ids = [keep_id, *duplicate_ids]
    placeholders = ", ".join(f":id_{index}" for index in range(len(category_ids)))
    params = {f"id_{index}": category_id for index, category_id in enumerate(category_ids)}
    links = bind.execute(sa.text(
        "SELECT category_id, notion_page_id, synced_at, average "
        "FROM user_income_category_notion_links "
        f"WHERE category_id IN ({placeholders})"
    ), params).mappings().all()
    if not links:
        return

    pages = {link["notion_page_id"] for link in links if link["notion_page_id"] is not None}
    averages = {str(link["average"]) for link in links if link["average"] is not None}
    if len(pages) > 1:
        raise RuntimeError(
            f"Notion link conflict while deduplicating income categories {category_ids}: "
            "multiple notion_page_id values"
        )
    if len(averages) > 1:
        raise RuntimeError(
            f"Notion link conflict while deduplicating income categories {category_ids}: "
            "multiple average values"
        )

    page = next(iter(pages), None)
    average = next((link["average"] for link in links if link["average"] is not None), None)
    synced_values = [link["synced_at"] for link in links if link["synced_at"] is not None]
    synced_at = max(synced_values) if synced_values else None
    keep_link = next((link for link in links if link["category_id"] == keep_id), None)
    source_link = keep_link or links[0]
    duplicate_placeholders = ", ".join(
        f":duplicate_{index}" for index in range(len(duplicate_ids))
    )
    duplicate_params = {
        f"duplicate_{index}": category_id for index, category_id in enumerate(duplicate_ids)
    }
    if keep_link is None:
        bind.execute(sa.text(
            "UPDATE user_income_category_notion_links SET category_id = :keep_id, "
            "notion_page_id = :page, synced_at = :synced_at, average = :average "
            "WHERE category_id = :source_id"
        ), {"keep_id": keep_id, "source_id": source_link["category_id"], "page": page,
            "synced_at": synced_at, "average": average})
    else:
        # Delete the duplicate first: notion_page_id is unique and its value may
        # be the metadata that is about to fill the canonical cache row.
        bind.execute(sa.text(
            "DELETE FROM user_income_category_notion_links "
            f"WHERE category_id IN ({duplicate_placeholders})"
        ), duplicate_params)
        bind.execute(sa.text(
            "UPDATE user_income_category_notion_links SET notion_page_id = :page, "
            "synced_at = :synced_at, average = :average WHERE category_id = :keep_id"
        ), {"keep_id": keep_id, "page": page, "synced_at": synced_at, "average": average})

    if keep_link is None:
        bind.execute(sa.text(
            "DELETE FROM user_income_category_notion_links "
            f"WHERE category_id IN ({duplicate_placeholders})"
        ), duplicate_params)


def upgrade() -> None:
    bind = op.get_bind()
    # Deterministically preserve the oldest category. Historical incomes and the
    # optional Notion-link cache move to it before the duplicate row is removed.
    duplicates = bind.execute(sa.text(
        "SELECT user_id, lower(name) AS normalized_name, min(id) AS keep_id "
        "FROM user_income_categories GROUP BY user_id, lower(name) HAVING count(*) > 1"
    )).mappings().all()
    for row in duplicates:
        rows = bind.execute(sa.text(
            "SELECT id FROM user_income_categories WHERE user_id = :uid "
            "AND lower(name) = :name AND id != :keep_id"
        ), {"uid": row["user_id"], "name": row["normalized_name"],
            "keep_id": row["keep_id"]}).scalars().all()
        duplicate_ids = [int(duplicate_id) for duplicate_id in rows]
        # Resolve conflicts before moving incomes or deleting any category/link.
        _merge_duplicate_links(bind, int(row["keep_id"]), duplicate_ids)
        for duplicate_id in duplicate_ids:
            bind.execute(sa.text(
                "UPDATE incomes SET income_category_id = :keep_id WHERE income_category_id = :duplicate_id"
            ), {"keep_id": row["keep_id"], "duplicate_id": duplicate_id})
            bind.execute(sa.text("DELETE FROM user_income_categories WHERE id = :duplicate_id"),
                         {"duplicate_id": duplicate_id})
    op.create_index(
        "uq_user_income_categories_user_lower_name", "user_income_categories",
        ["user_id", sa.text("lower(name)")], unique=True,
    )
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE user_income_category_notion_links ENABLE ROW LEVEL SECURITY")
        predicate = (
            "EXISTS (SELECT 1 FROM user_income_categories c "
            "WHERE c.id = category_id AND c.user_id = current_setting('app.user_id', true))"
        )
        op.execute(
            "CREATE POLICY tenant_isolation ON user_income_category_notion_links "
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )
        # ``incomes`` was already RLS-protected by user_id. Its foreign key can
        # nevertheless be supplied directly by a malicious SQL client, so make
        # the category parent check part of WITH CHECK too.
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON incomes")
        income_predicate = (
            "user_id = current_setting('app.user_id', true) AND "
            "(income_category_id IS NULL OR EXISTS (SELECT 1 FROM user_income_categories c "
            "WHERE c.id = income_category_id "
            "AND c.user_id = current_setting('app.user_id', true)))"
        )
        op.execute(
            "CREATE POLICY tenant_isolation ON incomes "
            "USING (user_id = current_setting('app.user_id', true)) "
            f"WITH CHECK ({income_predicate})"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON user_income_category_notion_links")
        op.execute("ALTER TABLE user_income_category_notion_links DISABLE ROW LEVEL SECURITY")
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON incomes")
        op.execute(
            "CREATE POLICY tenant_isolation ON incomes "
            "USING (user_id = current_setting('app.user_id', true)) "
            "WITH CHECK (user_id = current_setting('app.user_id', true))"
        )
    op.drop_index("uq_user_income_categories_user_lower_name", table_name="user_income_categories")
