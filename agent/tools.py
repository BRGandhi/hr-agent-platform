"""
Tool JSON schemas passed to Claude.
These tell Claude what tools it can call and what parameters to use.
"""

TOOLS = [
    {
        "name": "query_hr_database",
        "description": (
            "Run a read-only SQL SELECT query against the HR employees database. "
            "Use this for ANY question involving employee counts, headcount, demographics, "
            "attrition rates, salaries, job roles, departments, satisfaction scores, "
            "tenure, promotions, performance ratings, or any other structured HR data. "
            "Always use SELECT statements only. The full database schema is in your system prompt."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql_query": {
                    "type": "string",
                    "description": "A SQL SELECT query to run against the employees table",
                },
                "explanation": {
                    "type": "string",
                    "description": "Brief explanation of what this query retrieves and why",
                },
            },
            "required": ["sql_query", "explanation"],
        },
    },
    {
        "name": "calculate_metrics",
        "description": (
            "Compute derived HR metrics and statistics on data already retrieved from the database. "
            "Use this when you need to calculate attrition rates, percentage distributions, "
            "averages, ratios, tenure statistics, salary bands, correlation analysis, "
            "year-over-year comparisons, or any derived metric that goes beyond what SQL returns. "
            "Pass the raw query results as JSON data along with the operation to perform."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "data": {
                    "type": "string",
                    "description": "JSON string of the data to analyze (from a previous query_hr_database call)",
                },
                "operation": {
                    "type": "string",
                    "description": (
                        "Description of the calculation to perform. Examples: "
                        "'calculate attrition rate per group', "
                        "'compute percentage breakdown', "
                        "'find top N by value', "
                        "'compute summary statistics', "
                        "'rank departments by metric'"
                    ),
                },
            },
            "required": ["data", "operation"],
        },
    },
    {
        "name": "create_visualization",
        "description": (
            "Generate a Plotly chart specification from HR data. "
            "Use this when the user asks for a chart, graph, visualization, or plot. "
            "Supported chart types: bar, horizontal_bar, pie, histogram, scatter, line, box. "
            "Returns a chart spec that Streamlit will render automatically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "chart_type": {
                    "type": "string",
                    "enum": ["bar", "horizontal_bar", "pie", "histogram", "scatter", "line", "box"],
                    "description": "Type of chart to create",
                },
                "data": {
                    "type": "string",
                    "description": "JSON string of the data rows to plot",
                },
                "x_column": {
                    "type": "string",
                    "description": "Column name to use for X-axis (or categories for pie/bar)",
                },
                "y_column": {
                    "type": "string",
                    "description": "Column name to use for Y-axis (or values for pie/bar)",
                },
                "title": {
                    "type": "string",
                    "description": "Chart title",
                },
                "color_column": {
                    "type": "string",
                    "description": "Optional: column to use for color grouping",
                },
            },
            "required": ["chart_type", "data", "x_column", "y_column", "title"],
        },
    },
    {
        "name": "get_attrition_insights",
        "description": (
            "Perform a comprehensive attrition risk analysis across the entire workforce. "
            "Use this when the user asks about: attrition risk factors, which employees might leave, "
            "top drivers of attrition, at-risk groups, or wants an overall attrition summary. "
            "Returns a structured analysis with key risk indicators and affected groups."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "focus_area": {
                    "type": "string",
                    "enum": [
                        "overall_summary",
                        "by_department",
                        "by_job_role",
                        "by_demographics",
                        "by_satisfaction",
                        "by_compensation",
                        "top_risk_factors",
                    ],
                    "description": "Which aspect of attrition to analyze",
                }
            },
            "required": ["focus_area"],
        },
    },
]
