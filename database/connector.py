from __future__ import annotations

import logging
import re
import sqlite3

from config import DB_PATH
from database.access_control import AccessProfile

logger = logging.getLogger("hr_platform.db")

EMPLOYEES_FROM_PATTERN = re.compile(
    r"\bFROM\s+employees\b"
    r"(?:\s+(?:AS\s+)?(?P<alias>[A-Za-z_][A-Za-z0-9_]*))?"
    r"(?=\s+(?:WHERE|GROUP|ORDER|LIMIT|JOIN|INNER|LEFT|RIGHT|FULL|CROSS|UNION|HAVING)\b|\s*$)",
    re.IGNORECASE,
)


class HRDatabase:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _apply_department_scope(
        self, sql: str, access_profile: AccessProfile | None
    ) -> tuple[str, list[str]]:
        """Return (scoped_sql, params) using parameterized queries for department filtering."""
        if access_profile is None:
            return sql, []

        departments = access_profile.allowed_departments
        if not departments:
            return sql, []

        placeholders = ", ".join("?" for _ in departments)
        match = EMPLOYEES_FROM_PATTERN.search(sql)
        if not match:
            raise ValueError("Could not safely apply department scope to the query.")

        alias = match.group("alias") or "employees"
        replacement = (
            f"FROM (SELECT * FROM employees WHERE Department IN ({placeholders})) {alias}"
        )
        scoped = EMPLOYEES_FROM_PATTERN.sub(replacement, sql, count=1)
        return scoped, list(departments)

    def execute_query(self, sql: str, access_profile: AccessProfile | None = None) -> list[dict]:
        """Execute a read-only SQL SELECT query and return results as a list of dicts."""
        upper = sql.strip().upper()
        if not upper.startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed")

        scoped_sql, params = self._apply_department_scope(sql, access_profile)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(scoped_sql, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_table_stats(self, access_profile: AccessProfile | None = None) -> dict:
        """Return access-scoped stats about the employees table."""
        departments = access_profile.allowed_departments if access_profile else []

        with self._get_connection() as conn:
            cursor = conn.cursor()

            if departments:
                placeholders = ", ".join("?" for _ in departments)
                cursor.execute(
                    f"SELECT COUNT(*) as total FROM employees WHERE Department IN ({placeholders})",
                    departments,
                )
                total = cursor.fetchone()["total"]
                cursor.execute(
                    f"SELECT COUNT(*) as attrited FROM employees WHERE Department IN ({placeholders}) AND Attrition='Yes'",
                    departments,
                )
                attrited = cursor.fetchone()["attrited"]
            else:
                cursor.execute("SELECT COUNT(*) as total FROM employees")
                total = cursor.fetchone()["total"]
                cursor.execute("SELECT COUNT(*) as attrited FROM employees WHERE Attrition='Yes'")
                attrited = cursor.fetchone()["attrited"]

            cursor.execute("SELECT name FROM pragma_table_info('employees')")
            columns = [row["name"] for row in cursor.fetchall()]

        return {
            "total_employees": total,
            "attrited_employees": attrited,
            "active_employees": total - attrited,
            "attrition_rate_pct": round(100 * attrited / total, 1) if total else 0,
            "columns": columns,
            "scope_name": access_profile.scope_name if access_profile else "Enterprise",
            "allowed_departments": access_profile.allowed_departments if access_profile else [],
            "allowed_metrics": access_profile.allowed_metrics if access_profile else ["all"],
        }

    def is_connected(self) -> bool:
        try:
            with self._get_connection() as conn:
                conn.execute("SELECT 1 FROM employees LIMIT 1")
            return True
        except Exception:
            return False
