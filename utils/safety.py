"""
SQL safety validation layer.
Blocks any non-SELECT or destructive SQL before it reaches the database.
"""

BLOCKED_KEYWORDS = [
    "DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "TRUNCATE",
    "CREATE", "GRANT", "REVOKE", "ATTACH", "DETACH",
    "--", ";--", "/*", "*/",
    "PRAGMA",  # block schema-altering pragmas
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

    for keyword in BLOCKED_KEYWORDS:
        if keyword in upper:
            return False, f"Blocked keyword detected: '{keyword}'. Only SELECT queries are allowed."

    # Auto-add LIMIT if missing to prevent huge result sets
    if "LIMIT" not in upper:
        stripped = stripped.rstrip(";")
        stripped = f"{stripped} LIMIT {AUTO_LIMIT}"

    return True, stripped
