"""
SQL Validation & Security Check Layer
Ensures only safe, read-only SELECT queries are executed.
"""

import re
from dataclasses import dataclass


# ── Forbidden SQL patterns (case-insensitive) ────────────────────────────────
# These target write/DDL/admin operations and known injection vectors. Read-only
# constructs like UNION are intentionally NOT blocked — they cannot mutate data
# and are legitimately useful for combining SELECT results.
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
    r"\bINTO\s+OUTFILE\b",
    r"\bINTO\s+DUMPFILE\b",
    r"\bLOAD_FILE\b",
    # SELECT ... INTO <table> creates a new table — block it.
    r"\bSELECT\b.*\bINTO\b\s+[a-zA-Z_]",
]

# Maximum allowed query length
MAX_QUERY_LENGTH = 4000


@dataclass
class ValidationResult:
    is_valid: bool
    cleaned_sql: str
    error: str = ""


def _has_comment_outside_strings(sql: str) -> bool:
    """Return True if the SQL contains a `--` or `/* */` comment that is NOT
    inside a single-quoted string literal. Scans char-by-char tracking quote
    state so quoted values containing `--` or `/*` are not flagged."""
    in_string = False
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if in_string:
            if ch == "'":
                # Handle escaped quote ('') inside a string literal.
                if i + 1 < n and sql[i + 1] == "'":
                    i += 2
                    continue
                in_string = False
            i += 1
            continue
        # Not inside a string
        if ch == "'":
            in_string = True
        elif ch == "-" and i + 1 < n and sql[i + 1] == "-":
            return True
        elif ch == "/" and i + 1 < n and sql[i + 1] == "*":
            return True
        i += 1
    return False


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

    # Reject SQL comments only when they appear OUTSIDE of string literals, so
    # legitimate values like '--' or 'a/*b' inside quotes don't trigger a false
    # positive while real injection comments (-- , /* */) are still blocked.
    if _has_comment_outside_strings(cleaned):
        return ValidationResult(
            False, "",
            "SQL comments are not allowed (potential injection vector)."
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
