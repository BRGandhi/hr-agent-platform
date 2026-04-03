from __future__ import annotations

import logging
import re
import sqlite3

from config import DB_PATH
from database.access_control import AccessProfile

logger = logging.getLogger("hr_platform.db")

EMPLOYEES_FROM_PATTERN = re.compile(
    r"\bFROM\s+(?P<table>employees_current|employees)\b"
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

    def _table_exists(self, conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE name = ?
              AND type IN ('table', 'view')
            LIMIT 1
            """,
            (table_name,),
        ).fetchone()
        return bool(row)

    def _table_columns(self, conn: sqlite3.Connection, table_name: str) -> list[str]:
        cursor = conn.execute(f"SELECT name FROM pragma_table_info('{table_name}')")
        return [row["name"] for row in cursor.fetchall()]

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

        table_name = match.group("table") or "employees"
        alias = match.group("alias") or table_name
        replacement = (
            f"FROM (SELECT * FROM {table_name} WHERE Department IN ({placeholders})) {alias}"
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
        """Return access-scoped stats about the latest current snapshot."""
        departments = access_profile.allowed_departments if access_profile else []

        with self._get_connection() as conn:
            cursor = conn.cursor()
            has_current_view = self._table_exists(conn, "employees_current")
            current_table = "employees_current" if has_current_view else "employees"
            panel_table = "employees" if self._table_exists(conn, "employees") else current_table
            current_columns = self._table_columns(conn, current_table)
            panel_columns = set(self._table_columns(conn, panel_table))
            current_column_set = set(current_columns)
            current_snapshot_condition = ""
            if not has_current_view and "IsCurrentSnapshot" in current_column_set:
                current_snapshot_condition = "IsCurrentSnapshot = 1"

            def where_clause(*conditions: str, include_current_snapshot: bool = True) -> tuple[str, list[str]]:
                clauses = [condition for condition in conditions if condition]
                params: list[str] = []
                if include_current_snapshot and current_snapshot_condition:
                    clauses.append(current_snapshot_condition)
                if departments:
                    placeholders = ", ".join("?" for _ in departments)
                    clauses.append(f"Department IN ({placeholders})")
                    params.extend(departments)
                sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
                return sql, params

            total_where, total_params = where_clause()
            cursor.execute(f"SELECT COUNT(*) as total FROM {current_table}{total_where}", total_params)
            total = cursor.fetchone()["total"]

            attrited_where, attrited_params = where_clause("Attrition = 'Yes'")
            cursor.execute(
                f"SELECT COUNT(*) as attrited FROM {current_table}{attrited_where}",
                attrited_params,
            )
            attrited = cursor.fetchone()["attrited"]

            promotion_stats = {
                "avg_years_since_last_promotion": 0.0,
                "avg_salary_hike_pct": 0.0,
                "promoted_last_year_employees": 0,
                "promotion_stalled_employees": 0,
            }

            if {"YearsSinceLastPromotion", "PercentSalaryHike"} <= current_column_set:
                current_promo_where, current_promo_params = where_clause()
                cursor.execute(
                    f"""
                    SELECT
                        ROUND(AVG(YearsSinceLastPromotion), 1) as avg_years_since_last_promotion,
                        ROUND(AVG(PercentSalaryHike), 1) as avg_salary_hike_pct,
                        SUM(CASE WHEN YearsSinceLastPromotion >= 5 THEN 1 ELSE 0 END) as promotion_stalled_employees
                    FROM {current_table}{current_promo_where}
                    """,
                    current_promo_params,
                )
                promotion_row = cursor.fetchone()
                promotion_stats["avg_years_since_last_promotion"] = float(
                    promotion_row["avg_years_since_last_promotion"] or 0
                )
                promotion_stats["avg_salary_hike_pct"] = float(
                    promotion_row["avg_salary_hike_pct"] or 0
                )
                promotion_stats["promotion_stalled_employees"] = int(
                    promotion_row["promotion_stalled_employees"] or 0
                )

            if {"PromotedThisMonth", "EmployeeNumber", "PercentSalaryHike"} <= panel_columns:
                recent_promotions_where, recent_promotions_params = where_clause(
                    "PromotedThisMonth = 1",
                    include_current_snapshot=False,
                )
                cursor.execute(
                    f"SELECT COUNT(DISTINCT EmployeeNumber) as promoted_last_year_employees, "
                    f"ROUND(AVG(PercentSalaryHike), 1) as avg_salary_hike_pct "
                    f"FROM {panel_table}{recent_promotions_where}",
                    recent_promotions_params,
                )
                promotion_row = cursor.fetchone()
                promotion_stats["promoted_last_year_employees"] = int(
                    promotion_row["promoted_last_year_employees"] or 0
                )
                if "avg_salary_hike_pct" in promotion_row.keys():
                    promotion_stats["avg_salary_hike_pct"] = float(
                        promotion_row["avg_salary_hike_pct"] or 0
                    )
            elif "YearsSinceLastPromotion" in current_column_set:
                fallback_promotions_where, fallback_promotions_params = where_clause("YearsSinceLastPromotion < 1")
                cursor.execute(
                    f"SELECT COUNT(*) as promoted_last_year_employees "
                    f"FROM {current_table}{fallback_promotions_where}",
                    fallback_promotions_params,
                )
                promotion_stats["promoted_last_year_employees"] = int(
                    cursor.fetchone()["promoted_last_year_employees"] or 0
                )

        return {
            "total_employees": total,
            "attrited_employees": attrited,
            "active_employees": total - attrited,
            "attrition_rate_pct": round(100 * attrited / total, 1) if total else 0,
            "avg_years_since_last_promotion": float(promotion_stats["avg_years_since_last_promotion"] or 0),
            "avg_salary_hike_pct": float(promotion_stats["avg_salary_hike_pct"] or 0),
            "promoted_last_year_employees": int(promotion_stats["promoted_last_year_employees"] or 0),
            "promotion_stalled_employees": int(promotion_stats["promotion_stalled_employees"] or 0),
            "columns": current_columns,
            "scope_name": access_profile.scope_name if access_profile else "Enterprise",
            "allowed_departments": access_profile.allowed_departments if access_profile else [],
            "allowed_metrics": access_profile.allowed_metrics if access_profile else ["all"],
        }

    def is_connected(self) -> bool:
        try:
            with self._get_connection() as conn:
                source_table = "employees_current" if self._table_exists(conn, "employees_current") else "employees"
                conn.execute(f"SELECT 1 FROM {source_table} LIMIT 1")
            return True
        except Exception:
            return False
