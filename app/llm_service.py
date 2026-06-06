"""
LLM Service (OpenAI)
Handles two LLM calls:
  1. Text-to-SQL  : converts user question + schema context → SQL query
  2. Narration    : converts query result → natural language answer
"""

import json
import logging
from typing import Any

from openai import OpenAI, OpenAIError

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class LLMServiceError(Exception):
    """Raised when an OpenAI call fails (auth, rate limit, network, etc.)."""
    pass


# Lazy singleton — client is created on first use so the module imports
# fine even before the API key is configured.
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        # Only pass base_url when explicitly configured; otherwise let the SDK
        # use the official OpenAI endpoint. An empty string would be an invalid URL.
        kwargs: dict[str, Any] = {
            "api_key": settings.openai_api_key,
            "timeout": settings.request_timeout,
        }
        if settings.base_url:
            kwargs["base_url"] = settings.base_url
        _client = OpenAI(**kwargs)
    return _client


def _is_reasoning_model(model: str) -> bool:
    """GPT-5 / o-series reasoning models use `max_completion_tokens` (not
    `max_tokens`) and only accept the default temperature (1)."""
    m = model.lower()
    return m.startswith(("gpt-5", "o1", "o3", "o4"))


def _chat_completion(messages: list[dict], max_output_tokens: int, temperature: float = 0):
    """Single entry point for all OpenAI chat calls.

    Normalizes the parameters that differ between model families so callers
    don't have to care: reasoning models (gpt-5, o-series) require
    `max_completion_tokens` and reject a non-default temperature, while the
    gpt-4o family uses `max_tokens` and accepts `temperature`.
    """
    model = settings.llm_model
    kwargs: dict[str, Any] = {"model": model, "messages": messages}

    if _is_reasoning_model(model):
        kwargs["max_completion_tokens"] = max_output_tokens
        # Reasoning models only support temperature=1; omit to use the default.
    else:
        kwargs["max_tokens"] = max_output_tokens
        kwargs["temperature"] = temperature

    return _get_client().chat.completions.create(**kwargs)


# ── System Prompts ────────────────────────────────────────────────────────────

TEXT_TO_SQL_SYSTEM_PROMPT = """You are an expert PostgreSQL analyst. Your job is to convert natural language questions into precise, optimized SQL SELECT queries.

CRITICAL RULES (MUST FOLLOW STRICTLY):
1. ONLY generate SELECT queries. Never INSERT, UPDATE, DELETE, DROP, or ALTER.
2. ONLY use table and column names that EXACTLY appear in the DATABASE SCHEMA provided below. Do NOT invent, guess, or assume any name that is not listed. The schema is the single source of truth — if a column is not in the schema, it does not exist.
3. Always use explicit table aliases when joining tables.
4. Return ONLY the SQL query — no explanation, no markdown, no preamble.

QUERY BUILDING RULES:
5. Use LIMIT {max_rows} unless the user explicitly asks for all rows.
6. When filtering text columns, use ILIKE for case-insensitive matching.
7. Always handle NULL values gracefully (COALESCE, IS NOT NULL, etc.).
8. Use the foreign-key relationships listed in the schema to join tables correctly.
9. Use proper date/time functions (DATE_TRUNC, EXTRACT, etc.) for temporal analysis.
10. Prefer CTEs (WITH clauses) for complex queries to improve readability.
11. If the schema does not contain the tables/columns needed to answer the question, respond with a single line starting with "ERROR:" explaining what is missing, instead of inventing columns.

The database contains e-commerce data from TikTok Shop and Shopee platforms.
"""

NARRATION_SYSTEM_PROMPT = """You are a friendly and insightful e-commerce data analyst assistant.
Your job is to turn raw SQL query results into clear, concise, and helpful natural language responses.

RULES:
1. Answer in the same language the user used to ask the question.
2. Be concise but complete — highlight key insights.
3. Use numbers, percentages, and comparisons where helpful.
4. If the result is empty, say so clearly and suggest why that might be.
5. Format currency values appropriately (e.g., Rp 1.500.000 for IDR).
6. Mention data source (TikTok Shop / Shopee) when relevant.
7. Never make up data — only refer to what's in the query result.
"""


ROUTER_SYSTEM_PROMPT = """You are a router for an e-commerce analytics chatbot connected to a PostgreSQL database with TikTok Shop and Shopee data.

Classify the user's latest message into EXACTLY ONE category and reply with ONLY that single word:
- DATA      : needs querying the database (sales, orders, products, stock, revenue, store performance, comparisons, counts, trends, etc.)
- CHAT      : greetings, thanks, small talk, or questions about what you can do / who you are.
- OFFTOPIC  : a real question but NOT answerable from the store's database (e.g. general marketing advice, opinions, world knowledge, coding help).

Reply with one word only: DATA, CHAT, or OFFTOPIC. No punctuation, no explanation."""


async def classify_question(
    user_question: str,
    conversation_history: list[dict] | None = None,
) -> str:
    """
    Lightweight LLM router. Returns one of: "DATA", "CHAT", "OFFTOPIC".
    Falls back to "DATA" on any ambiguity/error so the question still gets
    a real attempt rather than being wrongly rejected.
    """
    messages: list[dict] = [{"role": "system", "content": ROUTER_SYSTEM_PROMPT}]
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_question})

    try:
        # Reasoning models spend tokens on hidden reasoning before emitting the
        # label, so give a small budget rather than 4 tokens (which can come back
        # empty). Non-reasoning models simply ignore the headroom.
        response = _chat_completion(messages, max_output_tokens=16)
    except OpenAIError as e:
        # Don't block the user on a router failure — default to attempting DATA.
        logger.warning("Router classification failed, defaulting to DATA: %s", e)
        return "DATA"

    raw = (response.choices[0].message.content or "").strip().upper()
    for label in ("DATA", "CHAT", "OFFTOPIC"):
        if label in raw:
            return label
    return "DATA"


