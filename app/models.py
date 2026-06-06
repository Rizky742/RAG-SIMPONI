from pydantic import BaseModel, Field
from typing import Any, Optional


# ── Request Models ────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    user_id: str = Field(..., description="ID of the authenticated user")
    question: str = Field(..., min_length=1, max_length=2000, description="User's natural language question")
    history: list[ChatMessage] = Field(default=[], description="Previous conversation turns for multi-turn context")
    schema_name: str = Field(default="public", description="PostgreSQL schema to query against")
    source_filter: Optional[str] = Field(None, description="Filter schema to specific data source (e.g. 'tiktok' or 'shopee')")
    show_sql: bool = Field(default=False, description="Include the generated SQL in the response")


# ── Response Models ───────────────────────────────────────────────────────────

class ChatResponse(BaseModel):
    answer: str = Field(..., description="Natural language answer")
    sql_query: Optional[str] = Field(None, description="The SQL query that was executed (only if show_sql=True)")
    row_count: int = Field(..., description="Number of rows returned by the query")
    source_tables: list[str] = Field(default=[], description="Tables referenced in the query")
    error: Optional[str] = Field(None, description="Error message if something went wrong")


class SchemaTableInfo(BaseModel):
    table_name: str
    table_comment: Optional[str]
    column_count: int
    columns: list[dict[str, Any]]
    foreign_keys: list[dict[str, str]]


class SchemaResponse(BaseModel):
    schema_name: str
    table_count: int
    tables: list[SchemaTableInfo]
