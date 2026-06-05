"""
Chat Router
Orchestrates the full Text-to-SQL pipeline:
  Data Layer → Schema Layer → Text-to-SQL → SQL Validation →
  DB Execution → LLM Narration → Response
"""

import re
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ChatRequest, ChatResponse
from app.schema_layer import extract_schema_metadata, build_schema_prompt
from app.llm_service import generate_sql, generate_narration
from app.sql_validator import validate_and_sanitize_sql, extract_sql_from_llm_response
from app.db_executor import execute_query, QueryExecutionError

logger = logging.getLogger(__name__)
router = APIRouter()


def _extract_table_names(sql: str) -> list[str]:
    """Simple regex to extract table names from a SQL query."""
    pattern = r"(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)"
    return list(set(re.findall(pattern, sql, re.IGNORECASE)))


def _is_meta_question(question: str) -> bool:
    """Check if the question is about capabilities, not data analysis."""
    meta_keywords = [
        "apa aja", "apa saja", "apa yang bisa", "fitur apa",
        "kemampuan", "bisa apa", "kapabilitas", "help", "bantuan apa",
        "apa yang kamu", "apa yang aku", "what can you", "what do you",
        "capabilities", "features", "what features"
    ]
    q_lower = question.lower()
    return any(keyword in q_lower for keyword in meta_keywords)


def _get_capabilities_response() -> str:
    """Return a user-friendly capabilities response."""
    return """Saya bisa membantu Anda menganalisis data e-commerce dari TikTok Shop dan Shopee dengan pertanyaan-pertanyaan seperti:

**Tentang Penjualan:**
- "Berapa total penjualan bulan ini?"
- "Tampilkan penjualan per hari minggu lalu"
- "Mana toko yang paling laku?"

**Tentang Produk:**
- "Produk apa yang paling terjual?"
- "Produk mana yang paling sedikit stok?"
- "Berapa jumlah produk yang kami punya?"

**Tentang Order:**
- "Berapa jumlah order baru hari ini?"
- "Order mana saja yang sudah selesai?"
- "Status pembayaran apa yang paling banyak?"

**Tentang Performa Toko:**
- "Toko mana yang paling banyak order?"
- "Perbandingan penjualan antar toko"
- "Kategori produk apa yang paling diminati?"

Cukup tanyakan apa yang ingin Anda ketahui tentang data, saya akan bantu!"""


@router.post("/chat", response_model=ChatResponse, summary="Ask a question about your data")
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Full Text-to-SQL pipeline:
    1. Extract & cache schema metadata (Schema Understanding Layer)
    2. Build schema-aware prompt
    3. LLM generates SQL (Text-to-SQL Processing Layer)
    4. Validate & sanitize SQL (Security Check)
    5. Execute query (Database Execution Layer)
    6. LLM narrates the result (Generation Layer)
    """
    # Handle meta questions about capabilities
    if _is_meta_question(request.question):
        return ChatResponse(answer=_get_capabilities_response(), row_count=0)

    try:
        # ── Step 1: Schema Understanding Layer ───────────────────────────
        logger.info(f"[1/5] Extracting schema metadata for '{request.schema_name}'...")
        schema_meta = await extract_schema_metadata(
            db,
            schema_name=request.schema_name,
        )

        if not schema_meta:
            raise HTTPException(
                status_code=404,
                detail=f"No tables found in schema '{request.schema_name}'. "
                       "Make sure the schema exists and contains tables.",
            )

        schema_prompt = build_schema_prompt(schema_meta, source_filter=request.source_filter)

        # ── Step 2: Text-to-SQL Processing Layer ─────────────────────────
        logger.info(f"[2/5] Generating SQL for question: '{request.question}'")
        conversation_history = [
            {"role": m.role, "content": m.content}
            for m in request.history
        ]

        llm_sql_response = await generate_sql(
            user_question=request.question,
            schema_prompt=schema_prompt,
            conversation_history=conversation_history if conversation_history else None,
        )

        # ── Step 3: SQL Validation & Security Check ───────────────────────
        logger.info("[3/5] Validating generated SQL...")
        raw_sql = extract_sql_from_llm_response(llm_sql_response)
        validation = validate_and_sanitize_sql(raw_sql)

        if not validation.is_valid:
            logger.warning(f"SQL validation failed: {validation.error}")
            return ChatResponse(
                answer=(
                    "I'm sorry, I was unable to generate a valid query for your question. "
                    f"Reason: {validation.error}\n\n"
                    "Please try rephrasing your question."
                ),
                row_count=0,
                error=validation.error,
            )

        clean_sql = validation.cleaned_sql
        logger.info(f"Validated SQL:\n{clean_sql}")

        # ── Step 4: Database Execution Layer ──────────────────────────────
        logger.info("[4/5] Executing query against PostgreSQL...")
        try:
            rows, row_count = await execute_query(db, clean_sql)
        except QueryExecutionError as e:
            logger.error(f"Query execution error: {e}")
            return ChatResponse(
                answer=(
                    "I encountered an error while running the query. "
                    f"Details: {str(e)}\n\n"
                    "Please try rephrasing your question or contact support."
                ),
                sql_query=clean_sql if request.show_sql else None,
                row_count=0,
                error=str(e),
            )

        logger.info(f"Query returned {row_count} rows.")

        # ── Step 5: Generation Layer (LLM Narration) ──────────────────────
        logger.info("[5/5] Generating natural language answer...")
        answer = await generate_narration(
            user_question=request.question,
            sql_query=clean_sql,
            query_result=rows,
            row_count=row_count,
        )

        return ChatResponse(
            answer=answer,
            sql_query=clean_sql if request.show_sql else None,
            row_count=row_count,
            source_tables=_extract_table_names(clean_sql),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error in chat pipeline")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
