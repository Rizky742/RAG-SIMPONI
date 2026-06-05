"""
Schema Router
Endpoints to inspect, refresh, and browse the database schema metadata.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import SchemaResponse, SchemaTableInfo
from app.schema_layer import (
    extract_schema_metadata,
    get_cached_schema,
    clear_schema_cache,
)

router = APIRouter()


@router.get("/schema", response_model=SchemaResponse, summary="Get database schema metadata")
async def get_schema(
    schema_name: str = Query(default="public", description="PostgreSQL schema name"),
    refresh: bool = Query(default=False, description="Force refresh of cached schema"),
    db: AsyncSession = Depends(get_db),
):
    """Returns the full schema metadata including tables, columns, types, and foreign keys."""
    schema_meta = await extract_schema_metadata(db, schema_name=schema_name, refresh=refresh)

    tables = [
        SchemaTableInfo(
            table_name=tbl,
            table_comment=info.get("table_comment"),
            column_count=len(info["columns"]),
            columns=info["columns"],
            foreign_keys=info["foreign_keys"],
        )
        for tbl, info in schema_meta.items()
    ]

    return SchemaResponse(
        schema_name=schema_name,
        table_count=len(tables),
        tables=tables,
    )


@router.post("/schema/refresh", summary="Refresh schema cache")
async def refresh_schema(
    schema_name: str = Query(default="public"),
    db: AsyncSession = Depends(get_db),
):
    """Clears the schema cache and re-extracts metadata from PostgreSQL."""
    clear_schema_cache()
    schema_meta = await extract_schema_metadata(db, schema_name=schema_name, refresh=True)
    return {
        "message": "Schema cache refreshed successfully.",
        "schema_name": schema_name,
        "table_count": len(schema_meta),
        "tables": list(schema_meta.keys()),
    }


@router.get("/schema/tables", summary="List all tables in schema")
async def list_tables(
    schema_name: str = Query(default="public"),
    db: AsyncSession = Depends(get_db),
):
    """Quick endpoint to list all table names in the schema."""
    schema_meta = await extract_schema_metadata(db, schema_name=schema_name)
    return {
        "schema_name": schema_name,
        "tables": sorted(schema_meta.keys()),
        "table_count": len(schema_meta),
    }