async def generate_chat_reply(
    user_question: str,
    is_offtopic: bool,
    conversation_history: list[dict] | None = None,
) -> str:
    """
    Answer a non-data message (greeting/small talk, or an off-topic question)
    naturally, while steering the user back toward what the bot can do.
    """
    if is_offtopic:
        guidance = (
            "The user's question cannot be answered from the store database. "
            "Reply briefly and helpfully in the user's language, make clear you focus on "
            "analyzing their TikTok Shop and Shopee store data, and invite a data question."
        )
    else:
        guidance = (
            "The user is making small talk or greeting you. Reply warmly and briefly in the "
            "user's language, and remind them you can analyze their TikTok Shop and Shopee store data."
        )

    messages = [
        {"role": "system", "content": f"You are Simponi, a friendly e-commerce analytics assistant. {guidance}"},
    ]
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_question})

    try:
        response = _chat_completion(messages, max_output_tokens=settings.max_tokens)
    except OpenAIError as e:
        logger.error("OpenAI chat-reply call failed: %s", e)
        raise LLMServiceError(f"Failed to generate a reply: {e}") from e

    return response.choices[0].message.content or ""


async def generate_sql(
    user_question: str,
    schema_prompt: str,
    conversation_history: list[dict] | None = None,
) -> str:
    """
    Call OpenAI to convert the user question + schema context into a SQL query.
    Returns the raw LLM response text (SQL extraction happens in the caller).
    """
    system = TEXT_TO_SQL_SYSTEM_PROMPT.format(max_rows=settings.max_rows_returned)
    system += f"\n\n{schema_prompt}"

    messages: list[dict] = [{"role": "system", "content": system}]

    # Include conversation history for multi-turn context
    if conversation_history:
        messages.extend(conversation_history)

    messages.append({
        "role": "user",
        "content": (
            f"Generate a PostgreSQL SELECT query to answer this question:\n\n"
            f"{user_question}\n\n"
            f"Return ONLY the SQL query, nothing else."
        ),
    })

    try:
        response = _chat_completion(messages, max_output_tokens=settings.max_tokens, temperature=0)
    except OpenAIError as e:
        logger.error("OpenAI text-to-SQL call failed: %s", e)
        raise LLMServiceError(f"Failed to generate SQL from the language model: {e}") from e

    logger.debug("Text-to-SQL response: %s", response)

    return response.choices[0].message.content or ""


async def regenerate_sql_with_error(
    user_question: str,
    schema_prompt: str,
    failed_sql: str,
    db_error: str,
) -> str:
    """
    Self-correction: give the model the SQL it produced plus the PostgreSQL
    error, and ask it to return a corrected query. Used once when the first
    query fails at execution (e.g. wrong column name). Returns raw LLM text.
    """
    system = TEXT_TO_SQL_SYSTEM_PROMPT.format(max_rows=settings.max_rows_returned)
    system += f"\n\n{schema_prompt}"

    messages: list[dict] = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                f"This question was asked:\n{user_question}\n\n"
                f"You generated this SQL, but PostgreSQL rejected it:\n"
                f"```sql\n{failed_sql}\n```\n\n"
                f"PostgreSQL error:\n{db_error}\n\n"
                f"Fix the query using ONLY tables and columns that exist in the schema above. "
                f"If the schema genuinely cannot answer the question, reply with a single line "
                f"starting with 'ERROR:'. Otherwise return ONLY the corrected SQL query."
            ),
        },
    ]

    try:
        response = _chat_completion(messages, max_output_tokens=settings.max_tokens, temperature=0)
    except OpenAIError as e:
        logger.error("OpenAI SQL self-correction call failed: %s", e)
        raise LLMServiceError(f"Failed to regenerate SQL: {e}") from e

    logger.debug("SQL self-correction response: %s", response)

    return response.choices[0].message.content or ""


async def generate_narration(
    user_question: str,
    sql_query: str,
    query_result: list[dict[str, Any]],
    row_count: int,
    truncated: bool = False,
) -> str:
    """
    Call OpenAI to narrate the SQL query results in natural language.

    `truncated` indicates the query produced more rows than were returned,
    so the answer should avoid claiming `row_count` is the exact total.
    """
    # Serialize result — send at most 50 rows to the LLM to keep tokens bounded.
    result_preview = query_result[:50]
    result_json = json.dumps(result_preview, default=str, ensure_ascii=False, indent=2)

    truncation_note = ""
    if truncated:
        truncation_note = (
            f"\n\n(Note: the query returned at least {row_count} rows and the result was "
            f"truncated to {row_count} rows. Do NOT state this as the exact total; say it is "
            f"a partial result and suggest adding filters for an exact count.)"
        )
    elif row_count > 50:
        truncation_note = f"\n\n(Note: Showing first 50 of {row_count} total rows)"

    messages = [
        {"role": "system", "content": NARRATION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"User question: {user_question}\n\n"
                f"SQL query executed:\n```sql\n{sql_query}\n```\n\n"
                f"Query result ({row_count} rows):\n{result_json}"
                f"{truncation_note}\n\n"
                f"Please provide a clear, insightful answer based on this data."
            ),
        },
    ]

    try:
        response = _chat_completion(messages, max_output_tokens=settings.max_tokens)
    except OpenAIError as e:
        logger.error("OpenAI narration call failed: %s", e)
        raise LLMServiceError(f"Failed to narrate the query result: {e}") from e

    logger.debug("Narration response: %s", response)

    return response.choices[0].message.content or ""
