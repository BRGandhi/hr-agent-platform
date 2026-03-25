"""
SQL safety validation layer.
Blocks any non-SELECT or destructive SQL before it reaches the database.
"""

import re

BLOCKED_KEYWORDS = [
    "DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "TRUNCATE",
    "CREATE", "GRANT", "REVOKE", "ATTACH", "DETACH",
    "PRAGMA", "EXEC", "EXECUTE", "VACUUM", "REINDEX",
    "UNION",  # prevent scope bypass via UNION injection
    "INTO",   # block SELECT INTO
    "LOAD_EXTENSION",
]

BLOCKED_PATTERNS = [
    r"--",      # single-line comment
    r";--",
    r"/\*",     # block comment open
    r"\*/",     # block comment close
    r";",       # multiple statements
]

# Max rows returned per query to prevent memory issues
AUTO_LIMIT = 500


def validate_sql(query: str) -> tuple[bool, str]:
    """
    Validate a SQL query for safety.
    Returns (is_safe: bool, message: str).
    If safe, message is the (possibly modified) query with LIMIT added.
    If not safe, message is the reason it was rejected.
    """
    stripped = query.strip()
    upper = stripped.upper()

    if not upper.startswith("SELECT"):
        return False, "Query must start with SELECT. Only read-only queries are allowed."

    # Check for blocked patterns (comments, semicolons)
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, stripped):
            return False, f"Blocked pattern detected: '{pattern}'. Only simple SELECT queries are allowed."

    # Check for blocked keywords (word-boundary matching to reduce false positives)
    for keyword in BLOCKED_KEYWORDS:
        if re.search(rf"\b{keyword}\b", upper):
            return False, f"Blocked keyword detected: '{keyword}'. Only SELECT queries are allowed."

    # Auto-add LIMIT if missing to prevent huge result sets
    if "LIMIT" not in upper:
        stripped = stripped.rstrip(";")
        stripped = f"{stripped} LIMIT {AUTO_LIMIT}"

    return True, stripped
