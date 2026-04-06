"""
Tool executor: bridges model tool requests to actual Python/SQL operations.
"""

from __future__ import annotations

import json
import logging
import re

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from database.access_control import AccessProfile
from database.connector import HRDatabase
from database.context_store import ContextStore
from utils.safety import validate_sql

logger = logging.getLogger("hr_platform.tools")

# Chart color palette
CHART_PALETTE = ["#0B5CAB", "#1E88E5", "#3AA0D8", "#0F766E", "#E67E22", "#C0392B", "#6B7280"]
HEATMAP_COLOR_SCALE = [
    [0.0, "#EFF6FF"],
    [0.22, "#BFDBFE"],
    [0.48, "#60A5FA"],
    [0.74, "#2563EB"],
    [1.0, "#0B3A75"],
]
MEASURE_KEYWORDS = (
    "count",
    "total",
    "rate",
    "pct",
    "percent",
    "avg",
    "average",
    "mean",
    "score",
    "income",
    "salary",
    "pay",
    "tenure",
    "years",
    "monthly",
    "daily",
    "hourly",
    "employees",
    "attrited",
)
IDENTIFIER_KEYWORDS = ("id", "number", "employee", "label")
TEMPORAL_KEYWORDS = ("date", "month", "quarter", "year", "week")
CATEGORY_PRIORITY = (
    "department",
    "jobrole",
    "attrition",
    "gender",
    "maritalstatus",
    "businesstravel",
    "overtime",
    "educationfield",
    "joblevel",
    "worklifebalance",
    "jobsatisfaction",
    "environmentsatisfaction",
    "performance",
    "stockoptionlevel",
)
PERCENT_VALUE_KEYWORDS = ("rate", "pct", "percent", "share")
CURRENCY_VALUE_KEYWORDS = ("income", "salary", "pay", "cost", "amount", "compensation")
YEARS_VALUE_KEYWORDS = ("tenure", "years", "promotion", "experience")
COUNT_VALUE_KEYWORDS = ("count", "total", "employees", "employeecount", "headcount", "attrited", "affected")


