"""
Multi-tenant filtering: get stores for a given user.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_user_store_ids(db: AsyncSession, user_id: str) -> list[str]:
    """
    Get all store IDs that belong to the given user.
    Returns a list of store UUIDs (as strings).
    """
    query = text("""
        SELECT DISTINCT su.store_id
        FROM store_users su
        WHERE su.user_id = :user_id
        ORDER BY su.store_id
    """)

    result = await db.execute(query, {"user_id": user_id})
    rows = result.fetchall()
    return [str(row[0]) for row in rows]


def build_store_filter_clause(store_ids: list[str], table_alias: str = "s") -> str:
    """
    Build a WHERE clause fragment to filter by stores.
    Assumes the main table has a store_id column or joins to stores table.

    Example: "s.store_id IN ('uuid1', 'uuid2')"
    """
    if not store_ids:
        return ""

    store_list = ", ".join(f"'{sid}'" for sid in store_ids)
    return f"{table_alias}.store_id IN ({store_list})"
