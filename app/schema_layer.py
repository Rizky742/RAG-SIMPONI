"""
Schema Understanding Layer
Extracts table/column metadata from PostgreSQL and builds
a schema-aware prompt context for the LLM.
"""

import time
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# In-memory schema cache (keyed by schema name), with a TTL so that schema
# changes (migrations, new tables) are eventually picked up without a restart.
# Use POST /schema/refresh for an immediate refresh.
_schema_cache: dict[str, dict] = {}
_schema_cache_ts: dict[str, float] = {}
SCHEMA_CACHE_TTL_SECONDS = 600  # 10 minutes


async def extract_schema_metadata(
    db: AsyncSession,
    schema_name: str = "public",
    refresh: bool = False,
) -> dict:
    """
    Extract full schema metadata from PostgreSQL information_schema.
    Returns a dict: { table_name: { columns: [...], foreign_keys: [...], comment: str } }
    """
    cached_at = _schema_cache_ts.get(schema_name, 0.0)
    is_fresh = (time.monotonic() - cached_at) < SCHEMA_CACHE_TTL_SECONDS
    if schema_name in _schema_cache and is_fresh and not refresh:
        return _schema_cache[schema_name]

    # ── 1. Tables & columns ─────────────────────────────────────────────
    col_query = text("""
        SELECT
            c.table_name,
            c.column_name,
            c.data_type,
            c.is_nullable,
            c.column_default,
            pgd.description AS column_comment
        FROM information_schema.columns c
        LEFT JOIN pg_catalog.pg_statio_all_tables st
            ON st.schemaname = c.table_schema
            AND st.relname    = c.table_name
        LEFT JOIN pg_catalog.pg_description pgd
            ON pgd.objoid  = st.relid
            AND pgd.objsubid = c.ordinal_position
        WHERE c.table_schema = :schema
        ORDER BY c.table_name, c.ordinal_position
    """)

    # ── 2. Primary keys ──────────────────────────────────────────────────
    pk_query = text("""
        SELECT
            tc.table_name,
            kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema   = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema    = :schema
    """)

    # ── 3. Foreign keys ──────────────────────────────────────────────────
    fk_query = text("""
        SELECT
            kcu.table_name,
            kcu.column_name,
            ccu.table_name  AS foreign_table_name,
            ccu.column_name AS foreign_column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema   = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
            ON ccu.constraint_name = tc.constraint_name
            AND ccu.table_schema   = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema    = :schema
    """)

    # ── 4. Table comments ────────────────────────────────────────────────
    tbl_comment_query = text("""
        SELECT
            relname AS table_name,
            obj_description(oid) AS table_comment
        FROM pg_catalog.pg_class
        WHERE relkind = 'r'
          AND relnamespace = (
              SELECT oid FROM pg_catalog.pg_namespace WHERE nspname = :schema
          )
    """)

    params = {"schema": schema_name}

    col_result       = await db.execute(col_query,        params)
    pk_result        = await db.execute(pk_query,         params)
    fk_result        = await db.execute(fk_query,         params)
    comment_result   = await db.execute(tbl_comment_query, params)

    columns      = col_result.fetchall()
    primary_keys = {(r.table_name, r.column_name) for r in pk_result.fetchall()}
    fk_rows      = fk_result.fetchall()
    tbl_comments = {r.table_name: r.table_comment for r in comment_result.fetchall()}

    # Build foreign-key map: table -> list of FK dicts
    fk_map: dict[str, list] = {}
    for r in fk_rows:
        fk_map.setdefault(r.table_name, []).append({
            "column": r.column_name,
            "references": f"{r.foreign_table_name}.{r.foreign_column_name}",
        })

    # Assemble metadata dict
    schema_meta: dict[str, dict] = {}
    for row in columns:
        tbl = row.table_name
        if tbl not in schema_meta:
            schema_meta[tbl] = {
                "table_comment": tbl_comments.get(tbl, ""),
                "columns": [],
                "foreign_keys": fk_map.get(tbl, []),
            }
        schema_meta[tbl]["columns"].append({
            "name":       row.column_name,
            "type":       row.data_type,
            "nullable":   row.is_nullable == "YES",
            "default":    row.column_default,
            "is_pk":      (tbl, row.column_name) in primary_keys,
            "comment":    row.column_comment or "",
        })

    _schema_cache[schema_name] = schema_meta
    _schema_cache_ts[schema_name] = time.monotonic()
    return schema_meta


def build_schema_prompt(schema_meta: dict, source_filter: Optional[str] = None) -> str:
    """
    Convert schema metadata into a compact, LLM-friendly text representation.
    Optional source_filter limits output to tables whose name contains the keyword.
    """
    # Ignore empty/whitespace and the Swagger UI placeholder "string" so a
    # stray default value doesn't silently filter every table away.
    if source_filter and source_filter.strip().lower() in ("", "string"):
        source_filter = None

    lines = ["### DATABASE SCHEMA\n"]

    # List all available tables upfront
    all_tables = sorted(schema_meta.keys())
    if not source_filter:
        lines.append(f"AVAILABLE TABLES: {', '.join(all_tables)}\n")

    for table_name, info in schema_meta.items():
        if source_filter and source_filter.lower() not in table_name.lower():
            continue

        comment_str = f"  -- {info['table_comment']}" if info["table_comment"] else ""
        lines.append(f"TABLE {table_name}{comment_str}")

        for col in info["columns"]:
            pk_tag  = " [PK]"      if col["is_pk"]   else ""
            null_tag = " NOT NULL" if not col["nullable"] else ""
            cmt_tag  = f"  -- {col['comment']}" if col["comment"] else ""
            lines.append(f"  {col['name']} {col['type'].upper()}{pk_tag}{null_tag}{cmt_tag}")

        for fk in info["foreign_keys"]:
            lines.append(f"  FK: {fk['column']} -> {fk['references']}")

        lines.append("")  # blank line between tables

    return "\n".join(lines)


def get_cached_schema(schema_name: str = "public") -> Optional[dict]:
    return _schema_cache.get(schema_name)


def clear_schema_cache():
    _schema_cache.clear()
    _schema_cache_ts.clear()
