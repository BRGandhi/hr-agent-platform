from __future__ import annotations

from collections import defaultdict
import logging
import re
import sqlite3

from config import DB_PATH
from database.access_control import AccessProfile

logger = logging.getLogger("hr_platform.db")
TREND_PERIOD_OPTIONS = (3, 6, 12, 24, 36)

EMPLOYEES_FROM_PATTERN = re.compile(
    r"\bFROM\s+(?P<table>employees_trend_current|employees_monthly_history|workforce_monthly_summary|workforce_monthly_events|employees_current|employees)\b"
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

    def _normalize_period_months(self, period_months: int | None, available_months: int) -> int:
        if available_months <= 0:
            return 0
        try:
            requested = int(period_months or 12)
        except (TypeError, ValueError):
            requested = 12
        if requested <= 0:
            requested = 12
        return min(requested, available_months)

    def _available_trend_periods(self, total_months: int) -> list[int]:
        periods = [period for period in TREND_PERIOD_OPTIONS if period <= total_months]
        if not periods and total_months > 0:
            return [total_months]
        return periods

    def _post_process_trend_rows(self, rows: list[dict]) -> list[dict]:
        if not rows:
            return []

        normalized_rows: list[dict] = []
        for row in rows:
            normalized_rows.append(
                {
                    "SnapshotMonth": str(row.get("SnapshotMonth") or ""),
                    "SnapshotYear": int(row.get("SnapshotYear") or 0),
                    "SnapshotMonthNumber": int(row.get("SnapshotMonthNumber") or 0),
                    "Department": str(row.get("Department") or "All"),
                    "Headcount": int(row.get("Headcount") or 0),
                    "StartOfMonthHeadcount": int(row.get("StartOfMonthHeadcount") or 0),
                    "HiresThisMonth": int(row.get("HiresThisMonth") or 0),
                    "ExitsThisMonth": int(row.get("ExitsThisMonth") or 0),
                    "PromotionsThisMonth": int(row.get("PromotionsThisMonth") or 0),
                    "NetChangeThisMonth": int(row.get("NetChangeThisMonth") or 0),
                    "MonthlyHiringRatePct": float(row.get("MonthlyHiringRatePct") or 0),
                    "MonthlyAttritionRatePct": float(row.get("MonthlyAttritionRatePct") or 0),
                    "MonthlyPromotionRatePct": float(row.get("MonthlyPromotionRatePct") or 0),
                    "AverageYearsAtCompany": float(row.get("AverageYearsAtCompany") or 0),
                    "AverageYearsSinceLastPromotion": float(row.get("AverageYearsSinceLastPromotion") or 0),
                    "AverageMonthlyIncome": float(row.get("AverageMonthlyIncome") or 0),
                    "OverTimeSharePct": float(row.get("OverTimeSharePct") or 0),
                    "TenureBand0To1Pct": float(row.get("TenureBand0To1Pct") or 0),
                    "TenureBand2To4Pct": float(row.get("TenureBand2To4Pct") or 0),
                    "TenureBand5To9Pct": float(row.get("TenureBand5To9Pct") or 0),
                    "TenureBand10PlusPct": float(row.get("TenureBand10PlusPct") or 0),
                    "MoMHeadcountChange": int(row.get("MoMHeadcountChange") or 0),
                    "MoMHeadcountChangePct": float(row.get("MoMHeadcountChangePct") or 0),
                    "Rolling12Hires": int(row.get("Rolling12Hires") or 0),
                    "Rolling12Exits": int(row.get("Rolling12Exits") or 0),
                    "Rolling12Promotions": int(row.get("Rolling12Promotions") or 0),
                    "Rolling12HiringRatePct": float(row.get("Rolling12HiringRatePct") or 0),
                    "Rolling12AttritionRatePct": float(row.get("Rolling12AttritionRatePct") or 0),
                    "Rolling12PromotionRatePct": float(row.get("Rolling12PromotionRatePct") or 0),
                    "YoYHeadcountChange": int(row.get("YoYHeadcountChange") or 0),
                    "YoYHeadcountChangePct": float(row.get("YoYHeadcountChangePct") or 0),
                }
            )

        for index, row in enumerate(normalized_rows):
            window = normalized_rows[max(0, index - 11): index + 1]
            avg_headcount = (
                sum(float(item["Headcount"]) for item in window) / len(window)
                if window else 0.0
            )
            row["Rolling12Hires"] = int(sum(item["HiresThisMonth"] for item in window))
            row["Rolling12Exits"] = int(sum(item["ExitsThisMonth"] for item in window))
            row["Rolling12Promotions"] = int(sum(item["PromotionsThisMonth"] for item in window))
            row["Rolling12HiringRatePct"] = round((100.0 * row["Rolling12Hires"] / avg_headcount), 2) if avg_headcount else 0.0
            row["Rolling12AttritionRatePct"] = round((100.0 * row["Rolling12Exits"] / avg_headcount), 2) if avg_headcount else 0.0
            row["Rolling12PromotionRatePct"] = round((100.0 * row["Rolling12Promotions"] / avg_headcount), 2) if avg_headcount else 0.0

            previous = normalized_rows[index - 1] if index > 0 else None
            if previous and previous["Headcount"]:
                row["MoMHeadcountChange"] = int(row["Headcount"] - previous["Headcount"])
                row["MoMHeadcountChangePct"] = round((100.0 * row["MoMHeadcountChange"] / previous["Headcount"]), 2)
            else:
                row["MoMHeadcountChange"] = 0
                row["MoMHeadcountChangePct"] = 0.0

            prior_year = normalized_rows[index - 12] if index >= 12 else None
            if prior_year and prior_year["Headcount"]:
                row["YoYHeadcountChange"] = int(row["Headcount"] - prior_year["Headcount"])
                row["YoYHeadcountChangePct"] = round((100.0 * row["YoYHeadcountChange"] / prior_year["Headcount"]), 2)
            else:
                row["YoYHeadcountChange"] = 0
                row["YoYHeadcountChangePct"] = 0.0

        return normalized_rows

    def _query_scope_trend_rows(self, conn: sqlite3.Connection, access_profile: AccessProfile | None = None) -> list[dict]:
        if not self._table_exists(conn, "workforce_monthly_summary"):
            return []

        departments = access_profile.allowed_departments if access_profile else []
        if not departments:
            rows = conn.execute(
                """
                SELECT *
                FROM workforce_monthly_summary
                WHERE Department = 'All'
                ORDER BY SnapshotMonth
                """
            ).fetchall()
            return self._post_process_trend_rows([dict(row) for row in rows])

        placeholders = ", ".join("?" for _ in departments)
        rows = conn.execute(
            f"""
            SELECT *
            FROM workforce_monthly_summary
            WHERE Department IN ({placeholders})
            ORDER BY SnapshotMonth, Department
            """,
            departments,
        ).fetchall()

        grouped_rows: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            grouped_rows[str(row["SnapshotMonth"])].append(dict(row))

        aggregated_rows: list[dict] = []
        for snapshot_month in sorted(grouped_rows):
            month_rows = grouped_rows[snapshot_month]
            total_headcount = sum(int(row.get("Headcount") or 0) for row in month_rows)
            start_headcount = sum(int(row.get("StartOfMonthHeadcount") or 0) for row in month_rows)
            hires = sum(int(row.get("HiresThisMonth") or 0) for row in month_rows)
            exits = sum(int(row.get("ExitsThisMonth") or 0) for row in month_rows)
            promotions = sum(int(row.get("PromotionsThisMonth") or 0) for row in month_rows)

            def weighted_average(key: str) -> float:
                if total_headcount <= 0:
                    return 0.0
                weighted_total = sum(float(row.get(key) or 0) * int(row.get("Headcount") or 0) for row in month_rows)
                return round(weighted_total / total_headcount, 2)

            template = month_rows[0]
            aggregated_rows.append(
                {
                    "SnapshotMonth": snapshot_month,
                    "SnapshotYear": int(template.get("SnapshotYear") or 0),
                    "SnapshotMonthNumber": int(template.get("SnapshotMonthNumber") or 0),
                    "Department": "All",
                    "Headcount": total_headcount,
                    "StartOfMonthHeadcount": start_headcount,
                    "HiresThisMonth": hires,
                    "ExitsThisMonth": exits,
                    "PromotionsThisMonth": promotions,
                    "NetChangeThisMonth": hires - exits,
                    "MonthlyHiringRatePct": round((100.0 * hires / start_headcount), 2) if start_headcount else 0.0,
                    "MonthlyAttritionRatePct": round((100.0 * exits / start_headcount), 2) if start_headcount else 0.0,
                    "MonthlyPromotionRatePct": round((100.0 * promotions / start_headcount), 2) if start_headcount else 0.0,
                    "AverageYearsAtCompany": weighted_average("AverageYearsAtCompany"),
                    "AverageYearsSinceLastPromotion": weighted_average("AverageYearsSinceLastPromotion"),
                    "AverageMonthlyIncome": weighted_average("AverageMonthlyIncome"),
                    "OverTimeSharePct": weighted_average("OverTimeSharePct"),
                    "TenureBand0To1Pct": weighted_average("TenureBand0To1Pct"),
                    "TenureBand2To4Pct": weighted_average("TenureBand2To4Pct"),
                    "TenureBand5To9Pct": weighted_average("TenureBand5To9Pct"),
                    "TenureBand10PlusPct": weighted_average("TenureBand10PlusPct"),
                    "MoMHeadcountChange": 0,
                    "MoMHeadcountChangePct": 0.0,
                    "Rolling12Hires": 0,
                    "Rolling12Exits": 0,
                    "Rolling12Promotions": 0,
                    "Rolling12HiringRatePct": 0.0,
                    "Rolling12AttritionRatePct": 0.0,
                    "Rolling12PromotionRatePct": 0.0,
                    "YoYHeadcountChange": 0,
                    "YoYHeadcountChangePct": 0.0,
                }
            )

        return self._post_process_trend_rows(aggregated_rows)

    def get_trend_metrics(self, access_profile: AccessProfile | None = None, period_months: int | None = 12) -> dict:
        with self._get_connection() as conn:
            rows = self._query_scope_trend_rows(conn, access_profile)

        if not rows:
            return {
                "available_periods": [],
                "selected_period_months": 0,
                "series": {},
                "latest": {},
                "trend_note": "",
            }

        selected_period = self._normalize_period_months(period_months, len(rows))
        scoped_rows = rows[-selected_period:]
        latest = scoped_rows[-1]
        available_periods = self._available_trend_periods(len(rows))

        return {
            "available_periods": available_periods,
            "selected_period_months": selected_period,
            "latest_month": latest["SnapshotMonth"],
            "period_start_month": scoped_rows[0]["SnapshotMonth"],
            "trend_note": (
                "Monthly trend metrics are simulated from the current workforce baseline."
            ),
            "latest": {
                "headcount": latest["Headcount"],
                "start_of_month_headcount": latest["StartOfMonthHeadcount"],
                "hires_this_month": latest["HiresThisMonth"],
                "exits_this_month": latest["ExitsThisMonth"],
                "promotions_this_month": latest["PromotionsThisMonth"],
                "net_change_this_month": latest["NetChangeThisMonth"],
                "monthly_hiring_rate_pct": latest["MonthlyHiringRatePct"],
                "monthly_attrition_rate_pct": latest["MonthlyAttritionRatePct"],
                "monthly_promotion_rate_pct": latest["MonthlyPromotionRatePct"],
                "rolling12_hiring_rate_pct": latest["Rolling12HiringRatePct"],
                "rolling12_attrition_rate_pct": latest["Rolling12AttritionRatePct"],
                "rolling12_promotion_rate_pct": latest["Rolling12PromotionRatePct"],
                "mom_headcount_change": latest["MoMHeadcountChange"],
                "mom_headcount_change_pct": latest["MoMHeadcountChangePct"],
                "yoy_headcount_change": latest["YoYHeadcountChange"],
                "yoy_headcount_change_pct": latest["YoYHeadcountChangePct"],
                "average_years_at_company": latest["AverageYearsAtCompany"],
                "average_years_since_last_promotion": latest["AverageYearsSinceLastPromotion"],
                "average_monthly_income": latest["AverageMonthlyIncome"],
                "overtime_share_pct": latest["OverTimeSharePct"],
                "tenure_distribution_pct": {
                    "0_1": latest["TenureBand0To1Pct"],
                    "2_4": latest["TenureBand2To4Pct"],
                    "5_9": latest["TenureBand5To9Pct"],
                    "10_plus": latest["TenureBand10PlusPct"],
                },
            },
            "series": {
                "headcount": [
                    {
                        "month": row["SnapshotMonth"],
                        "value": row["Headcount"],
                        "mom_change": row["MoMHeadcountChange"],
                        "mom_change_pct": row["MoMHeadcountChangePct"],
                        "yoy_change": row["YoYHeadcountChange"],
                        "yoy_change_pct": row["YoYHeadcountChangePct"],
                    }
                    for row in scoped_rows
                ],
                "attrition_rate_pct": [
                    {
                        "month": row["SnapshotMonth"],
                        "monthly_value": row["MonthlyAttritionRatePct"],
                        "rolling12_value": row["Rolling12AttritionRatePct"],
                    }
                    for row in scoped_rows
                ],
                "promotion_rate_pct": [
                    {
                        "month": row["SnapshotMonth"],
                        "monthly_value": row["MonthlyPromotionRatePct"],
                        "rolling12_value": row["Rolling12PromotionRatePct"],
                    }
                    for row in scoped_rows
                ],
                "hiring_rate_pct": [
                    {
                        "month": row["SnapshotMonth"],
                        "monthly_value": row["MonthlyHiringRatePct"],
                        "rolling12_value": row["Rolling12HiringRatePct"],
                    }
                    for row in scoped_rows
                ],
                "tenure_distribution_pct": [
                    {
                        "month": row["SnapshotMonth"],
                        "band_0_1": row["TenureBand0To1Pct"],
                        "band_2_4": row["TenureBand2To4Pct"],
                        "band_5_9": row["TenureBand5To9Pct"],
                        "band_10_plus": row["TenureBand10PlusPct"],
                        "average_years_at_company": row["AverageYearsAtCompany"],
                    }
                    for row in scoped_rows
                ],
                "overtime_share_pct": [
                    {
                        "month": row["SnapshotMonth"],
                        "value": row["OverTimeSharePct"],
                    }
                    for row in scoped_rows
                ],
            },
        }

    def get_periodic_report_rows(
        self,
        report_type: str,
        access_profile: AccessProfile | None = None,
        period_months: int | None = 12,
    ) -> tuple[str, list[dict]]:
        with self._get_connection() as conn:
            rows = self._query_scope_trend_rows(conn, access_profile)

        if not rows:
            return "Trend Report", []

        selected_period = self._normalize_period_months(period_months, len(rows))
        scoped_rows = rows[-selected_period:]
        report_type = str(report_type or "").strip().lower()

        if report_type == "workforce_trend":
            report_name = f"Workforce Trend Report | Last {selected_period} Months"
            report_rows = [
                {
                    "SnapshotMonth": row["SnapshotMonth"],
                    "Headcount": row["Headcount"],
                    "Rolling12HiringRatePct": row["Rolling12HiringRatePct"],
                    "Rolling12AttritionRatePct": row["Rolling12AttritionRatePct"],
                    "Rolling12PromotionRatePct": row["Rolling12PromotionRatePct"],
                    "AverageYearsAtCompany": row["AverageYearsAtCompany"],
                    "OverTimeSharePct": row["OverTimeSharePct"],
                    "MoMHeadcountChangePct": row["MoMHeadcountChangePct"],
                    "YoYHeadcountChangePct": row["YoYHeadcountChangePct"],
                }
                for row in scoped_rows
            ]
        elif report_type == "headcount_trend":
            report_name = f"Headcount Trend Report | Last {selected_period} Months"
            report_rows = [
                {
                    "SnapshotMonth": row["SnapshotMonth"],
                    "Headcount": row["Headcount"],
                    "NetChangeThisMonth": row["NetChangeThisMonth"],
                    "MoMHeadcountChange": row["MoMHeadcountChange"],
                    "MoMHeadcountChangePct": row["MoMHeadcountChangePct"],
                    "YoYHeadcountChange": row["YoYHeadcountChange"],
                    "YoYHeadcountChangePct": row["YoYHeadcountChangePct"],
                }
                for row in scoped_rows
            ]
        elif report_type == "attrition_trend":
            report_name = f"Attrition Trend Report | Last {selected_period} Months"
            report_rows = [
                {
                    "SnapshotMonth": row["SnapshotMonth"],
                    "ExitsThisMonth": row["ExitsThisMonth"],
                    "MonthlyAttritionRatePct": row["MonthlyAttritionRatePct"],
                    "Rolling12AttritionRatePct": row["Rolling12AttritionRatePct"],
                    "OverTimeSharePct": row["OverTimeSharePct"],
                    "Headcount": row["Headcount"],
                }
                for row in scoped_rows
            ]
        elif report_type == "promotion_trend":
            report_name = f"Promotion Trend Report | Last {selected_period} Months"
            report_rows = [
                {
                    "SnapshotMonth": row["SnapshotMonth"],
                    "PromotionsThisMonth": row["PromotionsThisMonth"],
                    "MonthlyPromotionRatePct": row["MonthlyPromotionRatePct"],
                    "Rolling12PromotionRatePct": row["Rolling12PromotionRatePct"],
                    "AverageYearsSinceLastPromotion": row["AverageYearsSinceLastPromotion"],
                }
                for row in scoped_rows
            ]
        elif report_type == "tenure_distribution_trend":
            report_name = f"Tenure Distribution Trend Report | Last {selected_period} Months"
            report_rows = [
                {
                    "SnapshotMonth": row["SnapshotMonth"],
                    "AverageYearsAtCompany": row["AverageYearsAtCompany"],
                    "TenureBand0To1Pct": row["TenureBand0To1Pct"],
                    "TenureBand2To4Pct": row["TenureBand2To4Pct"],
                    "TenureBand5To9Pct": row["TenureBand5To9Pct"],
                    "TenureBand10PlusPct": row["TenureBand10PlusPct"],
                }
                for row in scoped_rows
            ]
        else:
            return "", []

        return report_name, report_rows

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

            trend_metrics = self.get_trend_metrics(access_profile=access_profile, period_months=12)
            latest_trend = trend_metrics.get("latest") or {}

        return {
            "total_employees": total,
            "attrited_employees": attrited,
            "active_employees": total - attrited,
            "attrition_rate_pct": round(100 * attrited / total, 1) if total else 0,
            "avg_years_since_last_promotion": float(promotion_stats["avg_years_since_last_promotion"] or 0),
            "avg_salary_hike_pct": float(promotion_stats["avg_salary_hike_pct"] or 0),
            "promoted_last_year_employees": int(promotion_stats["promoted_last_year_employees"] or 0),
            "promotion_stalled_employees": int(promotion_stats["promotion_stalled_employees"] or 0),
            "latest_trend_month": trend_metrics.get("latest_month", ""),
            "available_trend_periods": trend_metrics.get("available_periods", []),
            "selected_trend_period_months": trend_metrics.get("selected_period_months", 0),
            "trend_note": trend_metrics.get("trend_note", ""),
            "trend_series": trend_metrics.get("series", {}),
            "trend_summary": latest_trend,
            "headcount_mom_change": int(latest_trend.get("mom_headcount_change") or 0),
            "headcount_mom_change_pct": float(latest_trend.get("mom_headcount_change_pct") or 0),
            "headcount_yoy_change": int(latest_trend.get("yoy_headcount_change") or 0),
            "headcount_yoy_change_pct": float(latest_trend.get("yoy_headcount_change_pct") or 0),
            "monthly_hiring_rate_pct": float(latest_trend.get("monthly_hiring_rate_pct") or 0),
            "monthly_attrition_rate_pct": float(latest_trend.get("monthly_attrition_rate_pct") or 0),
            "monthly_promotion_rate_pct": float(latest_trend.get("monthly_promotion_rate_pct") or 0),
            "rolling12_hiring_rate_pct": float(latest_trend.get("rolling12_hiring_rate_pct") or 0),
            "rolling12_attrition_rate_pct": float(latest_trend.get("rolling12_attrition_rate_pct") or 0),
            "rolling12_promotion_rate_pct": float(latest_trend.get("rolling12_promotion_rate_pct") or 0),
            "avg_years_at_company": float(latest_trend.get("average_years_at_company") or 0),
            "overtime_share_pct": float(latest_trend.get("overtime_share_pct") or 0),
            "tenure_distribution_pct": latest_trend.get("tenure_distribution_pct", {}),
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
