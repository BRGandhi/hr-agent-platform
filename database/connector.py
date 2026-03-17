import sqlite3
import json
from config import DB_PATH


class HRDatabase:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def execute_query(self, sql: str) -> list[dict]:
        """Execute a read-only SQL SELECT query and return results as a list of dicts."""
        upper = sql.strip().upper()
        if not upper.startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_table_stats(self) -> dict:
        """Return basic stats about the employees table."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
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
            "attrition_rate_pct": round(100 * attrited / total, 1),
            "columns": columns,
        }

    def is_connected(self) -> bool:
        """Check if the database file exists and is accessible."""
        try:
            with self._get_connection() as conn:
                conn.execute("SELECT 1 FROM employees LIMIT 1")
            return True
        except Exception:
            return False
