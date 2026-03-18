"""
Tool executor: bridges model tool requests to actual Python/SQL operations.
"""

from __future__ import annotations

import json

import pandas as pd
import plotly.express as px

from database.access_control import AccessProfile
from database.connector import HRDatabase
from utils.safety import validate_sql


class ToolExecutor:
    def __init__(self, db: HRDatabase):
        self.db = db

    def execute(self, tool_name: str, tool_input: dict, access_profile: AccessProfile | None = None) -> str:
        try:
            if tool_name == "query_hr_database":
                return self._query_database(tool_input, access_profile)
            if tool_name == "calculate_metrics":
                return self._calculate_metrics(tool_input)
            if tool_name == "create_visualization":
                return self._create_visualization(tool_input)
            if tool_name == "get_attrition_insights":
                return self._get_attrition_insights(tool_input, access_profile)
            if tool_name == "generate_standard_report":
                return self._generate_standard_report(tool_input, access_profile)
            return f"Error: Unknown tool '{tool_name}'"
        except Exception as exc:
            return f"Tool execution error: {exc}"

    def _query_database(self, inputs: dict, access_profile: AccessProfile | None) -> str:
        sql = inputs.get("sql_query", "").strip()

        is_safe, result = validate_sql(sql)
        if not is_safe:
            return f"SQL rejected by safety validator: {result}"

        safe_sql = result
        if access_profile:
            allowed, reason = access_profile.is_sql_allowed(safe_sql)
            if not allowed:
                return reason

        rows = self.db.execute_query(safe_sql, access_profile=access_profile)
        if not rows:
            return "Query returned 0 rows."

        return json.dumps(rows, default=str)

    def _calculate_metrics(self, inputs: dict) -> str:
        raw_data = inputs.get("data", "[]")
        operation = inputs.get("operation", "")

        try:
            data = json.loads(raw_data)
        except json.JSONDecodeError:
            return "Error: Could not parse data JSON"

        if not data:
            return "Error: Empty data provided"

        df = pd.DataFrame(data)
        results = {}
        op_lower = operation.lower()

        if "attrition" in op_lower and ("rate" in op_lower or "percent" in op_lower):
            if "Attrition" in df.columns:
                yes = (df["Attrition"] == "Yes").sum()
                total = len(df)
                results["attrition_rate"] = {
                    "attrited": int(yes),
                    "total": total,
                    "rate_pct": round(100 * yes / total, 1) if total > 0 else 0,
                }
        elif "percentage" in op_lower or "breakdown" in op_lower or "distribution" in op_lower:
            for col in df.columns:
                if df[col].dtype == object or df[col].nunique() < 15:
                    counts = df[col].value_counts(normalize=True).mul(100).round(1)
                    results[f"{col}_distribution_pct"] = counts.to_dict()
        else:
            numeric = df.select_dtypes(include="number")
            if not numeric.empty:
                results["summary_stats"] = numeric.describe().round(2).to_dict()

        return json.dumps(results, default=str)

    def _create_visualization(self, inputs: dict) -> str:
        chart_type = inputs.get("chart_type", "bar")
        raw_data = inputs.get("data", "[]")
        x_col = inputs.get("x_column", "")
        y_col = inputs.get("y_column", "")
        title = inputs.get("title", "HR Chart")
        color_col = inputs.get("color_column")

        try:
            data = json.loads(raw_data)
        except json.JSONDecodeError:
            return json.dumps({"error": "Could not parse chart data JSON"})

        if not data:
            return json.dumps({"error": "Empty data - cannot create chart"})

        df = pd.DataFrame(data)
        for col in [x_col, y_col]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="ignore")

        palette = ["#6366F1", "#10B981", "#F59E0B", "#EF4444", "#3B82F6", "#8B5CF6"]

        if chart_type == "bar":
            fig = px.bar(df, x=x_col, y=y_col, title=title, color=color_col, text_auto=True, color_discrete_sequence=palette)
        elif chart_type == "horizontal_bar":
            fig = px.bar(df, x=y_col, y=x_col, orientation="h", title=title, color=color_col, text_auto=True, color_discrete_sequence=palette)
        elif chart_type == "pie":
            fig = px.pie(df, names=x_col, values=y_col, title=title, color_discrete_sequence=palette)
        elif chart_type == "line":
            fig = px.line(df, x=x_col, y=y_col, title=title, color=color_col, markers=True, color_discrete_sequence=palette)
        else:
            fig = px.bar(df, x=x_col, y=y_col, title=title, color=color_col, text_auto=True, color_discrete_sequence=palette)

        fig.update_layout(
            plot_bgcolor="#FFFFFF",
            paper_bgcolor="#FFFFFF",
            font=dict(family="Inter, sans-serif", color="#1E293B"),
            title_x=0,
            margin=dict(t=52, b=40, l=16, r=16),
        )

        return json.dumps({"chart_json": fig.to_json(), "title": title})

    def _get_attrition_insights(self, inputs: dict, access_profile: AccessProfile | None) -> str:
        focus = inputs.get("focus_area", "overall_summary")
        allowed_metrics = set(access_profile.allowed_metrics) if access_profile else {"all"}

        if access_profile and "all" not in allowed_metrics and "attrition" not in allowed_metrics:
            return json.dumps({"error": "Attrition insights are outside your role-based access"})

        if focus == "by_demographics" and access_profile and "all" not in allowed_metrics and "demographics" not in allowed_metrics:
            return json.dumps({"error": "Demographic insights are outside your role-based access"})
        if focus == "by_satisfaction" and access_profile and "all" not in allowed_metrics and "satisfaction" not in allowed_metrics:
            return json.dumps({"error": "Satisfaction insights are outside your role-based access"})
        if focus == "by_compensation" and access_profile and "all" not in allowed_metrics and "compensation" not in allowed_metrics:
            return json.dumps({"error": "Compensation insights are outside your role-based access"})

        queries = {
            "overall_summary": """
                SELECT
                    COUNT(*) as TotalEmployees,
                    SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END) as TotalAttrited,
                    ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1) as AttritionRate_pct
                FROM employees
            """,
            "by_department": """
                SELECT Department,
                    COUNT(*) as Total,
                    SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END) as Attrited,
                    ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1) as AttritionRate_pct
                FROM employees GROUP BY Department ORDER BY AttritionRate_pct DESC
            """,
            "by_job_role": """
                SELECT JobRole,
                    COUNT(*) as Total,
                    SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END) as Attrited,
                    ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1) as AttritionRate_pct
                FROM employees GROUP BY JobRole ORDER BY AttritionRate_pct DESC
            """,
            "by_demographics": """
                SELECT Gender, MaritalStatus,
                    COUNT(*) as Total,
                    ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1) as AttritionRate_pct
                FROM employees GROUP BY Gender, MaritalStatus ORDER BY AttritionRate_pct DESC
            """,
            "by_satisfaction": """
                SELECT JobSatisfaction, EnvironmentSatisfaction, WorkLifeBalance,
                    COUNT(*) as Total,
                    ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1) as AttritionRate_pct
                FROM employees
                GROUP BY JobSatisfaction, EnvironmentSatisfaction, WorkLifeBalance
                ORDER BY AttritionRate_pct DESC LIMIT 20
            """,
            "by_compensation": """
                SELECT
                    CASE
                        WHEN MonthlyIncome < 3000 THEN 'Low (<$3K)'
                        WHEN MonthlyIncome < 6000 THEN 'Mid ($3K-$6K)'
                        WHEN MonthlyIncome < 10000 THEN 'Upper-Mid ($6K-$10K)'
                        ELSE 'High (>$10K)'
                    END as IncomeBand,
                    COUNT(*) as Total,
                    ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1) as AttritionRate_pct
                FROM employees
                GROUP BY IncomeBand ORDER BY AttritionRate_pct DESC
            """,
            "top_risk_factors": """
                SELECT
                    'OverTime=Yes' as RiskFactor,
                    COUNT(*) as AffectedEmployees,
                    ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1) as AttritionRate_pct
                FROM employees WHERE OverTime='Yes'
                ORDER BY AttritionRate_pct DESC
            """,
        }

        sql = queries.get(focus, queries["overall_summary"])
        rows = self.db.execute_query(sql.strip(), access_profile=access_profile)
        return json.dumps({"focus_area": focus, "results": rows}, default=str)

    def _generate_standard_report(self, inputs: dict, access_profile: AccessProfile | None) -> str:
        report_type = inputs.get("report_type", "").strip().lower()
        explanation = inputs.get("explanation", "").strip()
        allowed_metrics = set(access_profile.allowed_metrics) if access_profile else {"all"}

        if report_type == "active_headcount":
            if access_profile and "all" not in allowed_metrics and "headcount" not in allowed_metrics:
                return json.dumps({"error": "Active headcount reports are outside your role-based access"})
            report_name = "Active Headcount Report"
            sql = """
                SELECT
                    'Employee ' || EmployeeNumber AS EmployeeLabel,
                    EmployeeNumber,
                    Department,
                    JobRole,
                    JobLevel,
                    BusinessTravel,
                    OverTime,
                    Attrition
                FROM employees
                WHERE Attrition = 'No'
                ORDER BY Department, JobRole, EmployeeNumber
            """
        elif report_type == "attrition":
            if access_profile and "all" not in allowed_metrics and "attrition" not in allowed_metrics:
                return json.dumps({"error": "Attrition reports are outside your role-based access"})
            report_name = "Attrition Report"
            sql = """
                SELECT
                    'Employee ' || EmployeeNumber AS EmployeeLabel,
                    EmployeeNumber,
                    Department,
                    JobRole,
                    JobLevel,
                    BusinessTravel,
                    OverTime,
                    Attrition
                FROM employees
                WHERE Attrition = 'Yes'
                ORDER BY Department, JobRole, EmployeeNumber
            """
        else:
            return json.dumps({"error": "Unsupported report type"})

        rows = self.db.execute_query(sql.strip(), access_profile=access_profile)
        return json.dumps(
            {
                "report_name": report_name,
                "report_type": report_type,
                "scope_name": access_profile.scope_name if access_profile else "Enterprise",
                "row_count": len(rows),
                "note": (
                    "Employee labels are derived from EmployeeNumber because the demo dataset does not include real employee names."
                ),
                "explanation": explanation,
                "results": rows,
            },
            default=str,
        )
