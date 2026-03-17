"""
Tool executor: bridges Claude's tool requests to actual Python/SQL operations.
Claude says "call tool X with params Y" — this module does the actual work.
"""

import json
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from database.connector import HRDatabase
from utils.safety import validate_sql


class ToolExecutor:
    def __init__(self, db: HRDatabase):
        self.db = db

    def execute(self, tool_name: str, tool_input: dict) -> str:
        """
        Dispatch a tool call to the appropriate handler.
        Returns a string result to send back to Claude.
        """
        try:
            if tool_name == "query_hr_database":
                return self._query_database(tool_input)
            elif tool_name == "calculate_metrics":
                return self._calculate_metrics(tool_input)
            elif tool_name == "create_visualization":
                return self._create_visualization(tool_input)
            elif tool_name == "get_attrition_insights":
                return self._get_attrition_insights(tool_input)
            else:
                return f"Error: Unknown tool '{tool_name}'"
        except Exception as e:
            return f"Tool execution error: {str(e)}"

    # ------------------------------------------------------------------ #
    #  Tool 1: Query HR Database                                           #
    # ------------------------------------------------------------------ #
    def _query_database(self, inputs: dict) -> str:
        sql = inputs.get("sql_query", "").strip()

        is_safe, result = validate_sql(sql)
        if not is_safe:
            return f"SQL rejected by safety validator: {result}"

        safe_sql = result  # validator may have appended LIMIT
        try:
            rows = self.db.execute_query(safe_sql)
        except Exception as e:
            return f"Database error: {str(e)}"

        if not rows:
            return "Query returned 0 rows."

        return json.dumps(rows, default=str)

    # ------------------------------------------------------------------ #
    #  Tool 2: Calculate Metrics                                           #
    # ------------------------------------------------------------------ #
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

        # Attrition rate calculation
        if "attrition" in op_lower and ("rate" in op_lower or "percent" in op_lower):
            if "Attrition" in df.columns:
                for col in df.columns:
                    if col == "Attrition":
                        continue
                    if df[col].nunique() < 20:  # groupable column
                        group = df.groupby(col)["Attrition"].apply(
                            lambda x: round(100 * (x == "Yes").sum() / len(x), 1)
                        ).reset_index()
                        group.columns = [col, "AttritionRate_pct"]
                        results[f"attrition_rate_by_{col}"] = group.to_dict(orient="records")
            if not results:
                yes = (df.get("Attrition", pd.Series()) == "Yes").sum() if "Attrition" in df.columns else 0
                total = len(df)
                results["attrition_rate"] = {
                    "attrited": int(yes),
                    "total": total,
                    "rate_pct": round(100 * yes / total, 1) if total > 0 else 0,
                }

        # Percentage breakdown
        elif "percentage" in op_lower or "breakdown" in op_lower or "distribution" in op_lower:
            for col in df.columns:
                if df[col].dtype == object or df[col].nunique() < 15:
                    counts = df[col].value_counts(normalize=True).mul(100).round(1)
                    results[f"{col}_distribution_pct"] = counts.to_dict()

        # Top N ranking
        elif "top" in op_lower or "rank" in op_lower:
            numeric_cols = df.select_dtypes(include="number").columns.tolist()
            if numeric_cols:
                sort_col = numeric_cols[-1]
                top = df.nlargest(min(10, len(df)), sort_col)
                results["top_ranked"] = top.to_dict(orient="records")

        # Summary statistics (default fallback)
        else:
            numeric = df.select_dtypes(include="number")
            if not numeric.empty:
                results["summary_stats"] = numeric.describe().round(2).to_dict()
            categorical = df.select_dtypes(include="object")
            for col in categorical.columns[:3]:
                results[f"{col}_value_counts"] = df[col].value_counts().head(10).to_dict()

        return json.dumps(results, default=str)

    # ------------------------------------------------------------------ #
    #  Tool 3: Create Visualization                                        #
    # ------------------------------------------------------------------ #
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
            return json.dumps({"error": "Empty data — cannot create chart"})

        df = pd.DataFrame(data)

        # Convert numeric strings to numbers
        for col in [x_col, y_col]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="ignore")

        try:
            if chart_type == "bar":
                fig = px.bar(df, x=x_col, y=y_col, title=title,
                             color=color_col, text_auto=True,
                             color_discrete_sequence=px.colors.qualitative.Set2)
            elif chart_type == "horizontal_bar":
                fig = px.bar(df, x=y_col, y=x_col, orientation="h", title=title,
                             color=color_col, text_auto=True,
                             color_discrete_sequence=px.colors.qualitative.Set2)
            elif chart_type == "pie":
                fig = px.pie(df, names=x_col, values=y_col, title=title,
                             color_discrete_sequence=px.colors.qualitative.Set2)
            elif chart_type == "histogram":
                fig = px.histogram(df, x=x_col, title=title,
                                   color=color_col,
                                   color_discrete_sequence=px.colors.qualitative.Set2)
            elif chart_type == "scatter":
                fig = px.scatter(df, x=x_col, y=y_col, title=title,
                                 color=color_col, hover_data=df.columns.tolist(),
                                 color_discrete_sequence=px.colors.qualitative.Set2)
            elif chart_type == "line":
                fig = px.line(df, x=x_col, y=y_col, title=title,
                              color=color_col, markers=True,
                              color_discrete_sequence=px.colors.qualitative.Set2)
            elif chart_type == "box":
                fig = px.box(df, x=x_col, y=y_col, title=title,
                             color=color_col,
                             color_discrete_sequence=px.colors.qualitative.Set2)
            else:
                fig = px.bar(df, x=x_col, y=y_col, title=title)

            fig.update_layout(
                plot_bgcolor="white",
                paper_bgcolor="white",
                font=dict(family="Inter, sans-serif"),
                title_font_size=16,
            )

            chart_json = fig.to_json()
            return json.dumps({"chart_json": chart_json, "title": title})

        except Exception as e:
            return json.dumps({"error": f"Chart creation failed: {str(e)}"})

    # ------------------------------------------------------------------ #
    #  Tool 4: Get Attrition Insights                                      #
    # ------------------------------------------------------------------ #
    def _get_attrition_insights(self, inputs: dict) -> str:
        focus = inputs.get("focus_area", "overall_summary")

        queries = {
            "overall_summary": """
                SELECT
                    COUNT(*) as TotalEmployees,
                    SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END) as TotalAttrited,
                    ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1) as AttritionRate_pct,
                    ROUND(AVG(Age),1) as AvgAge,
                    ROUND(AVG(MonthlyIncome),0) as AvgMonthlyIncome,
                    ROUND(AVG(YearsAtCompany),1) as AvgTenureYears,
                    SUM(CASE WHEN OverTime='Yes' THEN 1 ELSE 0 END) as OverTimeWorkers
                FROM employees
            """,
            "by_department": """
                SELECT Department,
                    COUNT(*) as Total,
                    SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END) as Attrited,
                    ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1) as AttritionRate_pct,
                    ROUND(AVG(MonthlyIncome),0) as AvgIncome
                FROM employees GROUP BY Department ORDER BY AttritionRate_pct DESC
            """,
            "by_job_role": """
                SELECT JobRole,
                    COUNT(*) as Total,
                    SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END) as Attrited,
                    ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1) as AttritionRate_pct,
                    ROUND(AVG(MonthlyIncome),0) as AvgIncome,
                    ROUND(AVG(JobSatisfaction),1) as AvgJobSatisfaction
                FROM employees GROUP BY JobRole ORDER BY AttritionRate_pct DESC
            """,
            "by_demographics": """
                SELECT Gender, MaritalStatus,
                    COUNT(*) as Total,
                    ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1) as AttritionRate_pct,
                    ROUND(AVG(Age),1) as AvgAge
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
                    ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1) as AttritionRate_pct,
                    ROUND(AVG(MonthlyIncome),0) as AvgIncome
                FROM employees
                GROUP BY IncomeBand ORDER BY AttritionRate_pct DESC
            """,
            "top_risk_factors": """
                SELECT
                    'OverTime=Yes' as RiskFactor,
                    COUNT(*) as AffectedEmployees,
                    ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1) as AttritionRate_pct
                FROM employees WHERE OverTime='Yes'
                UNION ALL
                SELECT 'SingleMaritalStatus', COUNT(*),
                    ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1)
                FROM employees WHERE MaritalStatus='Single'
                UNION ALL
                SELECT 'LowJobSatisfaction(1)', COUNT(*),
                    ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1)
                FROM employees WHERE JobSatisfaction=1
                UNION ALL
                SELECT 'LowEnvironmentSatisfaction(1)', COUNT(*),
                    ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1)
                FROM employees WHERE EnvironmentSatisfaction=1
                UNION ALL
                SELECT 'LowWorkLifeBalance(1)', COUNT(*),
                    ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1)
                FROM employees WHERE WorkLifeBalance=1
                UNION ALL
                SELECT 'FrequentTraveler', COUNT(*),
                    ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1)
                FROM employees WHERE BusinessTravel='Travel_Frequently'
                ORDER BY AttritionRate_pct DESC
            """,
        }

        sql = queries.get(focus, queries["overall_summary"])
        try:
            rows = self.db.execute_query(sql.strip())
            return json.dumps({"focus_area": focus, "results": rows}, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)})
