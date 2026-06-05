"""
SQL Validation & Security Check Layer
Ensures only safe, read-only SELECT queries are executed.
"""

import re
from dataclasses import dataclass


# ── Forbidden SQL patterns (case-insensitive) ────────────────────────────────
FORBIDDEN_PATTERNS = [
    r"\bDROP\b",
    r"\bDELETE\b",
    r"\bTRUNCATE\b",
    r"\bINSERT\b",
    r"\bUPDATE\b",
    r"\bALTER\b",
    r"\bCREATE\b",
    r"\bREPLACE\b",
    r"\bGRANT\b",
    r"\bREVOKE\b",
    r"\bEXECUTE\b",
    r"\bEXEC\b",
    r"\bCALL\b",
    r"\bPG_SLEEP\b",
    r"\bPG_READ_FILE\b",
    r"\bCOPY\b",
    r"--",                      # SQL comments (injection vector)
    r"/\*.*?\*/",               # Block comments
    r";\s*\w",                  # Multiple statements
    r"\bINTO\s+OUTFILE\b",
    r"\bLOAD_FILE\b",
    r"\bUNION\s+ALL\s+SELECT\b",  # Allow only when combined legitimately
]

# Maximum allowed query length
MAX_QUERY_LENGTH = 4000


@dataclass
class ValidationResult:
    is_valid: bool
    cleaned_sql: str
    error: str = ""


def validate_and_sanitize_sql(sql: str) -> ValidationResult:
    """
    Validate that the SQL is a safe, read-only SELECT query.
    Returns a ValidationResult with cleaned SQL or an error message.
    """
    if not sql or not sql.strip():
        return ValidationResult(False, "", "Empty SQL query.")

    # Strip leading/trailing whitespace and trailing semicolons
    cleaned = sql.strip().rstrip(";").strip()

    # Length check
    if len(cleaned) > MAX_QUERY_LENGTH:
        return ValidationResult(
            False, "", f"Query too long ({len(cleaned)} chars). Max: {MAX_QUERY_LENGTH}."
        )

    # Must start with SELECT (allow CTEs: WITH ... SELECT)
    upper = cleaned.upper().lstrip()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        return ValidationResult(
            False, "",
            "Only SELECT queries are allowed. Query must start with SELECT or WITH."
        )

    # Check forbidden patterns
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, cleaned, re.IGNORECASE | re.DOTALL):
            return ValidationResult(
                False, "",
                f"Query contains a forbidden pattern: {pattern}. "
                "Only read-only SELECT queries are permitted."
            )

    # Ensure there's no stacked query via semicolon
    if ";" in cleaned:
        return ValidationResult(
            False, "",
            "Multiple statements detected (semicolon found). Only single queries allowed."
        )

    return ValidationResult(True, cleaned)


def extract_sql_from_llm_response(response_text: str) -> str:
    """
    Extract the SQL query from an LLM response that may contain
    markdown code blocks or explanatory text.
    """
    # Try to extract from ```sql ... ``` block
    sql_block = re.search(r"```sql\s*(.*?)\s*```", response_text, re.DOTALL | re.IGNORECASE)
    if sql_block:
        return sql_block.group(1).strip()

    # Try generic ``` ... ``` block
    code_block = re.search(r"```\s*(.*?)\s*```", response_text, re.DOTALL)
    if code_block:
        return code_block.group(1).strip()

    # Fallback: look for SELECT keyword and take from there
    select_match = re.search(r"((?:WITH|SELECT)\s.*)", response_text, re.DOTALL | re.IGNORECASE)
    if select_match:
        return select_match.group(1).strip()

    return response_text.strip()
