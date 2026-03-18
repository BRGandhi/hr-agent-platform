from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from config import CONTEXT_DB_PATH
from database.schema import HR_SCHEMA


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ContextStore:
    def __init__(self, db_path: str = CONTEXT_DB_PATH):
        self.db_path = db_path
        self._initialize()

    def _connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self):
        with self._connection() as conn:
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

        with self._connection() as conn:
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
        with self._connection() as conn:
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

    def list_documents(self) -> list[dict]:
        with self._connection() as conn:
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

    def remember(self, user_email: str, question: str, response: str):
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO conversation_memory (user_email, question, response, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_email, question, response, _utc_now()),
            )
            conn.commit()

    def recent_memory(self, user_email: str, limit: int = 5) -> list[dict]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT question, response, created_at
                FROM conversation_memory
                WHERE user_email = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_email, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_questions(self, user_email: str, limit: int = 8) -> list[dict]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT question, created_at
                FROM conversation_memory
                WHERE user_email = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_email, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def search_documents(self, query: str, allowed_tags: list[str], limit: int = 3) -> list[dict]:
        tokens = [token.lower() for token in query.split() if len(token) > 2]
        with self._connection() as conn:
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