class ToolExecutor:
    def __init__(self, db: HRDatabase, context_store: ContextStore | None = None):
        self.db = db
        self.context_store = context_store

    def execute(
        self,
        tool_name: str,
        tool_input: dict,
        access_profile: AccessProfile | None = None,
        table_context: dict | None = None,
    ) -> str:
        try:
            if tool_name == "search_past_chats":
                return self._search_past_chats(tool_input, access_profile)
            if tool_name == "search_context_documents":
                return self._search_context_documents(tool_input, access_profile)
            if tool_name == "query_hr_database":
                return self._query_database(tool_input, access_profile)
            if tool_name == "calculate_metrics":
                return self._calculate_metrics(tool_input)
            if tool_name == "create_visualization":
                return self._create_visualization(tool_input, table_context=table_context)
            if tool_name == "suggest_visualizations":
                return self._suggest_visualizations(tool_input, table_context=table_context)
            if tool_name == "get_attrition_insights":
                return self._get_attrition_insights(tool_input, access_profile)
            if tool_name == "generate_standard_report":
                return self._generate_standard_report(tool_input, access_profile)
            return json.dumps({"error": f"Unknown tool '{tool_name}'"})
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            logger.warning("Tool %s input error: %s", tool_name, exc)
            return json.dumps({"error": f"Invalid input: {exc}"})
        except pd.errors.ParserError as exc:
            logger.warning("Tool %s data parsing error: %s", tool_name, exc)
            return json.dumps({"error": "Could not parse the provided data."})
        except Exception as exc:
            logger.exception("Unexpected error in tool %s", tool_name)
            return json.dumps({"error": "An unexpected error occurred while executing the tool."})

    def _search_past_chats(self, inputs: dict, access_profile: AccessProfile | None) -> str:
        if not self.context_store:
            return json.dumps({"error": "Conversation history is not available."})
        if access_profile is None:
            return json.dumps({"error": "User access context is required for past-chat retrieval."})

        query = str(inputs.get("query", "") or "").strip()
        if not query:
            return json.dumps({"error": "A search query is required."})

        max_items = max(1, min(int(inputs.get("max_items", 3) or 3), 4))
        only_helpful = bool(inputs.get("only_helpful", False))
        items = self.context_store.search_memories(
            access_profile.email,
            query,
            limit=max_items,
            min_feedback=1 if only_helpful else None,
            require_strong_match=True,
        )
        filtered_items = []
        for item in items:
            allowed, _ = access_profile.can_access_question(str(item.get("question", "")))
            if allowed:
                filtered_items.append(item)

        return json.dumps(
            {
                "query": query,
                "memories": [
                    {
                        "memory_id": item.get("memory_id"),
                        "question": item.get("question", ""),
                        "response_snippet": str(item.get("response", ""))[:260],
                        "created_at": item.get("created_at"),
                        "feedback_score": item.get("feedback_score", 0),
                    }
                    for item in filtered_items
                ],
            },
            default=str,
        )

    def _search_context_documents(self, inputs: dict, access_profile: AccessProfile | None) -> str:
        if not self.context_store:
            return json.dumps({"error": "Context documents are not available."})

        query = str(inputs.get("query", "") or "").strip()
        if not query:
            return json.dumps({"error": "A search query is required."})

        max_items = max(1, min(int(inputs.get("max_items", 3) or 3), 4))
        allowed_tags = access_profile.allowed_doc_tags if access_profile else ["all"]
        items = self.context_store.search_documents(query, allowed_tags, limit=max_items)

        return json.dumps(
            {
                "query": query,
                "documents": [
                    {
                        "title": item.get("title", ""),
                        "tags": item.get("tags", []),
                        "content_snippet": str(item.get("content", ""))[:280],
                        "created_at": item.get("created_at"),
                    }
                    for item in items
                ],
            },
            default=str,
        )

    def _query_database(self, inputs: dict, access_profile: AccessProfile | None) -> str:
        sql = inputs.get("sql_query", "").strip()

        is_safe, result = validate_sql(sql)
        if not is_safe:
            return json.dumps({"error": f"SQL rejected: {result}"})

        safe_sql = result
        if access_profile:
            allowed, reason = access_profile.is_sql_allowed(safe_sql)
            if not allowed:
                return json.dumps({"error": reason})

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
            return json.dumps({"error": "Could not parse data JSON"})

        if not data:
            return json.dumps({"error": "Empty data provided"})

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

    def _create_visualization(self, inputs: dict, table_context: dict | None = None) -> str:
        chart_type = str(inputs.get("chart_type", "bar") or "bar").strip().lower()
        x_col = str(inputs.get("x_column", "") or "").strip()
        y_col = str(inputs.get("y_column", "") or "").strip()
        title = str(inputs.get("title", "") or "").strip() or "HR Chart"
        color_col = str(inputs.get("color_column", "") or "").strip() or None
        question = str(inputs.get("question", "") or "").strip()

        rows, resolved_title_or_error = self._resolve_visualization_rows(inputs, table_context)
        if rows is None:
            return json.dumps({"error": resolved_title_or_error})

        df = self._prepare_visualization_dataframe(rows)
        analysis_context = question or title or resolved_title_or_error

        if chart_type == "heatmap":
            if not x_col:
                x_col = self._choose_dimension_column(df, analysis_context)
            if not y_col:
                y_col = self._choose_dimension_column(df, analysis_context, exclude={x_col} if x_col else None)
            if not color_col:
                color_col = self._choose_metric_column(df, analysis_context)
        elif not x_col and chart_type == "histogram":
            x_col = self._choose_metric_column(df, analysis_context)
        elif not x_col:
            x_col = self._choose_dimension_column(df, analysis_context)

        if not y_col and chart_type in {"bar", "horizontal_bar", "stacked_bar", "pie", "donut", "line", "area", "box"}:
            y_col = self._choose_metric_column(df, analysis_context)

        if not x_col and chart_type not in {"scatter"}:
            return json.dumps({"error": "Visualization requires a valid x column or the latest table context."})
        if chart_type == "heatmap" and (not y_col or not color_col):
            return json.dumps({"error": "Heatmaps require x, y, and color value columns."})
        if chart_type not in {"histogram", "pie", "donut", "heatmap"} and chart_type not in {"scatter"} and not y_col:
            return json.dumps({"error": "Visualization requires a valid y column for this chart type."})

        try:
            fig = self._build_visualization_figure(
                df=df,
                chart_type=chart_type,
                x_col=x_col,
                y_col=y_col,
                title=title or resolved_title_or_error,
                color_col=color_col,
            )
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

        return json.dumps({"chart_json": fig.to_json(), "title": title or resolved_title_or_error})

    def _suggest_visualizations(self, inputs: dict, table_context: dict | None = None) -> str:
        rows, source_title_or_error = self._resolve_visualization_rows(inputs, table_context)
        if rows is None:
            return json.dumps({"error": source_title_or_error})

        source_title = str(inputs.get("title", "") or "").strip() or source_title_or_error or "Latest Table"
        question = str(inputs.get("question", "") or "").strip()
        max_options = max(2, min(int(inputs.get("max_options", 3) or 3), 4))
        df = self._prepare_visualization_dataframe(rows)
        analysis_context = question or source_title
        question_intents = self._visual_intents(analysis_context)
        options: list[dict] = []
        seen_signatures: set[tuple] = set()

        def add_option(
            chart_type: str,
            chart_df: pd.DataFrame,
            x_col: str,
            y_col: str,
            title: str,
            reason: str,
            *,
            color_col: str | None = None,
            score: float = 0.0,
            business_question: str = "",
            best_for: str = "",
            watch_out: str = "",
        ) -> None:
            required_columns = {column for column in [x_col, y_col, color_col] if column}
            if chart_df.empty or not required_columns.issubset(set(chart_df.columns)):
                return

            signature = (chart_type, tuple(chart_df.columns), x_col, y_col, color_col, title)
            if signature in seen_signatures:
                return

            try:
                fig = self._build_visualization_figure(
                    df=chart_df.copy(),
                    chart_type=chart_type,
                    x_col=x_col,
                    y_col=y_col,
                    title=title,
                    color_col=color_col,
                )
            except ValueError:
                return

            seen_signatures.add(signature)
            options.append(
                {
                    "chart_type": chart_type,
                    "title": title,
                    "reason": reason,
                    "score": score,
                    "business_question": business_question or self._business_question_for_chart(chart_type, x_col, y_col, color_col),
                    "best_for": best_for or self._best_for_chart(chart_type),
                    "watch_out": watch_out or self._watch_out_for_chart(chart_type),
                    "chart_json": fig.to_json(),
                }
            )

        primary_dimension = self._choose_dimension_column(df, analysis_context)
        secondary_dimension = self._choose_dimension_column(df, analysis_context, exclude={primary_dimension} if primary_dimension else None)
        primary_metric = self._choose_metric_column(df, analysis_context)
        secondary_metric = self._choose_metric_column(df, analysis_context, exclude={primary_metric} if primary_metric else None)

        if primary_dimension and primary_metric:
            chart_df = self._prepare_category_metric_frame(df, primary_dimension, primary_metric)
            if self._is_datetime_column(chart_df, primary_dimension):
                add_option(
                    "line",
                    chart_df,
                    primary_dimension,
                    primary_metric,
                    f"{self._humanize_label(primary_metric)} over {self._humanize_label(primary_dimension)}",
                    "Best for showing how the workforce metric moves across an ordered time sequence.",
                    score=9.3 if question_intents["trend"] else 8.8,
                    business_question=f"How is {self._humanize_label(primary_metric).lower()} changing over {self._humanize_label(primary_dimension).lower()}?",
                    best_for="Trend reading and inflection points across an ordered timeline.",
                    watch_out="Less effective when the x-axis is not truly chronological.",
                )
                add_option(
                    "area",
                    chart_df,
                    primary_dimension,
                    primary_metric,
                    f"Cumulative view of {self._humanize_label(primary_metric)} over {self._humanize_label(primary_dimension)}",
                    "Adds visual weight when the overall volume matters alongside the directional trend.",
                    score=7.5 if question_intents["trend"] else 7.0,
                    business_question=f"How much total {self._humanize_label(primary_metric).lower()} is building up over {self._humanize_label(primary_dimension).lower()}?",
                    best_for="Showing scale plus direction in one view.",
                    watch_out="Can make exact comparisons harder than a line chart.",
                )
            else:
                preferred_chart = "horizontal_bar" if self._prefer_horizontal_bars(chart_df, primary_dimension) else "bar"
                add_option(
                    preferred_chart,
                    chart_df,
                    primary_dimension,
                    primary_metric,
                    f"{self._humanize_label(primary_metric)} by {self._humanize_label(primary_dimension)}",
                    "Best for comparing categories quickly and making the ranking immediately obvious.",
                    score=9.4 if question_intents["ranking"] else 8.9,
                    business_question=f"Which {self._humanize_label(primary_dimension).lower()} categories have the highest {self._humanize_label(primary_metric).lower()}?",
                    best_for="Fast ranking, comparison, and executive readout.",
                    watch_out="Composition within each bar is hidden unless you add a split dimension.",
                )
                add_option(
                    "bar" if preferred_chart == "horizontal_bar" else "horizontal_bar",
                    chart_df,
                    primary_dimension,
                    primary_metric,
                    f"{self._humanize_label(primary_metric)} by {self._humanize_label(primary_dimension)}",
                    "A strong alternative when you want the same comparison in a different visual orientation.",
                    score=7.4,
                    business_question=f"How do {self._humanize_label(primary_dimension).lower()} categories compare on {self._humanize_label(primary_metric).lower()}?",
                    best_for="The same core story in a different reading direction.",
                    watch_out="Usually secondary to the highest-scoring rank chart.",
                )

                if secondary_dimension:
                    stacked_df = self._prepare_stacked_frame(df, primary_dimension, secondary_dimension, primary_metric)
                    if not stacked_df.empty:
                        add_option(
                            "stacked_bar",
                            stacked_df,
                            primary_dimension,
                            primary_metric,
                            f"{self._humanize_label(primary_metric)} by {self._humanize_label(primary_dimension)} split by {self._humanize_label(secondary_dimension)}",
                            "Useful when you want both the total and the composition of each category in one view.",
                            color_col=secondary_dimension,
                            score=8.0 if question_intents["composition"] else 7.2,
                            business_question=(
                                f"How does {self._humanize_label(primary_metric).lower()} split by "
                                f"{self._humanize_label(secondary_dimension).lower()} within each {self._humanize_label(primary_dimension).lower()}?"
                            ),
                            best_for="Showing totals and mix together.",
                            watch_out="Harder to compare segment sizes across many categories.",
                        )

                    heatmap_df = self._prepare_heatmap_frame(df, primary_dimension, secondary_dimension, primary_metric)
                    if not heatmap_df.empty:
                        add_option(
                            "heatmap",
                            heatmap_df,
                            primary_dimension,
                            secondary_dimension,
                            f"{self._humanize_label(primary_metric)} heatmap across {self._humanize_label(primary_dimension)} and {self._humanize_label(secondary_dimension)}",
                            "Strong for spotting the highest and lowest combinations across two categorical dimensions at a glance.",
                            color_col=primary_metric,
                            score=8.8 if question_intents["composition"] or question_intents["ranking"] else 8.1,
                            business_question=(
                                f"Where are the highest and lowest {self._humanize_label(primary_metric).lower()} combinations "
                                f"across {self._humanize_label(primary_dimension).lower()} and {self._humanize_label(secondary_dimension).lower()}?"
                            ),
                            best_for="Matrix-style hotspot detection across two dimensions.",
                            watch_out="Less precise than bars when exact ranking between close values matters.",
                        )

                unique_categories = chart_df[primary_dimension].nunique(dropna=True)
                if 2 <= unique_categories <= 6:
                    add_option(
                        "donut",
                        chart_df,
                        primary_dimension,
                        primary_metric,
                        f"Share of {self._humanize_label(primary_metric)} by {self._humanize_label(primary_dimension)}",
                        "Works well for a small set of categories when relative share is the main story.",
                        score=7.2 if question_intents["composition"] else 6.5,
                        business_question=f"What share of {self._humanize_label(primary_metric).lower()} comes from each {self._humanize_label(primary_dimension).lower()} category?",
                        best_for="High-level share of mix for a small number of groups.",
                        watch_out="Not ideal for precise comparisons or longer category labels.",
                    )
        elif primary_metric and secondary_metric:
            scatter_df = self._limit_rows(df[[primary_metric, secondary_metric]].dropna(), max_rows=250)
            add_option(
                "scatter",
                scatter_df,
                primary_metric,
                secondary_metric,
                f"{self._humanize_label(secondary_metric)} vs {self._humanize_label(primary_metric)}",
                "Best for checking the relationship and spread between two numeric measures.",
                score=8.7 if question_intents["relationship"] else 7.6,
                business_question=(
                    f"How are {self._humanize_label(primary_metric).lower()} and "
                    f"{self._humanize_label(secondary_metric).lower()} related?"
                ),
                best_for="Correlation, spread, clustering, and outliers.",
                watch_out="Less intuitive for non-technical audiences if the relationship is weak.",
            )
            add_option(
                "histogram",
                df[[primary_metric]].dropna(),
                primary_metric,
                primary_metric,
                f"Distribution of {self._humanize_label(primary_metric)}",
                "Helps show concentration, skew, and outliers in a single metric.",
                score=6.9 if question_intents["distribution"] else 6.1,
                business_question=f"How is {self._humanize_label(primary_metric).lower()} distributed across the workforce?",
                best_for="Understanding concentration and skew.",
                watch_out="Does not show the relationship between two metrics.",
            )
        elif primary_metric:
            add_option(
                "histogram",
                df[[primary_metric]].dropna(),
                primary_metric,
                primary_metric,
                f"Distribution of {self._humanize_label(primary_metric)}",
                "Shows whether values cluster tightly or spread widely across the workforce.",
                score=7.7 if question_intents["distribution"] else 6.8,
                business_question=f"How is {self._humanize_label(primary_metric).lower()} distributed across employees or groups?",
                best_for="Distribution shape, spread, and outlier detection.",
                watch_out="Not ideal when the main decision is category ranking.",
            )
            if primary_dimension:
                add_option(
                    "box",
                    self._build_box_frame(df, primary_dimension, primary_metric),
                    primary_dimension,
                    primary_metric,
                    f"{self._humanize_label(primary_metric)} spread by {self._humanize_label(primary_dimension)}",
                    "Strong choice when you need category-level spread rather than just averages.",
                    score=8.1 if question_intents["distribution"] else 7.3,
                    business_question=(
                        f"How does the spread of {self._humanize_label(primary_metric).lower()} differ by "
                        f"{self._humanize_label(primary_dimension).lower()}?"
                    ),
                    best_for="Comparing spread, median, and outliers across groups.",
                    watch_out="Less intuitive than bars for simple average comparisons.",
                )
        else:
            count_dimension = primary_dimension or self._choose_count_dimension(df, question)
            if count_dimension:
                count_metric = "EmployeeCount"
                count_df = self._aggregate_counts(df, count_dimension, count_metric)
                preferred_chart = "horizontal_bar" if self._prefer_horizontal_bars(count_df, count_dimension) else "bar"
                add_option(
                    preferred_chart,
                    count_df,
                    count_dimension,
                    count_metric,
                    f"Employee count by {self._humanize_label(count_dimension)}",
                    "Best baseline view for roster-style tables because it turns rows into an immediately readable ranking.",
                    score=8.7,
                    business_question=f"Which {self._humanize_label(count_dimension).lower()} categories have the highest employee count?",
                    best_for="Clean ranking on roster-style or raw employee tables.",
                    watch_out="Does not show proportional mix across a second dimension.",
                )

                share_dimension = self._choose_share_dimension(df, question, exclude={count_dimension})
                if share_dimension:
                    share_df = self._aggregate_counts(df, share_dimension, count_metric)
                    chart_type = "donut" if share_df[share_dimension].nunique(dropna=True) <= 7 else "bar"
                    add_option(
                        chart_type,
                        share_df,
                        share_dimension,
                        count_metric,
                        f"Employee mix by {self._humanize_label(share_dimension)}",
                        "Useful for showing the overall composition of the table rather than the rank order.",
                        score=7.1 if chart_type == "donut" else 6.8,
                        business_question=f"How is the workforce mix distributed across {self._humanize_label(share_dimension).lower()}?",
                        best_for="Workforce composition and mix.",
                        watch_out="Exact comparisons become harder as categories increase.",
                    )

                if secondary_dimension and secondary_dimension != count_dimension:
                    secondary_df = self._aggregate_counts(df, secondary_dimension, count_metric)
                    add_option(
                        "bar",
                        secondary_df,
                        secondary_dimension,
                        count_metric,
                        f"Employee count by {self._humanize_label(secondary_dimension)}",
                        "Offers a second lens on the same roster so the user can compare different breakdowns.",
                        score=6.5,
                        business_question=f"How does employee count differ by {self._humanize_label(secondary_dimension).lower()}?",
                        best_for="A second categorical lens on the same roster.",
                        watch_out="Usually secondary to the strongest primary ranking view.",
                    )

        if not options:
            return json.dumps({"error": "The current table does not contain enough structure to suggest a visualization."})

        ranked_options = sorted(options, key=lambda item: item.get("score", 0), reverse=True)[:max_options]
        for index, option in enumerate(ranked_options, start=1):
            option["id"] = f"option_{index}"
            option.pop("score", None)

        return json.dumps(
            {
                "title": f"Visualization options for {source_title}",
                "source_title": source_title,
                "recommended_option_id": ranked_options[0]["id"],
                "options": ranked_options,
            }
        )

    def _resolve_visualization_rows(self, inputs: dict, table_context: dict | None) -> tuple[list[dict] | None, str]:
        raw_data = inputs.get("data")
        title = str(inputs.get("title", "") or "").strip()

        if isinstance(raw_data, list):
            rows = raw_data
        elif isinstance(raw_data, str) and raw_data.strip():
            try:
                rows = json.loads(raw_data)
            except json.JSONDecodeError:
                return None, "Could not parse chart data JSON"
        elif table_context and table_context.get("rows"):
            rows = table_context["rows"]
            title = title or str(table_context.get("title", "") or "").strip()
        else:
            return None, "No table data was provided. Use the latest generated table or pass data explicitly."

        if not isinstance(rows, list):
            return None, "Visualization data must be a JSON array of objects."
        if not rows:
            return None, "Empty data - cannot create chart"

        return rows, title or "Latest Table"

    def _prepare_visualization_dataframe(self, rows: list[dict]) -> pd.DataFrame:
        df = pd.DataFrame(rows).copy()
        if df.empty:
            return df

        for column in df.columns:
            series = df[column]
            if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_datetime64_any_dtype(series):
                continue

            non_null = series.notna().sum()
            if non_null == 0:
                continue

            numeric = pd.to_numeric(series, errors="coerce")
            if numeric.notna().sum() >= max(3, int(non_null * 0.8)):
                df[column] = numeric
                continue

            if self._looks_temporal(column):
                parsed = pd.to_datetime(series, errors="coerce")
                if parsed.notna().sum() >= max(2, int(non_null * 0.6)):
                    df[column] = parsed

        return df

    def _build_visualization_figure(
        self,
        df: pd.DataFrame,
        chart_type: str,
        x_col: str,
        y_col: str,
        title: str,
        color_col: str | None = None,
    ):
        if df.empty:
            raise ValueError("The visualization dataset is empty.")

        if chart_type != "histogram" and x_col and x_col not in df.columns:
            raise ValueError(f"Column '{x_col}' is not available in the table.")
        if chart_type not in {"histogram", "pie", "donut", "heatmap"} and y_col and y_col not in df.columns:
            raise ValueError(f"Column '{y_col}' is not available in the table.")
        if chart_type == "histogram" and x_col not in df.columns:
            raise ValueError("Histogram requires a valid x column.")
        if chart_type in {"pie", "donut"} and (x_col not in df.columns or y_col not in df.columns):
            raise ValueError("Pie and donut charts require both a category column and a value column.")
        if chart_type == "scatter" and (x_col not in df.columns or y_col not in df.columns):
            raise ValueError("Scatter plots require two numeric columns.")
        if chart_type == "heatmap" and (x_col not in df.columns or y_col not in df.columns or not color_col or color_col not in df.columns):
            raise ValueError("Heatmaps require x, y, and color value columns.")
        if color_col and color_col not in df.columns:
            color_col = None

        chart_df = df.copy()
        if chart_type in {"bar", "horizontal_bar", "stacked_bar", "pie", "donut", "line", "area"}:
            required_cols = [col for col in [x_col, y_col, color_col] if col]
            chart_df = chart_df[required_cols].dropna()
        elif chart_type == "scatter":
            chart_df = chart_df[[x_col, y_col] + ([color_col] if color_col else [])].dropna()
        elif chart_type == "box":
            chart_df = chart_df[[x_col, y_col]].dropna()
        elif chart_type == "histogram":
            chart_df = chart_df[[x_col]].dropna()
        elif chart_type == "heatmap":
            chart_df = chart_df[[x_col, y_col, color_col]].dropna()

        if chart_df.empty:
            raise ValueError("The selected columns do not contain enough data to plot.")

        if chart_type in {"bar", "horizontal_bar", "stacked_bar"}:
            if self._is_datetime_column(chart_df, x_col):
                chart_df = chart_df.sort_values(x_col)
            else:
                chart_df = chart_df.sort_values(y_col, ascending=False)
                chart_df = self._limit_chart_categories(chart_df, x_col, y_col)

        if chart_type == "bar":
            fig = px.bar(
                chart_df,
                x=x_col,
                y=y_col,
                title=title,
                color=color_col,
                text_auto=True,
                color_discrete_sequence=CHART_PALETTE,
            )
        elif chart_type == "horizontal_bar":
            fig = px.bar(
                chart_df,
                x=y_col,
                y=x_col,
                orientation="h",
                title=title,
                color=color_col,
                text_auto=True,
                color_discrete_sequence=CHART_PALETTE,
            )
        elif chart_type == "stacked_bar":
            fig = px.bar(
                chart_df,
                x=x_col,
                y=y_col,
                color=color_col,
                title=title,
                text_auto=True,
                color_discrete_sequence=CHART_PALETTE,
            )
            fig.update_layout(barmode="stack")
        elif chart_type == "pie":
            fig = px.pie(
                self._limit_chart_categories(chart_df, x_col, y_col, max_categories=7),
                names=x_col,
                values=y_col,
                title=title,
                color_discrete_sequence=CHART_PALETTE,
            )
        elif chart_type == "donut":
            fig = px.pie(
                self._limit_chart_categories(chart_df, x_col, y_col, max_categories=7),
                names=x_col,
                values=y_col,
                title=title,
                hole=0.52,
                color_discrete_sequence=CHART_PALETTE,
            )
        elif chart_type == "histogram":
            fig = px.histogram(
                chart_df,
                x=x_col,
                title=title,
                color_discrete_sequence=CHART_PALETTE,
                nbins=min(max(len(chart_df) // 4, 8), 24),
            )
        elif chart_type == "scatter":
            fig = px.scatter(
                chart_df,
                x=x_col,
                y=y_col,
                color=color_col,
                title=title,
                color_discrete_sequence=CHART_PALETTE,
            )
        elif chart_type == "line":
            fig = px.line(
                chart_df.sort_values(x_col),
                x=x_col,
                y=y_col,
                color=color_col,
                title=title,
                markers=True,
                color_discrete_sequence=CHART_PALETTE,
            )
        elif chart_type == "area":
            fig = px.area(
                chart_df.sort_values(x_col),
                x=x_col,
                y=y_col,
                color=color_col,
                title=title,
                color_discrete_sequence=CHART_PALETTE,
            )
        elif chart_type == "box":
            fig = px.box(
                chart_df,
                x=x_col,
                y=y_col,
                title=title,
                color=color_col,
                color_discrete_sequence=CHART_PALETTE,
                points="outliers",
            )
        elif chart_type == "heatmap":
            frame = self._prepare_heatmap_frame(chart_df, x_col, y_col, color_col)
            if frame.empty:
                raise ValueError("The selected columns do not contain enough structure for a heatmap.")
            x_order = list(dict.fromkeys(frame[x_col].tolist()))
            y_order = list(dict.fromkeys(frame[y_col].tolist()))
            pivot = frame.pivot_table(index=y_col, columns=x_col, values=color_col, aggfunc="mean")
            pivot = pivot.reindex(
                index=[value for value in y_order if value in pivot.index],
                columns=[value for value in x_order if value in pivot.columns],
            )
            fig = go.Figure(
                data=go.Heatmap(
                    z=pivot.values,
                    x=list(pivot.columns),
                    y=list(pivot.index),
                    colorscale=HEATMAP_COLOR_SCALE,
                    hoverongaps=False,
                    colorbar=dict(title=self._humanize_label(color_col)),
                )
            )
            fig.update_layout(title=title)
        else:
            raise ValueError(f"Unsupported chart type '{chart_type}'.")

        self._style_figure(fig, chart_type, x_col=x_col, y_col=y_col, color_col=color_col, chart_df=chart_df)
        return fig

    def _style_figure(
        self,
        fig,
        chart_type: str,
        *,
        x_col: str = "",
        y_col: str = "",
        color_col: str | None = None,
        chart_df: pd.DataFrame | None = None,
    ) -> None:
        fig.update_layout(
            paper_bgcolor="rgba(255,255,255,0)",
            plot_bgcolor="#F8FBFF",
            font=dict(family="Inter, sans-serif", size=13, color="#334155"),
            title=dict(x=0.02, xanchor="left", font=dict(size=20, color="#0F172A")),
            margin=dict(t=72, b=56, l=56, r=24),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                x=0,
                bgcolor="rgba(255,255,255,0.75)",
            ),
            hoverlabel=dict(bgcolor="#FFFFFF", bordercolor="#CBD5E1", font=dict(color="#0F172A")),
            uniformtext_minsize=10,
            uniformtext_mode="hide",
        )
        fig.update_xaxes(
            showgrid=False,
            zeroline=False,
            linecolor="#CBD5E1",
            tickfont=dict(color="#475569"),
            title_font=dict(color="#1E293B"),
        )
        fig.update_yaxes(
            showgrid=True,
            gridcolor="rgba(148,163,184,0.18)",
            zeroline=False,
            tickfont=dict(color="#475569"),
            title_font=dict(color="#1E293B"),
        )
        fig.update_traces(marker_line_width=1.2, marker_line_color="rgba(255,255,255,0.9)", selector=dict(type="bar"))
        fig.update_traces(opacity=0.94, selector=dict(type="histogram"))
        fig.update_traces(line=dict(width=3), marker=dict(size=8), selector=dict(type="scatter"))

        x_label = self._humanize_label(x_col)
        y_label = self._humanize_label(y_col)

        if chart_type in {"line", "area"}:
            fig.update_layout(hovermode="x unified")

        if chart_type == "horizontal_bar":
            metric_profile = self._metric_profile(y_col, chart_df[y_col] if chart_df is not None and y_col in chart_df.columns else None)
            fig.update_xaxes(title_text=y_label)
            fig.update_yaxes(title_text=x_label, automargin=True)
            self._apply_numeric_axis_format(fig, "x", metric_profile)
            fig.update_traces(
                texttemplate=self._plotly_value_token(metric_profile, "x"),
                textposition="outside",
                cliponaxis=False,
                hovertemplate=(
                    f"{x_label}: %{{y}}<br>"
                    f"{y_label}: {self._plotly_value_token(metric_profile, 'x')}<extra></extra>"
                ),
                selector=dict(type="bar"),
            )
        elif chart_type in {"bar", "stacked_bar", "line", "area", "box"}:
            metric_profile = self._metric_profile(y_col, chart_df[y_col] if chart_df is not None and y_col in chart_df.columns else None)
            fig.update_xaxes(title_text=x_label, automargin=True)
            fig.update_yaxes(title_text=y_label)
            self._apply_numeric_axis_format(fig, "y", metric_profile)
            if chart_type in {"bar", "stacked_bar"}:
                textposition = "outside" if chart_type == "bar" and chart_df is not None and len(chart_df) <= 10 else "auto"
                fig.update_traces(
                    texttemplate=self._plotly_value_token(metric_profile, "y"),
                    textposition=textposition,
                    cliponaxis=False,
                    hovertemplate=(
                        f"{x_label}: %{{x}}<br>"
                        f"{y_label}: {self._plotly_value_token(metric_profile, 'y')}<extra></extra>"
                    ),
                    selector=dict(type="bar"),
                )
            elif chart_type in {"line", "area"}:
                fig.update_traces(
                    hovertemplate=(
                        f"{x_label}: %{{x}}<br>"
                        f"{y_label}: {self._plotly_value_token(metric_profile, 'y')}<extra></extra>"
                    )
                )
            elif chart_type == "box":
                fig.update_traces(
                    boxmean=True,
                    hovertemplate=(
                        f"{x_label}: %{{x}}<br>"
                        f"{y_label}: {self._plotly_value_token(metric_profile, 'y')}<extra></extra>"
                    )
                )
        elif chart_type == "scatter":
            x_profile = self._metric_profile(x_col, chart_df[x_col] if chart_df is not None and x_col in chart_df.columns else None)
            y_profile = self._metric_profile(y_col, chart_df[y_col] if chart_df is not None and y_col in chart_df.columns else None)
            fig.update_xaxes(title_text=x_label)
            fig.update_yaxes(title_text=y_label)
            self._apply_numeric_axis_format(fig, "x", x_profile)
            self._apply_numeric_axis_format(fig, "y", y_profile)
            fig.update_traces(
                hovertemplate=(
                    f"{x_label}: {self._plotly_value_token(x_profile, 'x')}<br>"
                    f"{y_label}: {self._plotly_value_token(y_profile, 'y')}<extra></extra>"
                )
            )
        elif chart_type == "histogram":
            metric_profile = self._metric_profile(x_col, chart_df[x_col] if chart_df is not None and x_col in chart_df.columns else None)
            fig.update_xaxes(title_text=x_label)
            fig.update_yaxes(title_text="Employees")
            self._apply_numeric_axis_format(fig, "x", metric_profile)
            fig.update_traces(
                hovertemplate=(
                    f"{x_label}: {self._plotly_value_token(metric_profile, 'x')}<br>"
                    "Employees: %{y:,.0f}<extra></extra>"
                )
            )
        elif chart_type in {"pie", "donut"}:
            metric_profile = self._metric_profile(y_col, chart_df[y_col] if chart_df is not None and y_col in chart_df.columns else None)
            label_count = chart_df[x_col].nunique(dropna=True) if chart_df is not None and x_col in chart_df.columns else 0
            fig.update_traces(
                textposition="inside",
                textinfo="percent+label" if label_count <= 5 else "percent",
                hovertemplate=(
                    f"{x_label}: %{{label}}<br>"
                    f"{y_label}: {self._plotly_value_token(metric_profile, 'value')}<br>"
                    "Share: %{percent}<extra></extra>"
                ),
            )
            fig.update_layout(showlegend=True)
        elif chart_type == "heatmap":
            metric_profile = self._metric_profile(color_col or "", chart_df[color_col] if chart_df is not None and color_col and color_col in chart_df.columns else None)
            fig.update_xaxes(title_text=x_label, showgrid=False)
            fig.update_yaxes(title_text=y_label, showgrid=False, automargin=True)
            fig.update_traces(
                xgap=2,
                ygap=2,
                texttemplate=self._plotly_value_token(metric_profile, "z"),
                hovertemplate=(
                    f"{x_label}: %{{x}}<br>"
                    f"{y_label}: %{{y}}<br>"
                    f"{self._humanize_label(color_col or '')}: {self._plotly_value_token(metric_profile, 'z')}<extra></extra>"
                ),
                selector=dict(type="heatmap"),
            )

    def _metric_profile(self, column_name: str, series: pd.Series | None = None) -> dict[str, str | int]:
        lowered = str(column_name or "").lower()
        if any(keyword in lowered for keyword in PERCENT_VALUE_KEYWORDS):
            return {"kind": "percent", "precision": 1, "tickprefix": "", "ticksuffix": "%"}
        if any(keyword in lowered for keyword in CURRENCY_VALUE_KEYWORDS):
            return {"kind": "currency", "precision": 0, "tickprefix": "$", "ticksuffix": ""}
        if any(keyword in lowered for keyword in YEARS_VALUE_KEYWORDS):
            return {"kind": "years", "precision": 1, "tickprefix": "", "ticksuffix": " yrs"}
        if any(keyword in lowered for keyword in COUNT_VALUE_KEYWORDS):
            return {"kind": "count", "precision": 0, "tickprefix": "", "ticksuffix": ""}

        precision = 1
        if series is not None:
            try:
                numeric = pd.to_numeric(series.dropna(), errors="coerce")
                if not numeric.empty and (numeric % 1 == 0).all():
                    precision = 0
            except (TypeError, ValueError):
                precision = 1
        return {"kind": "number", "precision": precision, "tickprefix": "", "ticksuffix": ""}

    def _plotly_value_token(self, profile: dict[str, str | int], token: str) -> str:
        precision = int(profile.get("precision", 1) or 0)
        format_spec = f",.{precision}f"
        prefix = str(profile.get("tickprefix", "") or "")
        suffix = str(profile.get("ticksuffix", "") or "")
        return f"{prefix}%{{{token}:{format_spec}}}{suffix}"

    def _apply_numeric_axis_format(self, fig, axis: str, profile: dict[str, str | int]) -> None:
        update = {
            "tickformat": f",.{int(profile.get('precision', 1) or 0)}f",
            "tickprefix": str(profile.get("tickprefix", "") or ""),
            "ticksuffix": str(profile.get("ticksuffix", "") or ""),
            "separatethousands": True,
        }
        if axis == "x":
            fig.update_xaxes(**update)
        else:
            fig.update_yaxes(**update)

    def _humanize_label(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
        text = text.replace("_", " ")
        replacements = {
            "pct": "rate",
            "avg": "average",
            "num": "number",
        }
        parts = [replacements.get(part.lower(), part) for part in text.split()]
        return " ".join(parts).strip().title()

    def _prepare_heatmap_frame(self, df: pd.DataFrame, x_col: str, y_col: str, value_col: str) -> pd.DataFrame:
        frame = df[[x_col, y_col, value_col]].dropna().copy()
        if frame.empty:
            return frame
        if frame[x_col].nunique(dropna=True) > 12 or frame[y_col].nunique(dropna=True) > 8:
            return pd.DataFrame()
        frame[x_col] = frame[x_col].astype(str)
        frame[y_col] = frame[y_col].astype(str)
        aggregation = self._aggregation_method_for_metric(value_col)
        return (
            frame.groupby([x_col, y_col], dropna=False, sort=False)[value_col]
            .agg(aggregation)
            .reset_index()
        )

    def _aggregation_method_for_metric(self, value_col: str) -> str:
        lowered = str(value_col or "").lower()
        if any(keyword in lowered for keyword in COUNT_VALUE_KEYWORDS):
            return "sum"
        return "mean"

    def _visual_intents(self, question: str) -> dict[str, bool]:
        lowered = str(question or "").lower()
        return {
            "trend": any(token in lowered for token in ("trend", "over time", "timeline", "month", "quarter", "year")),
            "distribution": any(token in lowered for token in ("distribution", "spread", "range", "outlier", "variance")),
            "relationship": any(token in lowered for token in ("relationship", "correlation", "versus", "vs", "against")),
            "composition": any(token in lowered for token in ("share", "mix", "composition", "split", "breakdown")),
            "ranking": any(token in lowered for token in ("top", "highest", "lowest", "rank", "compare", "leaders", "laggards")),
        }

    def _business_question_for_chart(self, chart_type: str, x_col: str, y_col: str, color_col: str | None = None) -> str:
        x_label = self._humanize_label(x_col).lower()
        y_label = self._humanize_label(y_col).lower()
        color_label = self._humanize_label(color_col or "").lower()
        if chart_type in {"bar", "horizontal_bar"}:
            return f"Which {x_label} categories have the highest {y_label}?"
        if chart_type == "stacked_bar":
            return f"How does {y_label} split by {color_label} within each {x_label}?"
        if chart_type in {"pie", "donut"}:
            return f"What share of {y_label} comes from each {x_label} category?"
        if chart_type == "line":
            return f"How is {y_label} changing over {x_label}?"
        if chart_type == "area":
            return f"How much total {y_label} is building up over {x_label}?"
        if chart_type == "scatter":
            return f"How are {x_label} and {y_label} related?"
        if chart_type == "histogram":
            return f"How is {x_label} distributed?"
        if chart_type == "box":
            return f"How does the spread of {y_label} differ by {x_label}?"
        if chart_type == "heatmap":
            return f"Where are the highest and lowest {color_label} combinations across {x_label} and {y_label}?"
        return "What is the clearest way to view this workforce pattern?"

    def _best_for_chart(self, chart_type: str) -> str:
        mapping = {
            "bar": "Fast ranking and straightforward category comparison.",
            "horizontal_bar": "Readable ranking when labels are longer or there are more categories.",
            "stacked_bar": "Showing total volume and mix in the same view.",
            "pie": "High-level share of mix with a very small number of categories.",
            "donut": "Executive-friendly share of mix for a small set of groups.",
            "line": "Trend direction and inflection points over time.",
            "area": "Trend plus magnitude in one view.",
            "scatter": "Relationship, clustering, and outlier detection between two measures.",
            "histogram": "Distribution shape, concentration, and skew.",
            "box": "Spread, median, and outlier comparison across groups.",
            "heatmap": "Hotspot detection across two dimensions.",
        }
        return mapping.get(chart_type, "Understanding the main workforce pattern quickly.")

    def _watch_out_for_chart(self, chart_type: str) -> str:
        mapping = {
            "bar": "Composition within categories stays hidden.",
            "horizontal_bar": "Secondary once label length is no longer a problem.",
            "stacked_bar": "Segment-to-segment comparison can get hard in dense charts.",
            "pie": "Precise comparisons become difficult once there are many slices.",
            "donut": "Not ideal for exact rank-order comparison.",
            "line": "Only use when the x-axis has a real order.",
            "area": "Can obscure exact comparisons between nearby values.",
            "scatter": "Less intuitive when the relationship is weak or noisy.",
            "histogram": "Does not explain which categories drive the pattern.",
            "box": "More analytical than narrative for some business audiences.",
            "heatmap": "Less precise than bars when exact ranking matters most.",
        }
        return mapping.get(chart_type, "Use the chart that answers the decision question most directly.")

    def _prepare_category_metric_frame(self, df: pd.DataFrame, category_col: str, metric_col: str) -> pd.DataFrame:
        frame = df[[category_col, metric_col]].dropna().copy()
        if frame.empty:
            return frame
        if self._is_datetime_column(frame, category_col):
            return frame.sort_values(category_col)
        frame[category_col] = frame[category_col].astype(str)
        frame = frame.sort_values(metric_col, ascending=False)
        return self._limit_chart_categories(frame, category_col, metric_col)

    def _prepare_stacked_frame(self, df: pd.DataFrame, x_col: str, color_col: str, y_col: str) -> pd.DataFrame:
        frame = df[[x_col, color_col, y_col]].dropna().copy()
        if frame.empty:
            return frame
        if frame[x_col].nunique(dropna=True) > 12 or frame[color_col].nunique(dropna=True) > 6:
            return pd.DataFrame()
        frame[x_col] = frame[x_col].astype(str)
        frame[color_col] = frame[color_col].astype(str)
        return frame.sort_values([x_col, y_col], ascending=[True, False])

    def _build_box_frame(self, df: pd.DataFrame, x_col: str, y_col: str) -> pd.DataFrame:
        if not y_col or y_col not in df.columns:
            return pd.DataFrame()
        if x_col and x_col in df.columns:
            unique_values = df[x_col].dropna().nunique()
            if 2 <= unique_values <= 10:
                return self._limit_rows(df[[x_col, y_col]].dropna(), max_rows=400)
        frame = self._limit_rows(df[[y_col]].dropna(), max_rows=400)
        if frame.empty:
            return frame
        frame.insert(0, "Distribution", "All employees")
        return frame

    def _aggregate_counts(self, df: pd.DataFrame, category_col: str, count_col: str) -> pd.DataFrame:
        frame = df[[category_col]].copy()
        frame[category_col] = frame[category_col].fillna("Unknown").astype(str)
        aggregated = (
            frame.groupby(category_col, dropna=False)
            .size()
            .reset_index(name=count_col)
            .sort_values(count_col, ascending=False)
        )
        return self._limit_chart_categories(aggregated, category_col, count_col)

    def _limit_chart_categories(
        self,
        df: pd.DataFrame,
        category_col: str,
        value_col: str,
        max_categories: int = 12,
    ) -> pd.DataFrame:
        if df.empty or len(df) <= max_categories:
            return df

        trimmed = df.head(max_categories).copy()
        if pd.api.types.is_numeric_dtype(df[value_col]):
            remainder = df.iloc[max_categories:][value_col].sum()
            if remainder > 0:
                other_row = {category_col: "Other", value_col: remainder}
                for column in df.columns:
                    if column not in other_row:
                        other_row[column] = "Other"
                trimmed = pd.concat([trimmed, pd.DataFrame([other_row])], ignore_index=True)
        return trimmed

    def _limit_rows(self, df: pd.DataFrame, max_rows: int) -> pd.DataFrame:
        if len(df) <= max_rows:
            return df
        return df.head(max_rows).copy()

    def _choose_dimension_column(self, df: pd.DataFrame, question: str, exclude: set[str] | None = None) -> str:
        exclude = exclude or set()
        candidates = [column for column in self._category_like_columns(df) if column not in exclude]
        if not candidates:
            return ""

        question_tokens = self._question_tokens(question)

        def score(column: str) -> float:
            series = df[column]
            unique_values = series.dropna().nunique()
            score_value = 0.0
            lowered = column.lower()
            if 2 <= unique_values <= 8:
                score_value += 5
            elif unique_values <= 15:
                score_value += 3
            elif unique_values <= 25:
                score_value += 1
            else:
                score_value -= 4

            for priority, keyword in enumerate(CATEGORY_PRIORITY):
                if keyword in lowered:
                    score_value += max(0.5, 5 - (priority * 0.35))

            if self._looks_identifier(column):
                score_value -= 6
            if unique_values == len(series.dropna()) and not self._is_datetime_column(df, column):
                score_value -= 2
            score_value += self._token_match_score(lowered, question_tokens)
            return score_value

        return max(candidates, key=score)

    def _choose_count_dimension(self, df: pd.DataFrame, question: str) -> str:
        return self._choose_dimension_column(df, question)

    def _choose_share_dimension(self, df: pd.DataFrame, question: str, exclude: set[str] | None = None) -> str:
        exclude = exclude or set()
        candidates = []
        for column in self._category_like_columns(df):
            if column in exclude:
                continue
            unique_values = df[column].dropna().nunique()
            if 2 <= unique_values <= 8 and not self._looks_identifier(column):
                candidates.append(column)
        if not candidates:
            return ""
        question_tokens = self._question_tokens(question)
        return max(
            candidates,
            key=lambda column: (
                self._token_match_score(column.lower(), question_tokens)
                + max(0, 8 - df[column].dropna().nunique())
                + sum(2 for keyword in CATEGORY_PRIORITY if keyword in column.lower())
            ),
        )

    def _choose_metric_column(self, df: pd.DataFrame, question: str, exclude: set[str] | None = None) -> str:
        exclude = exclude or set()
        candidates = [column for column in df.columns if column not in exclude and pd.api.types.is_numeric_dtype(df[column])]
        if not candidates:
            return ""

        question_tokens = self._question_tokens(question)

        def score(column: str) -> float:
            series = df[column]
            lowered = column.lower()
            unique_values = series.dropna().nunique()
            score_value = 0.0
            if any(keyword in lowered for keyword in MEASURE_KEYWORDS):
                score_value += 5
            if self._looks_identifier(column):
                score_value -= 8
            if unique_values <= 1:
                score_value -= 10
            elif unique_values > 12:
                score_value += 2
            elif unique_values <= 10 and pd.api.types.is_integer_dtype(series) and not any(keyword in lowered for keyword in MEASURE_KEYWORDS):
                score_value -= 4
            score_value += self._token_match_score(lowered, question_tokens)
            return score_value

        best = max(candidates, key=score)
        return best if score(best) > 0.5 else ""

    def _category_like_columns(self, df: pd.DataFrame) -> list[str]:
        columns: list[str] = []
        for column in df.columns:
            series = df[column]
            lowered = column.lower()
            unique_values = series.dropna().nunique()
            if unique_values <= 1:
                continue
            if pd.api.types.is_datetime64_any_dtype(series):
                columns.append(column)
                continue
            if pd.api.types.is_numeric_dtype(series):
                if any(keyword in lowered for keyword in MEASURE_KEYWORDS):
                    continue
                if unique_values <= 10 and pd.api.types.is_integer_dtype(series) and not self._looks_identifier(column):
                    columns.append(column)
                continue
            columns.append(column)
        return columns

    def _prefer_horizontal_bars(self, df: pd.DataFrame, category_col: str) -> bool:
        labels = [str(value) for value in df[category_col].head(8)]
        return len(labels) > 5 or any(len(label) > 12 for label in labels)

    def _is_datetime_column(self, df: pd.DataFrame, column: str) -> bool:
        return bool(column) and column in df.columns and pd.api.types.is_datetime64_any_dtype(df[column])

    def _looks_temporal(self, column: str) -> bool:
        lowered = column.lower()
        return any(keyword in lowered for keyword in TEMPORAL_KEYWORDS)

    def _looks_identifier(self, column: str) -> bool:
        lowered = column.lower()
        return any(keyword in lowered for keyword in IDENTIFIER_KEYWORDS)

    def _question_tokens(self, question: str) -> set[str]:
        return set(re.findall(r"[a-z]+", question.lower()))

    def _token_match_score(self, column_name: str, question_tokens: set[str]) -> float:
        if not question_tokens:
            return 0.0
        normalized = re.sub(r"[^a-z]+", "", column_name)
        score = 0.0
        for token in question_tokens:
            if token in column_name:
                score += 1.5
            elif token and token in normalized:
                score += 1.0
        return score

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
                FROM employees_current
            """,
            "by_department": """
                SELECT Department,
                    COUNT(*) as Total,
                    SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END) as Attrited,
                    ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1) as AttritionRate_pct
                FROM employees_current GROUP BY Department ORDER BY AttritionRate_pct DESC
            """,
            "by_job_role": """
                SELECT JobRole,
                    COUNT(*) as Total,
                    SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END) as Attrited,
                    ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1) as AttritionRate_pct
                FROM employees_current GROUP BY JobRole ORDER BY AttritionRate_pct DESC
            """,
            "by_demographics": """
                SELECT Gender, MaritalStatus,
                    COUNT(*) as Total,
                    ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1) as AttritionRate_pct
                FROM employees_current GROUP BY Gender, MaritalStatus ORDER BY AttritionRate_pct DESC
            """,
            "by_satisfaction": """
                SELECT JobSatisfaction, EnvironmentSatisfaction, WorkLifeBalance,
                    COUNT(*) as Total,
                    ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1) as AttritionRate_pct
                FROM employees_current
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
                FROM employees_current
                GROUP BY IncomeBand ORDER BY AttritionRate_pct DESC
            """,
            "top_risk_factors": """
                SELECT
                    'OverTime=Yes' as RiskFactor,
                    COUNT(*) as AffectedEmployees,
                    ROUND(100.0*SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END)/COUNT(*),1) as AttritionRate_pct
                FROM employees_current WHERE OverTime='Yes'
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
                FROM employees_current
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
                FROM employees_current
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
