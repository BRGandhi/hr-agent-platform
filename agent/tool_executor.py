"""
Tool executor: bridges model tool requests to actual Python/SQL operations.
"""

from __future__ import annotations

import json
import logging
import re

import pandas as pd
import plotly.express as px

from database.access_control import AccessProfile
from database.connector import HRDatabase
from utils.safety import validate_sql

logger = logging.getLogger("hr_platform.tools")

# Chart color palette
CHART_PALETTE = ["#0050A0", "#2D6FA3", "#4D8FD1", "#F59E0B", "#D22630", "#6D839B"]
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


class ToolExecutor:
    def __init__(self, db: HRDatabase):
        self.db = db

    def execute(
        self,
        tool_name: str,
        tool_input: dict,
        access_profile: AccessProfile | None = None,
        table_context: dict | None = None,
    ) -> str:
        try:
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

        rows, resolved_title_or_error = self._resolve_visualization_rows(inputs, table_context)
        if rows is None:
            return json.dumps({"error": resolved_title_or_error})

        df = self._prepare_visualization_dataframe(rows)

        if not x_col and chart_type == "histogram":
            x_col = self._choose_metric_column(df, "")
        elif not x_col:
            x_col = self._choose_dimension_column(df, "")

        if not y_col and chart_type in {"bar", "horizontal_bar", "stacked_bar", "pie", "donut", "line", "area", "box"}:
            y_col = self._choose_metric_column(df, "")

        if not x_col and chart_type not in {"scatter"}:
            return json.dumps({"error": "Visualization requires a valid x column or the latest table context."})
        if chart_type not in {"histogram", "pie", "donut"} and chart_type not in {"scatter"} and not y_col:
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
        ) -> None:
            if len(options) >= max_options:
                return
            if chart_df.empty or x_col not in chart_df.columns or y_col not in chart_df.columns:
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
                    "id": f"option_{len(options) + 1}",
                    "chart_type": chart_type,
                    "title": title,
                    "reason": reason,
                    "chart_json": fig.to_json(),
                }
            )

        primary_dimension = self._choose_dimension_column(df, question)
        secondary_dimension = self._choose_dimension_column(df, question, exclude={primary_dimension} if primary_dimension else None)
        primary_metric = self._choose_metric_column(df, question)
        secondary_metric = self._choose_metric_column(df, question, exclude={primary_metric} if primary_metric else None)

        if primary_dimension and primary_metric:
            chart_df = self._prepare_category_metric_frame(df, primary_dimension, primary_metric)
            if self._is_datetime_column(chart_df, primary_dimension):
                add_option(
                    "line",
                    chart_df,
                    primary_dimension,
                    primary_metric,
                    f"{primary_metric} over {primary_dimension}",
                    "Best for seeing how the metric moves across an ordered timeline.",
                )
                add_option(
                    "area",
                    chart_df,
                    primary_dimension,
                    primary_metric,
                    f"Cumulative view of {primary_metric} over {primary_dimension}",
                    "Adds more visual weight when the overall magnitude matters as much as the trend.",
                )
            else:
                preferred_chart = "horizontal_bar" if self._prefer_horizontal_bars(chart_df, primary_dimension) else "bar"
                add_option(
                    preferred_chart,
                    chart_df,
                    primary_dimension,
                    primary_metric,
                    f"{primary_metric} by {primary_dimension}",
                    "Best for comparing categories quickly and making the ranking immediately obvious.",
                )
                add_option(
                    "bar" if preferred_chart == "horizontal_bar" else "horizontal_bar",
                    chart_df,
                    primary_dimension,
                    primary_metric,
                    f"{primary_metric} by {primary_dimension}",
                    "A strong alternative when you want the same comparison in a different visual orientation.",
                )

                if secondary_dimension:
                    stacked_df = self._prepare_stacked_frame(df, primary_dimension, secondary_dimension, primary_metric)
                    if not stacked_df.empty:
                        add_option(
                            "stacked_bar",
                            stacked_df,
                            primary_dimension,
                            primary_metric,
                            f"{primary_metric} by {primary_dimension} split by {secondary_dimension}",
                            "Useful when you want both the total and the composition of each category in one view.",
                            color_col=secondary_dimension,
                        )

                unique_categories = chart_df[primary_dimension].nunique(dropna=True)
                if 2 <= unique_categories <= 7:
                    add_option(
                        "donut",
                        chart_df,
                        primary_dimension,
                        primary_metric,
                        f"Share of {primary_metric} by {primary_dimension}",
                        "Works well for a small set of categories when relative share is the main story.",
                    )
        elif primary_metric and secondary_metric:
            scatter_df = self._limit_rows(df[[primary_metric, secondary_metric]].dropna(), max_rows=250)
            add_option(
                "scatter",
                scatter_df,
                primary_metric,
                secondary_metric,
                f"{secondary_metric} vs {primary_metric}",
                "Best for checking the relationship and spread between two numeric measures.",
            )
            add_option(
                "histogram",
                df[[primary_metric]].dropna(),
                primary_metric,
                primary_metric,
                f"Distribution of {primary_metric}",
                "Helps show concentration, skew, and outliers in a single metric.",
            )
        elif primary_metric:
            add_option(
                "histogram",
                df[[primary_metric]].dropna(),
                primary_metric,
                primary_metric,
                f"Distribution of {primary_metric}",
                "Shows whether values cluster tightly or spread widely across the workforce.",
            )
            if primary_dimension:
                add_option(
                    "box",
                    self._build_box_frame(df, primary_dimension, primary_metric),
                    primary_dimension,
                    primary_metric,
                    f"{primary_metric} spread by {primary_dimension}",
                    "Strong choice when you need category-level spread rather than just averages.",
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
                    f"Employee count by {count_dimension}",
                    "Best baseline view for roster-style tables because it turns rows into an immediately readable ranking.",
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
                        f"Employee mix by {share_dimension}",
                        "Useful for showing the overall composition of the table rather than the rank order.",
                    )

                if secondary_dimension and secondary_dimension != count_dimension:
                    secondary_df = self._aggregate_counts(df, secondary_dimension, count_metric)
                    add_option(
                        "bar",
                        secondary_df,
                        secondary_dimension,
                        count_metric,
                        f"Employee count by {secondary_dimension}",
                        "Offers a second lens on the same roster so the user can compare different breakdowns.",
                    )

        if not options:
            return json.dumps({"error": "The current table does not contain enough structure to suggest a visualization."})

        return json.dumps(
            {
                "title": f"Visualization options for {source_title}",
                "source_title": source_title,
                "recommended_option_id": options[0]["id"],
                "options": options,
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
        if chart_type not in {"histogram", "pie", "donut"} and y_col and y_col not in df.columns:
            raise ValueError(f"Column '{y_col}' is not available in the table.")
        if chart_type == "histogram" and x_col not in df.columns:
            raise ValueError("Histogram requires a valid x column.")
        if chart_type in {"pie", "donut"} and (x_col not in df.columns or y_col not in df.columns):
            raise ValueError("Pie and donut charts require both a category column and a value column.")
        if chart_type == "scatter" and (x_col not in df.columns or y_col not in df.columns):
            raise ValueError("Scatter plots require two numeric columns.")
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
        else:
            raise ValueError(f"Unsupported chart type '{chart_type}'.")

        self._style_figure(fig, chart_type)
        return fig

    def _style_figure(self, fig, chart_type: str) -> None:
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
        fig.update_traces(opacity=0.92, selector=dict(type="histogram"))
        fig.update_traces(line=dict(width=3), marker=dict(size=8), selector=dict(type="scatter"))

        if chart_type in {"line", "area"}:
            fig.update_layout(hovermode="x unified")
        if chart_type in {"pie", "donut"}:
            fig.update_traces(textposition="inside", textinfo="percent+label")
            fig.update_layout(showlegend=True)

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
