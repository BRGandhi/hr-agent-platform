from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass

from config import ACCESS_DB_PATH

logger = logging.getLogger("hr_platform.access")

HR_SCOPE_KEYWORDS = {
    "hr", "people", "employee", "employees", "headcount", "hc", "attrition", "turnover",
    "retention", "salary", "compensation", "pay", "income", "promotion", "tenure",
    "performance", "rating", "workforce", "manager", "team", "department", "hiring",
    "recruiting", "satisfaction", "engagement", "policy", "benefits", "leave", "overtime",
    "attriting", "attrited", "gender", "demographic", "women", "woman", "female", "male",
}

ACCESS_CAPABILITY_PHRASES = (
    "what can i ask",
    "what questions can i ask",
    "what kinds of questions can i ask",
    "what kind of questions can i ask",
    "what can you answer",
    "what can this platform answer",
    "what data can i access",
    "what data do i have access to",
    "tell me about the data that i can access",
    "tell me about the data i can access",
    "which data can i access",
    "what metrics can i request",
    "what metrics can i ask for",
    "which metrics can i request",
    "which metrics can i ask for",
    "which metrics do i have access to",
    "what measures can i request",
    "what measures can i ask for",
    "what reports can you generate",
    "what reports can i request",
    "what charts can you create",
    "what visuals can you create",
    "how can i use this platform",
    "how do i use this platform",
    "how do i ask",
    "how should i ask",
    "how do i request",
)

ACCESS_CAPABILITY_OBJECTS = {
    "data", "metric", "metrics", "measure", "measures", "report", "reports", "question", "questions",
    "chart", "charts", "visual", "visuals", "visualization", "visualizations", "schema", "column", "columns",
}

METRIC_KEYWORDS = {
    "headcount": {"headcount", "hc", "employee count", "how many", "total employees", "org size"},
    "attrition": {"attrition", "attriting", "attrited", "turnover", "retention", "left", "leavers", "overtime", "risk"},
    "compensation": {"salary", "compensation", "income", "pay", "bonus", "hike"},
    "performance": {"performance", "rating", "review"},
    "satisfaction": {"satisfaction", "engagement", "work-life", "environment", "relationship"},
    "tenure": {"tenure", "years", "promotion", "experience", "working years"},
    "demographics": {"gender", "age", "marital", "demographic", "education", "women", "woman", "men", "man", "female", "male"},
    "policy": {"policy", "policies", "benefits", "leave", "pto", "compliance", "handbook"},
}

METRIC_COLUMNS = {
    "compensation": {"MONTHLYINCOME", "HOURLYRATE", "DAILYRATE", "MONTHLYRATE", "PERCENTSALARYHIKE", "STOCKOPTIONLEVEL"},
    "performance": {"PERFORMANCERATING", "JOBINVOLVEMENT", "TRAININGTIMESLASTYEAR"},
    "satisfaction": {"JOBSATISFACTION", "ENVIRONMENTSATISFACTION", "WORKLIFEBALANCE", "RELATIONSHIPSATISFACTION"},
    "tenure": {"YEARSATCOMPANY", "YEARSINCURRENTROLE", "YEARSSINCELASTPROMOTION", "YEARSWITHCURRMANAGER", "TOTALWORKINGYEARS"},
    "demographics": {"AGE", "GENDER", "MARITALSTATUS", "EDUCATION", "EDUCATIONFIELD", "DISTANCEFROMHOME"},
    "policy": set(),
}


class AccessDeniedError(Exception):
    """Raised when a user has no access profile provisioned."""


