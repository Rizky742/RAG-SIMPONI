"""
LLM Service (OpenAI)
Handles two LLM calls:
  1. Text-to-SQL  : converts user question + schema context → SQL query
  2. Narration    : converts query result → natural language answer
"""

import json
from typing import Any

from openai import OpenAI

from app.config import get_settings

settings = get_settings()

# Lazy singleton — client is created on first use so the module imports
# fine even before the API key is configured.
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


# ── System Prompts ────────────────────────────────────────────────────────────

TEXT_TO_SQL_SYSTEM_PROMPT = """You are an expert PostgreSQL analyst. Your job is to convert natural language questions into precise, optimized SQL SELECT queries.

CRITICAL RULES (MUST FOLLOW STRICTLY):
1. ONLY generate SELECT queries. Never INSERT, UPDATE, DELETE, DROP, or ALTER.
2. ONLY use column names that EXACTLY match the schema below. Do NOT invent or assume column names.
3. Always use explicit table aliases when joining tables.
4. Return ONLY the SQL query — no explanation, no markdown, no preamble.

COLUMN NAME RULES (DO NOT VIOLATE):
- The primary key column is always 'id' (NOT 'product_id', 'order_id', 'user_id', etc.)
- The name column is 'name' (NOT 'product_name', 'order_name', 'user_name', etc.)
- DO NOT use 'product_id', 'product_name', 'order_items', 'unit_price' - these do NOT exist
- Use 'quantity' from order_details, NOT 'qty' or 'quantity_ordered'
- Use 'ordered_at' for order dates, NOT 'order_date' or 'created_at'
- Use 'total_amount', 'net_amount', or 'subtotal_amount' for order totals

QUERY BUILDING RULES:
5. Use LIMIT {max_rows} unless the user explicitly asks for all rows.
6. When filtering text columns, use ILIKE for case-insensitive matching.
7. Always handle NULL values gracefully (COALESCE, IS NOT NULL, etc.).
8. For revenue/sales queries, use orders.total_amount or orders.net_amount.
9. order_details has NO price column - use orders table for financial data.
10. For date filtering on orders, use ordered_at (not created_at).
11. Use proper date/time functions (DATE_TRUNC, EXTRACT, etc.) for temporal analysis.
12. Prefer CTEs (WITH clauses) for complex queries to improve readability.
13. If you cannot generate a valid query with the available tables/columns, say so.

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

    response = _get_client().chat.completions.create(
        model=settings.llm_model,
        max_completion_tokens=settings.max_tokens,
        messages=messages,
    )

    return response.choices[0].message.content or ""


async def generate_narration(
    user_question: str,
    sql_query: str,
    query_result: list[dict[str, Any]],
    row_count: int,
) -> str:
    """
    Call OpenAI to narrate the SQL query results in natural language.
    """
    # Serialize result — truncate if very large
    result_preview = query_result[:50]  # send at most 50 rows to LLM
    result_json = json.dumps(result_preview, default=str, ensure_ascii=False, indent=2)

    truncation_note = ""
    if row_count > 50:
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

    response = _get_client().chat.completions.create(
        model=settings.llm_model,
        max_completion_tokens=settings.max_tokens,
        messages=messages,
    )

    return response.choices[0].message.content or ""
