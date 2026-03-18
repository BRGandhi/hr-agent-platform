from __future__ import annotations

import sqlite3

from config import DB_PATH
from database.access_control import AccessProfile


class HRDatabase:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _apply_department_scope(self, sql: str, access_profile: AccessProfile | None) -> str:
        if access_profile is None:
            return sql

        clause = access_profile.departments_clause()
        if not clause:
            return sql

        return sql.replace(
            "FROM employees",
            f"FROM (SELECT * FROM employees WHERE {clause}) employees",
        )

    def execute_query(self, sql: str, access_profile: AccessProfile | None = None) -> list[dict]:
        """Execute a read-only SQL SELECT query and return results as a list of dicts."""
        upper = sql.strip().upper()
        if not upper.startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed")

        scoped_sql = self._apply_department_scope(sql, access_profile)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(scoped_sql)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_table_stats(self, access_profile: AccessProfile | None = None) -> dict:
        """Return access-scoped stats about the employees table."""
        clause = access_profile.departments_clause() if access_profile else None
        where_clause = f"WHERE {clause}" if clause else ""
        attrition_where = f"WHERE {clause} AND Attrition='Yes'" if clause else "WHERE Attrition='Yes'"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) as total FROM employees {where_clause}")
            total = cursor.fetchone()["total"]
            cursor.execute(f"SELECT COUNT(*) as attrited FROM employees {attrition_where}")
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
