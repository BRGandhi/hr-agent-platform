from __future__ import annotations

import json
import logging
import sqlite3
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from config import CONTEXT_DB_PATH, MEMORY_RETENTION_DAYS
from database.access_control import METRIC_KEYWORDS
from database.schema import HR_SCHEMA

logger = logging.getLogger("hr_platform.context")

TOPIC_LABELS = {
    "headcount": "Headcount",
    "attrition": "Attrition rate",
    "compensation": "Compensation bands",
    "performance": "Performance ratings",
    "satisfaction": "Satisfaction pulse",
    "tenure": "Tenure mix",
    "demographics": "Demographic mix",
    "policy": "Access policy guidance",
}

KPI_METRICS = {
    "headcount",
    "attrition",
    "compensation",
    "performance",
    "satisfaction",
    "tenure",
    "demographics",
}
SUMMARY_SECTION_HINTS = (
    "key takeaways",
    "takeaways",
    "summary",
    "highlights",
    "insights",
    "main takeaways",
)
FOLLOW_UP_SUMMARY_PATTERNS = (
    re.compile(r"^would you like\b", re.IGNORECASE),
    re.compile(r"^do you want\b", re.IGNORECASE),
    re.compile(r"^let me know\b", re.IGNORECASE),
    re.compile(r"^if you'd like\b", re.IGNORECASE),
)
MEMORY_MATCH_STOPWORDS = {
    "business",
    "unit",
    "units",
    "department",
    "departments",
    "team",
    "teams",
    "employee",
    "employees",
    "roster",
    "breakdown",
    "what",
    "which",
    "show",
    "give",
    "tell",
    "current",
    "latest",
    "generate",
    "create",
    "build",
    "report",
    "view",
    "please",
    "scope",
    "scoped",
    "question",
    "questions",
    "analysis",
    "analyze",
    "summary",
    "summarize",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokenize(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 2]


def _meaningful_tokens(text: str) -> list[str]:
    tokens = _tokenize(text)
    filtered = [token for token in tokens if token not in MEMORY_MATCH_STOPWORDS]
    return filtered or tokens


def _keyword_in_text(text: str, keyword: str) -> bool:
    lowered = text.lower()
    normalized = keyword.lower()
    if " " in normalized:
        return normalized in lowered

    variants = [normalized]
    if len(normalized) > 3:
        if normalized.endswith("y"):
            variants.append(f"{normalized[:-1]}ies")
        elif not normalized.endswith("s"):
            variants.append(f"{normalized}s")

    for variant in variants:
        idx = lowered.find(variant)
        while idx != -1:
            before_ok = idx == 0 or not lowered[idx - 1].isalpha()
            after_ok = (idx + len(variant) >= len(lowered)) or not lowered[idx + len(variant)].isalpha()
            if before_ok and after_ok:
                return True
            idx = lowered.find(variant, idx + 1)
    return False


def _extract_metrics(text: str) -> set[str]:
    if not text:
        return set()

    inferred: set[str] = set()
    for metric, keywords in METRIC_KEYWORDS.items():
        if any(_keyword_in_text(text, keyword) for keyword in keywords):
            inferred.add(metric)
    return inferred


def _allowed_metrics_filter(allowed_metrics: list[str] | None) -> set[str] | None:
    if not allowed_metrics or "all" in allowed_metrics:
        return None
    return {metric for metric in allowed_metrics if metric in TOPIC_LABELS}


def _is_metric_scope_allowed(metrics: set[str], allowed_metrics: list[str] | None) -> bool:
    allowed = _allowed_metrics_filter(allowed_metrics)
    if allowed is None or not metrics:
        return True
    return metrics.issubset(allowed)


def _topic_labels(metrics: set[str], *, kpi_only: bool = False) -> list[str]:
    ordered = []
    for metric in TOPIC_LABELS:
        if metric not in metrics:
            continue
        if kpi_only and metric not in KPI_METRICS:
            continue
        ordered.append(TOPIC_LABELS[metric])
    return ordered


def _history_metrics(question: str, response: str = "", insight_summary: str = "") -> set[str]:
    question_metrics = _extract_metrics(str(question or ""))
    if question_metrics:
        return question_metrics

    summary_text = str(insight_summary or "").strip()
    if summary_text:
        summary_metrics = _extract_metrics(summary_text)
        if summary_metrics:
            return summary_metrics

    response_summary = _build_insight_summary(str(response or ""))
    if response_summary:
        response_summary_metrics = _extract_metrics(response_summary)
        if response_summary_metrics:
            return response_summary_metrics

    return _extract_metrics(str(response or ""))


def _memory_match_details(query: str, question: str, response: str) -> dict[str, float | int | bool]:
    query_text = str(query or "").strip()
    question_text = str(question or "").strip()
    response_text = str(response or "").strip()
    query_topics = _extract_metrics(query_text)
    memory_topics = _extract_metrics(f"{question_text} {response_text}")

    raw_query_tokens = set(_tokenize(query_text))
    raw_question_tokens = set(_tokenize(question_text))
    query_tokens = set(_meaningful_tokens(query_text))
    question_tokens = set(_meaningful_tokens(question_text))
    response_tokens = set(_meaningful_tokens(response_text))

    token_overlap = len(query_tokens.intersection(question_tokens))
    response_overlap = len(query_tokens.intersection(response_tokens))
    shared_raw_tokens = len(raw_query_tokens.intersection(raw_question_tokens))
    topic_overlap = len(query_topics.intersection(memory_topics))
    query_coverage = token_overlap / max(len(query_tokens), 1) if query_tokens else 0.0

    normalized_query = " ".join(_tokenize(query_text))
    normalized_question = " ".join(_tokenize(question_text))
    phrase_similarity = 0.0
    if normalized_query and normalized_question:
        phrase_similarity = SequenceMatcher(None, normalized_query, normalized_question).ratio()
    direct_phrase_match = bool(
        normalized_query
        and normalized_question
        and (normalized_query in normalized_question or normalized_question in normalized_query)
    )

    is_strong_match = False
    if direct_phrase_match and shared_raw_tokens >= 2:
        is_strong_match = True
    elif phrase_similarity >= 0.74 and shared_raw_tokens >= 2:
        is_strong_match = True
    elif query_topics:
        if topic_overlap >= 1 and token_overlap >= 2 and query_coverage >= 0.45:
            is_strong_match = True
        elif topic_overlap >= 1 and phrase_similarity >= 0.58 and shared_raw_tokens >= 2:
            is_strong_match = True
        elif topic_overlap >= 2:
            is_strong_match = True
    else:
        if token_overlap >= 3 and query_coverage >= 0.5:
            is_strong_match = True

    return {
        "is_strong_match": is_strong_match,
        "topic_overlap": topic_overlap,
        "token_overlap": token_overlap,
        "response_overlap": response_overlap,
        "shared_raw_tokens": shared_raw_tokens,
        "query_coverage": query_coverage,
        "phrase_similarity": phrase_similarity,
    }


def _strip_markdown(value: str) -> str:
    cleaned = re.sub(r"`([^`]+)`", r"\1", value or "")
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*([^*\n]+)\*", r"\1", cleaned)
    cleaned = re.sub(r"~~([^~]+)~~", r"\1", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", cleaned)
    return " ".join(cleaned.split())


def _clean_summary_line(value: str) -> str:
    cleaned = str(value or "").strip()
    cleaned = re.sub(r"^#{1,6}\s*", "", cleaned)
    cleaned = re.sub(r"^(?:[-*+]|\u2022)\s*", "", cleaned)
    cleaned = re.sub(r"^\d+[\.\)]\s*", "", cleaned)
    cleaned = cleaned.replace("|", " ")
    return _strip_markdown(cleaned).strip(" -:")


def _looks_like_heading(line: str) -> bool:
    normalized = _clean_summary_line(line).lower()
    return normalized in SUMMARY_SECTION_HINTS


def _should_skip_summary_line(line: str) -> bool:
    cleaned = _clean_summary_line(line)
    if not cleaned:
        return True
    return any(pattern.match(cleaned) for pattern in FOLLOW_UP_SUMMARY_PATTERNS)


def _summary_bullets_from_lines(lines: list[str], limit: int = 3) -> list[str]:
    bullets: list[str] = []
    for line in lines:
        cleaned = _clean_summary_line(line)
        if not cleaned or _should_skip_summary_line(cleaned):
            continue
        bullets.append(cleaned.rstrip(".") + ".")
        if len(bullets) >= limit:
            break
    return bullets


def _sentence_summary(text: str, limit: int = 3) -> list[str]:
    normalized = _strip_markdown(text.replace("\n", " "))
    parts = re.split(r"(?<=[.!?])\s+", normalized)
    bullets: list[str] = []
    for part in parts:
        cleaned = part.strip()
        if not cleaned or cleaned.endswith("?") or _should_skip_summary_line(cleaned):
            continue
        bullets.append(cleaned)
        if len(bullets) >= limit:
            break
    return bullets


def _build_insight_summary(response: str) -> str:
    if not str(response or "").strip():
        return ""

    lines = [line.rstrip() for line in str(response).replace("\r\n", "\n").split("\n")]

    for index, line in enumerate(lines):
        if not _looks_like_heading(line):
            continue
        section_lines: list[str] = []
        for candidate in lines[index + 1:]:
            stripped = candidate.strip()
            if not stripped:
                if section_lines:
                    break
                continue
            if re.match(r"^#{1,6}\s+", stripped) and section_lines:
                break
            if _looks_like_heading(stripped) and section_lines:
                break
            section_lines.append(stripped)
        bullets = _summary_bullets_from_lines(section_lines)
        if bullets:
            return "\n".join(f"- {bullet}" for bullet in bullets)

    inline_bullets = [
        line.strip()
        for line in lines
        if re.match(r"^(?:\s*(?:[-*+]|\u2022)\s+|\s*\d+[\.\)]\s+)", line or "")
    ]
    bullets = _summary_bullets_from_lines(inline_bullets)
    if bullets:
        return "\n".join(f"- {bullet}" for bullet in bullets)

    sentence_bullets = _sentence_summary(str(response))
    return "\n".join(f"- {bullet}" for bullet in sentence_bullets)


def _row_value(row: sqlite3.Row | dict, key: str, default=None):
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return default


def _row_insight_summary(row: sqlite3.Row | dict) -> str:
    summary = str(_row_value(row, "insight_summary") or "").strip()
    if summary:
        return summary
    return _build_insight_summary(str(_row_value(row, "response") or ""))


class ContextStore:
    def __init__(self, db_path: str = CONTEXT_DB_PATH):
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
                CREATE TABLE IF NOT EXISTS conversation_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_email TEXT NOT NULL,
                    question TEXT NOT NULL,
                    response TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(conn, "conversation_memory", "feedback_score", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "conversation_memory", "feedback_updated_at", "TEXT")
            self._ensure_column(conn, "conversation_memory", "insight_summary", "TEXT")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS context_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

        self._seed_documents()

    def _ensure_column(self, conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
        columns = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name in columns:
            return
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    def _seed_documents(self):
        seed_docs = [
            {
                "title": "HR Analytics Scope Policy",
                "content": (
                    "This platform only answers HR insights questions. If a user asks about software engineering, "
                    "general web browsing, trivia, personal advice, or unrelated tasks, the correct response is that "
                    "the request is out of scope."
                ),
                "tags": ["hr", "scope", "policy"],
            },
            {
                "title": "HR Data Access Policy",
                "content": (
                    "Managers and analysts must only access workforce metrics that are explicitly allowed by role. "
                    "Department filters must be applied before calculating headcount, attrition, and other metrics."
                ),
                "tags": ["hr", "access", "policy"],
            },
            {
                "title": "Metric Definitions",
                "content": (
                    "Headcount is the count of employees in scope. Attrition rate is attrited employees divided by total "
                    "employees in scope, multiplied by 100. Compensation metrics are based on MonthlyIncome and related pay fields."
                ),
                "tags": ["hr", "metrics", "calculations"],
            },
            {
                "title": "Database Schema Summary",
                "content": HR_SCHEMA,
                "tags": ["hr", "database", "schema"],
            },
        ]

        with self._get_connection() as conn:
            existing_titles = {
                row["title"]
                for row in conn.execute("SELECT title FROM context_documents").fetchall()
            }
            for doc in seed_docs:
                if doc["title"] in existing_titles:
                    continue
                conn.execute(
                    """
                    INSERT INTO context_documents (title, content, tags, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (doc["title"], doc["content"], json.dumps(doc["tags"]), _utc_now()),
                )
            conn.commit()

    def add_document(self, title: str, content: str, tags: list[str]) -> dict:
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO context_documents (title, content, tags, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (title, content, json.dumps(tags), _utc_now()),
                )
                conn.commit()
                doc_id = cursor.lastrowid
            return {"id": doc_id, "title": title, "tags": tags}
        except sqlite3.Error as exc:
            logger.error("Failed to add context document: %s", exc)
            raise

    def list_documents(self) -> list[dict]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT id, title, tags, created_at FROM context_documents ORDER BY created_at DESC"
            ).fetchall()
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "tags": json.loads(row["tags"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def remember(self, user_email: str, question: str, response: str) -> int | None:
        insight_summary = _build_insight_summary(response)
        try:
            with self._get_connection() as conn:
                # Enforce retention policy only when auto-cleanup is enabled.
                if MEMORY_RETENTION_DAYS > 0:
                    cutoff = (
                        datetime.now(timezone.utc) - timedelta(days=MEMORY_RETENTION_DAYS)
                    ).isoformat()
                    conn.execute(
                        "DELETE FROM conversation_memory WHERE created_at < ?",
                        (cutoff,),
                    )
                cursor = conn.execute(
                    """
                    INSERT INTO conversation_memory (user_email, question, response, created_at, insight_summary)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_email, question, response, _utc_now(), insight_summary),
                )
                conn.commit()
                return int(cursor.lastrowid)
        except sqlite3.Error as exc:
            logger.error("Failed to store conversation memory: %s", exc)
            return None

    def recent_memory(self, user_email: str, limit: int = 5) -> list[dict]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, question, response, created_at, feedback_score, insight_summary
                FROM conversation_memory
                WHERE user_email = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_email, limit),
            ).fetchall()
        return [
            {
                "memory_id": row["id"],
                "question": row["question"],
                "response": row["response"],
                "created_at": row["created_at"],
                "feedback_score": row["feedback_score"],
                "insight_summary": _row_insight_summary(row),
            }
            for row in rows
        ]

    def recent_questions(self, user_email: str, limit: int = 20) -> list[dict]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, question, response, created_at, feedback_score, insight_summary
                FROM conversation_memory
                WHERE user_email = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_email, limit),
            ).fetchall()
        return [
            {
                "memory_id": row["id"],
                "question": row["question"],
                "response": row["response"],
                "created_at": row["created_at"],
                "feedback_score": row["feedback_score"],
                "insight_summary": _row_insight_summary(row),
            }
            for row in rows
        ]

    def recent_questions_for_sidebar(
        self,
        user_email: str,
        limit: int = 8,
        allowed_metrics: list[str] | None = None,
    ) -> list[dict]:
        questions = self.recent_questions(user_email, limit=max(limit * 2, limit))
        items: list[dict] = []
        seen: set[str] = set()

        for item in questions:
            question = str(item.get("question", "") or "").strip()
            response = str(item.get("response", "") or "").strip()
            insight_summary = str(item.get("insight_summary") or "").strip()
            if not question:
                continue

            inferred_metrics = _history_metrics(question, response, insight_summary)
            if not _is_metric_scope_allowed(inferred_metrics, allowed_metrics):
                continue

            normalized = question.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            items.append(
                {
                    "memory_id": item.get("memory_id"),
                    "question": question,
                    "created_at": item.get("created_at"),
                    "feedback_score": item.get("feedback_score", 0),
                    "topics": _topic_labels(inferred_metrics),
                    "insight_summary": insight_summary,
                }
            )
            if len(items) >= limit:
                break

        return items

    def past_questions_for_sidebar(
        self,
        user_email: str,
        limit: int = 50,
        allowed_metrics: list[str] | None = None,
    ) -> list[dict]:
        questions = self.recent_questions(user_email, limit=max(limit, 1))
        items: list[dict] = []

        for item in questions:
            question = str(item.get("question", "") or "").strip()
            response = str(item.get("response", "") or "").strip()
            insight_summary = str(item.get("insight_summary") or "").strip()
            if not question:
                continue

            inferred_metrics = _history_metrics(question, response, insight_summary)
            if not _is_metric_scope_allowed(inferred_metrics, allowed_metrics):
                continue

            items.append(
                {
                    "memory_id": item.get("memory_id"),
                    "question": question,
                    "created_at": item.get("created_at"),
                    "feedback_score": item.get("feedback_score", 0),
                    "topics": _topic_labels(inferred_metrics),
                    "insight_summary": insight_summary,
                }
            )
            if len(items) >= limit:
                break

        return items

    def search_memories(
        self,
        user_email: str,
        query: str,
        limit: int = 5,
        min_feedback: int | None = None,
        exclude_memory_ids: set[int] | None = None,
        require_strong_match: bool = False,
    ) -> list[dict]:
        tokens = _tokenize(query)
        exclude_memory_ids = exclude_memory_ids or set()
        query_token_set = set(tokens)
        query_topics = _extract_metrics(query)

        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, question, response, created_at, feedback_score, insight_summary
                FROM conversation_memory
                WHERE user_email = ?
                ORDER BY id DESC
                """,
                (user_email,),
            ).fetchall()

        scored: list[tuple[float, str, dict]] = []
        normalized_query = " ".join(tokens)

        for row in rows:
            memory_id = int(row["id"])
            if memory_id in exclude_memory_ids:
                continue

            feedback_score = int(row["feedback_score"] or 0)
            if min_feedback is not None and feedback_score < min_feedback:
                continue
            if min_feedback is None and feedback_score < 0:
                continue

            question_text = row["question"] or ""
            response_text = row["response"] or ""
            question_lower = question_text.lower()
            response_lower = response_text.lower()
            question_tokens = set(_tokenize(question_text))
            response_tokens = set(_tokenize(response_text))
            memory_topics = _extract_metrics(f"{question_text} {response_text}")
            match_details = _memory_match_details(query, question_text, response_text)
            if require_strong_match and not bool(match_details["is_strong_match"]):
                continue

            score = 0.0
            if not tokens and not query_topics:
                score = 1.0
            else:
                score += 4 * sum(token in question_lower for token in tokens)
                score += 2 * sum(token in response_lower for token in tokens)
                score += 2.5 * len(query_token_set.intersection(question_tokens))
                score += 1.5 * len(query_token_set.intersection(response_tokens))
                if normalized_query and normalized_query in question_lower:
                    score += 4
                if query_topics:
                    topic_overlap = len(query_topics.intersection(memory_topics))
                    score += 6 * topic_overlap
                if score <= 0:
                    continue
            score += 8 * float(match_details["phrase_similarity"])
            score += 4 * float(match_details["query_coverage"])
            if bool(match_details["is_strong_match"]):
                score += 6

            if feedback_score > 0:
                score += 3 * feedback_score

            scored.append(
                (
                    score,
                    row["created_at"],
                    {
                        "memory_id": memory_id,
                        "question": question_text,
                        "response": response_text,
                        "created_at": row["created_at"],
                        "feedback_score": feedback_score,
                        "insight_summary": _row_insight_summary(row),
                        "is_strong_match": bool(match_details["is_strong_match"]),
                    },
                )
            )

        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in scored[:limit]]

    def relevant_questions(
        self,
        user_email: str,
        query: str,
        limit: int = 8,
        allowed_metrics: list[str] | None = None,
    ) -> list[dict]:
        if not str(query or "").strip():
            return []

        deduped: list[dict] = []
        seen: set[str] = set()
        for item in self.search_memories(
            user_email,
            query,
            limit=max(limit * 3, 12),
            require_strong_match=True,
        ):
            question = item.get("question", "")
            response = item.get("response", "")
            insight_summary = str(item.get("insight_summary") or "").strip()
            inferred_metrics = _history_metrics(question, response, insight_summary)
            if not _is_metric_scope_allowed(inferred_metrics, allowed_metrics):
                continue

            normalized = question.strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(
                {
                    "memory_id": item.get("memory_id"),
                    "question": question,
                    "created_at": item.get("created_at"),
                    "feedback_score": item.get("feedback_score", 0),
                    "topics": _topic_labels(inferred_metrics),
                    "insight_summary": insight_summary,
                }
            )
            if len(deduped) >= limit:
                break
        return deduped

    def history_summary(
        self,
        user_email: str,
        allowed_metrics: list[str] | None = None,
        limit: int = 40,
    ) -> dict:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, question, response, created_at, feedback_score, insight_summary
                FROM conversation_memory
                WHERE user_email = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_email, limit),
            ).fetchall()

        total_rows = len(rows)
        topic_scores: dict[str, float] = {}
        favorite_questions: list[tuple[float, str, dict]] = []
        seen_questions: set[str] = set()

        for index, row in enumerate(rows):
            question = row["question"] or ""
            response = row["response"] or ""
            feedback_score = int(row["feedback_score"] or 0)
            insight_summary = _row_insight_summary(row)
            inferred_metrics = _history_metrics(question, response, insight_summary)
            if not _is_metric_scope_allowed(inferred_metrics, allowed_metrics):
                continue

            recency_weight = 1.4 - (index / max(total_rows, 1))
            score = max(recency_weight, 0.35)
            if feedback_score > 0:
                score += 0.9 * feedback_score
            elif feedback_score < 0:
                score = max(0.1, score + (0.35 * feedback_score))

            for metric in inferred_metrics:
                topic_scores[metric] = topic_scores.get(metric, 0.0) + score

            normalized_question = question.strip().lower()
            if normalized_question and normalized_question not in seen_questions:
                seen_questions.add(normalized_question)
                favorite_questions.append(
                    (
                        score + (0.15 * len(inferred_metrics)),
                        row["created_at"],
                        {
                            "memory_id": row["id"],
                            "question": question,
                            "created_at": row["created_at"],
                            "feedback_score": feedback_score,
                            "topics": _topic_labels(inferred_metrics),
                            "insight_summary": insight_summary,
                        },
                    )
                )

        ranked_topics = sorted(topic_scores.items(), key=lambda item: item[1], reverse=True)
        favorite_topics = [
            {"metric": metric, "topic": TOPIC_LABELS[metric], "score": round(score, 2)}
            for metric, score in ranked_topics[:4]
        ]
        favorite_kpis = [
            {"metric": metric, "topic": TOPIC_LABELS[metric], "score": round(score, 2)}
            for metric, score in ranked_topics
            if metric in KPI_METRICS
        ][:4]

        favorite_questions.sort(key=lambda item: (item[0], item[1]), reverse=True)
        ranked_questions = [item[2] for item in favorite_questions[:5]]

        if not favorite_topics:
            allowed = _allowed_metrics_filter(allowed_metrics)
            fallback_metrics = list(allowed or TOPIC_LABELS.keys())
            favorite_topics = [
                {"metric": metric, "topic": TOPIC_LABELS[metric], "score": 0.0}
                for metric in fallback_metrics[:4]
                if metric in TOPIC_LABELS
            ]

        if not favorite_kpis:
            allowed = _allowed_metrics_filter(allowed_metrics)
            fallback_metrics = [metric for metric in (allowed or TOPIC_LABELS.keys()) if metric in KPI_METRICS]
            favorite_kpis = [
                {"metric": metric, "topic": TOPIC_LABELS[metric], "score": 0.0}
                for metric in fallback_metrics[:4]
            ]

        return {
            "favorite_topics": favorite_topics,
            "favorite_kpis": favorite_kpis,
            "favorite_questions": ranked_questions,
        }

    def get_memory(
        self,
        user_email: str,
        memory_id: int,
        allowed_metrics: list[str] | None = None,
    ) -> dict | None:
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT id, question, response, created_at, feedback_score, insight_summary
                FROM conversation_memory
                WHERE id = ? AND user_email = ?
                """,
                (memory_id, user_email),
            ).fetchone()
            if row is None:
                return None

            question = str(row["question"] or "").strip()
            response = str(row["response"] or "").strip()
            insight_summary = _row_insight_summary(row)
            inferred_metrics = _history_metrics(question, response, insight_summary)
            if not _is_metric_scope_allowed(inferred_metrics, allowed_metrics):
                return None

            if insight_summary and not str(row["insight_summary"] or "").strip():
                conn.execute(
                    """
                    UPDATE conversation_memory
                    SET insight_summary = ?
                    WHERE id = ? AND user_email = ?
                    """,
                    (insight_summary, memory_id, user_email),
                )
                conn.commit()

        return {
            "memory_id": row["id"],
            "question": question,
            "response": response,
            "created_at": row["created_at"],
            "feedback_score": int(row["feedback_score"] or 0),
            "topics": _topic_labels(inferred_metrics),
            "insight_summary": insight_summary,
        }

    def record_feedback(self, user_email: str, memory_id: int, vote: str) -> dict | None:
        normalized_vote = str(vote or "").strip().lower()
        feedback_score = 1 if normalized_vote in {"up", "yes"} else -1 if normalized_vote in {"down", "no"} else 0
        if feedback_score == 0:
            raise ValueError("Feedback vote must be 'yes'/'no' or 'up'/'down'.")

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    UPDATE conversation_memory
                    SET feedback_score = ?, feedback_updated_at = ?
                    WHERE id = ? AND user_email = ?
                    """,
                    (feedback_score, _utc_now(), memory_id, user_email),
                )
                if cursor.rowcount == 0:
                    return None

                row = conn.execute(
                    """
                    SELECT id, question, response, created_at, feedback_score, insight_summary
                    FROM conversation_memory
                    WHERE id = ? AND user_email = ?
                    """,
                    (memory_id, user_email),
                ).fetchone()
                conn.commit()
        except sqlite3.Error as exc:
            logger.error("Failed to record conversation feedback: %s", exc)
            raise

        if row is None:
            return None

        return {
            "memory_id": row["id"],
            "question": row["question"],
            "response": row["response"],
            "created_at": row["created_at"],
            "feedback_score": row["feedback_score"],
            "insight_summary": _row_insight_summary(row),
        }

    def search_documents(self, query: str, allowed_tags: list[str], limit: int = 3) -> list[dict]:
        tokens = _tokenize(query)
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT title, content, tags, created_at FROM context_documents"
            ).fetchall()

        allowed_all = "all" in allowed_tags
        scored: list[tuple[int, dict]] = []

        for row in rows:
            tags = json.loads(row["tags"])
            if not allowed_all and not set(tags).intersection(allowed_tags):
                continue

            haystack = f"{row['title']} {row['content']}".lower()
            score = sum(token in haystack for token in tokens)
            if score > 0 or not tokens:
                scored.append(
                    (
                        score,
                        {
                            "title": row["title"],
                            "content": row["content"][:800],
                            "tags": tags,
                            "created_at": row["created_at"],
                        },
                    )
                )

        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:limit]]