@dataclass
class AccessProfile:
    email: str
    role: str
    scope_name: str
    allowed_departments: list[str]
    allowed_metrics: list[str]
    allowed_doc_tags: list[str]

    @property
    def full_access(self) -> bool:
        return "all" in self.allowed_metrics

    def summary(self) -> dict:
        return {
            "email": self.email,
            "role": self.role,
            "scope_name": self.scope_name,
            "allowed_departments": self.allowed_departments,
            "allowed_metrics": self.allowed_metrics,
            "allowed_doc_tags": self.allowed_doc_tags,
        }

    def departments_clause(self) -> str | None:
        """Return a SQL WHERE fragment for department filtering.

        NOTE: This is only used for display / non-parameterized contexts (e.g. logging).
        The actual DB queries use parameterized queries via connector.py.
        """
        if not self.allowed_departments:
            return None
        values = ", ".join(
            "'" + department.replace("'", "''") + "'"
            for department in self.allowed_departments
        )
        return f"Department IN ({values})"

    def requested_metrics_for_question(self, question: str) -> set[str]:
        """Extract requested metric domains from question using keyword matching.

        Uses word boundary awareness to reduce false positives
        (e.g. 'turnaround' won't trigger 'turnover').
        """
        lowered = question.lower()
        requested: set[str] = set()

        for metric, keywords in METRIC_KEYWORDS.items():
            for keyword in keywords:
                # Multi-word keywords: substring match (e.g. "employee count")
                # Single-word keywords: check word boundaries
                if " " in keyword:
                    if keyword in lowered:
                        requested.add(metric)
                        break
                else:
                    # Simple word-boundary check: keyword surrounded by non-alpha chars
                    idx = lowered.find(keyword)
                    while idx != -1:
                        before_ok = idx == 0 or not lowered[idx - 1].isalpha()
                        after_ok = (idx + len(keyword) >= len(lowered)) or not lowered[idx + len(keyword)].isalpha()
                        if before_ok and after_ok:
                            requested.add(metric)
                            break
                        idx = lowered.find(keyword, idx + 1)

        if not requested and any(keyword in lowered for keyword in HR_SCOPE_KEYWORDS):
            requested.add("headcount")
        return requested

    def is_access_capability_question(self, question: str) -> bool:
        normalized = " ".join((question or "").lower().split())
        if not normalized:
            return False

        if any(phrase in normalized for phrase in ACCESS_CAPABILITY_PHRASES):
            return True

        asks_access_envelope = (
            any(keyword in normalized for keyword in ("access", "allowed", "available", "supported"))
            and any(keyword in normalized for keyword in ACCESS_CAPABILITY_OBJECTS)
        )
        asks_platform_usage = (
            any(keyword in normalized for keyword in ("what", "which", "how"))
            and any(keyword in normalized for keyword in ("ask", "request", "use", "supported", "available"))
            and any(keyword in normalized for keyword in ("platform", "here", "data", "metric", "report", "question", "chart", "visual"))
        )
        asks_role_envelope = any(
            phrase in normalized
            for phrase in ("my role", "my access", "do i have access", "am i allowed", "what am i allowed")
        )
        return asks_access_envelope or asks_platform_usage or asks_role_envelope

    def is_hr_related_question(self, question: str) -> bool:
        lowered = question.lower()
        return (
            self.is_access_capability_question(question)
            or bool(self.requested_metrics_for_question(question))
            or any(keyword in lowered for keyword in HR_SCOPE_KEYWORDS)
        )

    def can_access_question(self, question: str) -> tuple[bool, str]:
        if not self.is_hr_related_question(question):
            return False, "This platform only supports HR insights, workforce analytics, HR policies, and related people-data questions."

        if self.is_access_capability_question(question):
            return True, ""

        requested = self.requested_metrics_for_question(question)
        if self.full_access or not requested:
            return True, ""

        unauthorized = sorted(metric for metric in requested if metric not in self.allowed_metrics)
        if unauthorized:
            return False, (
                f"Out of scope for your role. You currently have access to {', '.join(self.allowed_metrics)} data only."
            )
        return True, ""

    def is_sql_allowed(self, sql: str) -> tuple[bool, str]:
        if self.full_access:
            return True, ""

        upper = sql.upper()
        for metric, columns in METRIC_COLUMNS.items():
            if metric in self.allowed_metrics:
                continue
            if any(column in upper for column in columns):
                return False, f"This query touches {metric} data, which is outside your role-based access."
        return True, ""


class AccessControlStore:
    def __init__(self, db_path: str = ACCESS_DB_PATH):
        self.db_path = db_path
        self._initialize()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self):
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_access (
                    email TEXT PRIMARY KEY,
                    role TEXT NOT NULL,
                    scope_name TEXT NOT NULL,
                    allowed_departments TEXT NOT NULL,
                    allowed_metrics TEXT NOT NULL,
                    allowed_doc_tags TEXT NOT NULL
                )
                """
            )
            conn.commit()

        self._seed_defaults()

    def _seed_defaults(self):
        default_profiles = [
            {
                "email": "local@hr-intelligence.local",
                "role": "HR Admin",
                "scope_name": "Enterprise",
                "allowed_departments": [],
                "allowed_metrics": ["all"],
                "allowed_doc_tags": ["all"],
            },
            {
                "email": "demo.microsoft@hr-intelligence.local",
                "role": "Technology Manager",
                "scope_name": "Technology",
                "allowed_departments": ["Research & Development"],
                "allowed_metrics": ["headcount", "attrition"],
                "allowed_doc_tags": ["hr", "access", "policy"],
            },
            {
                "email": "demo.google@hr-intelligence.local",
                "role": "HR Business Partner",
                "scope_name": "Business Units",
                "allowed_departments": ["Research & Development", "Sales", "Human Resources"],
                "allowed_metrics": ["headcount", "attrition", "compensation", "satisfaction", "tenure", "demographics", "policy"],
                "allowed_doc_tags": ["all"],
            },
            {
                "email": "demo.okta@hr-intelligence.local",
                "role": "Policy Lead",
                "scope_name": "Enterprise Policy",
                "allowed_departments": [],
                "allowed_metrics": ["policy", "headcount", "attrition"],
                "allowed_doc_tags": ["policy", "access", "hr"],
            },
        ]

        with self._get_connection() as conn:
            for profile in default_profiles:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO user_access (
                        email, role, scope_name, allowed_departments, allowed_metrics, allowed_doc_tags
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile["email"],
                        profile["role"],
                        profile["scope_name"],
                        json.dumps(profile["allowed_departments"]),
                        json.dumps(profile["allowed_metrics"]),
                        json.dumps(profile["allowed_doc_tags"]),
                    ),
                )
            conn.commit()

    def get_profile(self, email: str) -> AccessProfile:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM user_access WHERE email = ?",
                (email,),
            ).fetchone()

        if row is None:
            logger.warning("No access profile found for user: %s — denying access", email)
            raise AccessDeniedError(
                f"No access profile provisioned for {email}. Contact your administrator."
            )

        return AccessProfile(
            email=row["email"],
            role=row["role"],
            scope_name=row["scope_name"],
            allowed_departments=json.loads(row["allowed_departments"]),
            allowed_metrics=json.loads(row["allowed_metrics"]),
            allowed_doc_tags=json.loads(row["allowed_doc_tags"]),
        )
