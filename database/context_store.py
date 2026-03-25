from __future__ import annotations

import json
import logging
import sqlite3
import re
from datetime import datetime, timedelta, timezone

from config import CONTEXT_DB_PATH, MEMORY_RETENTION_DAYS
from database.schema import HR_SCHEMA

logger = logging.getLogger("hr_platform.context")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokenize(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 2]


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
        try:
            with self._get_connection() as conn:
                # Enforce retention policy: delete old memories
                cutoff = (
                    datetime.now(timezone.utc) - timedelta(days=MEMORY_RETENTION_DAYS)
                ).isoformat()
                conn.execute(
                    "DELETE FROM conversation_memory WHERE created_at < ?",
                    (cutoff,),
                )
                cursor = conn.execute(
                    """
                    INSERT INTO conversation_memory (user_email, question, response, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_email, question, response, _utc_now()),
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
                SELECT id, question, response, created_at, feedback_score
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
            }
            for row in rows
        ]

    def recent_questions(self, user_email: str, limit: int = 20) -> list[dict]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, question, created_at, feedback_score
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
                "created_at": row["created_at"],
                "feedback_score": row["feedback_score"],
            }
            for row in rows
        ]

    def search_memories(
        self,
        user_email: str,
        query: str,
        limit: int = 5,
        min_feedback: int | None = None,
        exclude_memory_ids: set[int] | None = None,
    ) -> list[dict]:
        tokens = _tokenize(query)
        exclude_memory_ids = exclude_memory_ids or set()

        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, question, response, created_at, feedback_score
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

            score = 0.0
            if not tokens:
                score = 1.0
            else:
                score += 4 * sum(token in question_lower for token in tokens)
                score += 2 * sum(token in response_lower for token in tokens)
                if normalized_query and normalized_query in question_lower:
                    score += 4
                if score <= 0:
                    continue

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
                    },
                )
            )

        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in scored[:limit]]

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
                    SELECT id, question, response, created_at, feedback_score
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
