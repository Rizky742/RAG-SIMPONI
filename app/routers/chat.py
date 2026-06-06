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
from app.auth_service import get_user_store_ids, build_store_filter_clause
from app.llm_service import (
    generate_sql,
    regenerate_sql_with_error,
    generate_narration,
    classify_question,
    generate_chat_reply,
    LLMServiceError,
)
from app.sql_validator import validate_and_sanitize_sql, extract_sql_from_llm_response
from app.db_executor import execute_query, QueryExecutionError

logger = logging.getLogger(__name__)
router = APIRouter()


def _extract_table_names(sql: str) -> list[str]:
    """Simple regex to extract table names from a SQL query."""
    pattern = r"(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)"
    return list(set(re.findall(pattern, sql, re.IGNORECASE)))


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
    0. Route the question (DATA / CHAT / OFFTOPIC)
    1. Extract & cache schema metadata (Schema Understanding Layer)
    2. Build schema-aware prompt
    3. LLM generates SQL (Text-to-SQL Processing Layer)
    4. Validate & sanitize SQL (Security Check)
    5. Execute query (Database Execution Layer; self-corrects once on failure)
    6. LLM narrates the result (Generation Layer)
    """
    conversation_history = [
        {"role": m.role, "content": m.content}
        for m in request.history
    ]
    history_arg = conversation_history if conversation_history else None

    # ── Step 0: Route the question ───────────────────────────────────────
    try:
        route = await classify_question(request.question, history_arg)
    except LLMServiceError:
        # If the router itself errors, fall through to the data pipeline.
        route = "DATA"

    if route in ("CHAT", "OFFTOPIC"):
        logger.info(f"[router] Non-data question classified as {route}")
        try:
            answer = await generate_chat_reply(
                request.question,
                is_offtopic=(route == "OFFTOPIC"),
                conversation_history=history_arg,
            )
        except LLMServiceError:
            # Last-resort static fallback so the user always gets something useful.
            answer = _get_capabilities_response()
        return ChatResponse(answer=answer, row_count=0)

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

        # ── Step 1b: Multi-tenant filtering ────────────────────────────────
        logger.info(f"[1b/5] Getting stores for user '{request.user_id}'...")
        user_store_ids = await get_user_store_ids(db, request.user_id)

        if not user_store_ids:
            raise HTTPException(
                status_code=403,
                detail=f"User '{request.user_id}' has no associated stores.",
            )

        store_filter = build_store_filter_clause(user_store_ids, table_alias="s")
        logger.info(f"User has access to {len(user_store_ids)} store(s)")

        schema_prompt = build_schema_prompt(schema_meta, source_filter=request.source_filter)
        # Add multi-tenant context to the prompt
        schema_prompt += f"\n\nIMPORTANT: User can only access data from these stores: {', '.join(user_store_ids)}\n"
        schema_prompt += f"Always include in WHERE clause: {store_filter.replace('s.', 'stores.')}\n"

        # ── Step 2: Text-to-SQL Processing Layer ─────────────────────────
        logger.info(f"[2/5] Generating SQL for question: '{request.question}'")
        try:
            llm_sql_response = await generate_sql(
                user_question=request.question,
                schema_prompt=schema_prompt,
                conversation_history=history_arg,
            )
        except LLMServiceError as e:
            logger.error(f"LLM SQL generation failed: {e}")
            return ChatResponse(
                answer=(
                    "Maaf, saya sedang tidak bisa memproses pertanyaan Anda karena "
                    "kendala pada layanan AI. Silakan coba lagi sebentar lagi."
                ),
                row_count=0,
                error=str(e),
            )

        # If the model could not map the question to the schema, surface it cleanly.
        if llm_sql_response.strip().upper().startswith("ERROR:"):
            logger.info(f"LLM reported it cannot answer: {llm_sql_response}")
            return ChatResponse(
                answer=(
                    "Maaf, saya tidak menemukan data yang sesuai untuk menjawab pertanyaan itu. "
                    f"{llm_sql_response.strip()[len('ERROR:'):].strip()}\n\n"
                    "Coba ubah pertanyaan Anda."
                ),
                row_count=0,
            )

        # ── Step 3: SQL Validation & Security Check ───────────────────────
        logger.info("[3/5] Validating generated SQL...")
        raw_sql = extract_sql_from_llm_response(llm_sql_response)
        validation = validate_and_sanitize_sql(raw_sql)

        if not validation.is_valid:
            logger.warning(f"SQL validation failed: {validation.error}")
            return ChatResponse(
                answer=(
                    "Maaf, saya belum bisa menyusun query yang aman untuk pertanyaan itu. "
                    "Coba ajukan kembali dengan lebih spesifik."
                ),
                row_count=0,
                error=validation.error,
            )

        clean_sql = validation.cleaned_sql
        logger.info(f"Validated SQL:\n{clean_sql}")

        # ── Step 4: Database Execution Layer (with one self-correction) ───
        logger.info("[4/5] Executing query against PostgreSQL...")
        try:
            rows, row_count, truncated = await execute_query(db, clean_sql)
        except QueryExecutionError as first_error:
            logger.warning(f"Query failed, attempting self-correction: {first_error}")

            # Ask the LLM to fix the query using the actual PostgreSQL error.
            corrected_sql = clean_sql
            retry_failed = True
            try:
                corrected_response = await regenerate_sql_with_error(
                    user_question=request.question,
                    schema_prompt=schema_prompt,
                    failed_sql=clean_sql,
                    db_error=str(first_error),
                )
            except LLMServiceError:
                corrected_response = ""

            if corrected_response and not corrected_response.strip().upper().startswith("ERROR:"):
                retry_sql = extract_sql_from_llm_response(corrected_response)
                retry_validation = validate_and_sanitize_sql(retry_sql)
                if retry_validation.is_valid:
                    corrected_sql = retry_validation.cleaned_sql
                    logger.info(f"Self-corrected SQL:\n{corrected_sql}")
                    try:
                        rows, row_count, truncated = await execute_query(db, corrected_sql)
                        clean_sql = corrected_sql  # report the query that actually ran
                        retry_failed = False
                    except QueryExecutionError as second_error:
                        logger.error(f"Self-correction also failed: {second_error}")

            if retry_failed:
                return ChatResponse(
                    answer=(
                        "Maaf, saya kesulitan menyusun query yang tepat untuk pertanyaan itu. "
                        "Coba ajukan dengan lebih spesifik — misalnya sebutkan rentang waktu, "
                        "nama toko, atau platform (TikTok Shop / Shopee)."
                    ),
                    sql_query=clean_sql if request.show_sql else None,
                    row_count=0,
                    error=str(first_error),
                )

        logger.info(f"Query returned {row_count} rows.")

        # ── Step 5: Generation Layer (LLM Narration) ──────────────────────
        logger.info("[5/5] Generating natural language answer...")
        try:
            answer = await generate_narration(
                user_question=request.question,
                sql_query=clean_sql,
                query_result=rows,
                row_count=row_count,
                truncated=truncated,
            )
        except LLMServiceError as e:
            logger.error(f"LLM narration failed: {e}")
            return ChatResponse(
                answer=(
                    "Query berhasil dijalankan, tetapi saya gagal merangkum hasilnya "
                    "karena kendala layanan AI. Silakan coba lagi."
                ),
                sql_query=clean_sql if request.show_sql else None,
                row_count=row_count,
                source_tables=_extract_table_names(clean_sql),
                error=str(e),
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
