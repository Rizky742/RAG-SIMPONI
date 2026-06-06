"""
Database Execution Layer
Executes validated SQL queries against PostgreSQL and returns results.
"""

import asyncio
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

settings = get_settings()


class QueryExecutionError(Exception):
    """Raised when a SQL query fails during execution."""
    pass


async def execute_query(
    db: AsyncSession,
    sql: str,
) -> tuple[list[dict[str, Any]], int, bool]:
    """
    Execute a validated SQL query and return:
      - list of row dicts (column_name -> value)
      - number of rows returned to the caller
      - truncated flag: True if more rows existed than were returned

    Raises QueryExecutionError on failure.
    """
    try:
        # Execute with a timeout
        result = await asyncio.wait_for(
            _run_query(db, sql),
            timeout=settings.sql_timeout_seconds,
        )
        return result
    except asyncio.TimeoutError:
        await db.rollback()
        raise QueryExecutionError(
            f"Query timed out after {settings.sql_timeout_seconds} seconds. "
            "Try narrowing your query with more specific filters."
        )
    except Exception as e:
        # Roll back any partial transaction
        await db.rollback()
        raise QueryExecutionError(f"Query execution failed: {str(e)}")


async def _run_query(
    db: AsyncSession,
    sql: str,
) -> tuple[list[dict[str, Any]], int, bool]:
    """Internal: run the query and map rows to dicts.

    Fetches one row beyond the cap so we can reliably tell whether the
    result was truncated, instead of silently presenting a partial result
    as if it were the full total.
    """
    cap = settings.max_rows_returned
    result = await db.execute(text(sql))
    # Fetch cap + 1 rows: the extra row tells us the result was truncated.
    rows = result.fetchmany(cap + 1)

    truncated = len(rows) > cap
    if truncated:
        rows = rows[:cap]

    columns = list(result.keys())
    data = [
        {col: _serialize_value(row[i]) for i, col in enumerate(columns)}
        for row in rows
    ]

    return data, len(data), truncated


def _serialize_value(value: Any) -> Any:
    """Convert non-JSON-serializable types to serializable forms."""
    import datetime
    import decimal

    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        return str(value)
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return value
