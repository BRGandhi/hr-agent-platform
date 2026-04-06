import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from database.context_store import ContextStore


class ContextStorePersonalizationTests(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        self.store = ContextStore(db_path=self.db_path)
        self.user_email = "tester@hr-intelligence.local"

    def tearDown(self):
        del self.store
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except PermissionError:
                pass

    def test_relevant_questions_prefers_matching_metric_domain(self):
        self.store.remember(
            self.user_email,
            "What is the headcount for Research & Development?",
            "The current headcount is 430 employees.",
        )
        self.store.remember(
            self.user_email,
            "Which teams have the highest attrition risk in Sales?",
            "Sales leadership and field teams have the highest attrition risk.",
        )

        results = self.store.relevant_questions(
            self.user_email,
            "Show attrition risk by team for my scope",
            allowed_metrics=["headcount", "attrition"],
        )

        self.assertGreaterEqual(len(results), 1)
        self.assertIn("attrition", results[0]["question"].lower())
        self.assertIn("Attrition rate", results[0]["topics"])

    def test_history_summary_filters_disallowed_topics(self):
        self.store.remember(
            self.user_email,
            "What is the attrition rate for my scope?",
            "The attrition rate is 16.1%.",
        )
        self.store.remember(
            self.user_email,
            "Which HR access policy applies to my role?",
            "Your role follows the HR analytics access policy.",
        )
        self.store.remember(
            self.user_email,
            "What is the headcount for my scope?",
            "Your scoped headcount is 1,470 employees.",
        )

        summary = self.store.history_summary(
            self.user_email,
            allowed_metrics=["headcount", "attrition"],
        )

        favorite_topics = [item["topic"] for item in summary["favorite_topics"]]
        favorite_questions = [item["question"] for item in summary["favorite_questions"]]

        self.assertIn("Headcount", favorite_topics)
        self.assertIn("Attrition rate", favorite_topics)
        self.assertNotIn("Access policy guidance", favorite_topics)
        self.assertTrue(any("headcount" in question.lower() for question in favorite_questions))
        self.assertTrue(any("attrition" in question.lower() for question in favorite_questions))
        self.assertFalse(any("policy" in question.lower() for question in favorite_questions))

    def test_relevant_questions_require_close_question_match(self):
        self.store.remember(
            self.user_email,
            "Show headcount by department for Business Units",
            "Research & Development has the largest department headcount.",
        )

        results = self.store.relevant_questions(
            self.user_email,
            "Which job roles have the highest headcount in Business Units?",
            allowed_metrics=["headcount", "attrition"],
        )

        self.assertEqual(results, [])

    def test_search_memories_can_require_strong_match(self):
        self.store.remember(
            self.user_email,
            "What is the current headcount for Business Units?",
            "The scoped headcount is 1,470 employees.",
        )

        results = self.store.search_memories(
            self.user_email,
            "Show the current headcount for Business Units",
            require_strong_match=True,
        )

        self.assertEqual(len(results), 1)
        self.assertIn("headcount", results[0]["question"].lower())

    def test_past_questions_for_sidebar_preserves_full_recent_history(self):
        self.store.remember(
            self.user_email,
            "What is the current headcount for Business Units?",
            "The scoped headcount is 1,470 employees.",
        )
        self.store.remember(
            self.user_email,
            "What is the current headcount for Business Units?",
            "The scoped headcount is 1,470 employees.",
        )
        self.store.remember(
            self.user_email,
            "Generate an active headcount report for Business Units",
            "There are 1,233 active employees in scope.",
        )

        results = self.store.past_questions_for_sidebar(
            self.user_email,
            limit=10,
            allowed_metrics=["headcount", "attrition"],
        )

        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]["question"], "Generate an active headcount report for Business Units")
        self.assertEqual(results[1]["question"], "What is the current headcount for Business Units?")
        self.assertEqual(results[2]["question"], "What is the current headcount for Business Units?")

    def test_sidebar_topics_prefer_question_topic_over_response_mentions(self):
        self.store.remember(
            self.user_email,
            "Generate an attrition report for Business Units",
            (
                "Attrition is 16.1% across the business units.\n"
                "The current headcount is 1,470 and active headcount is 1,233."
            ),
        )

        results = self.store.past_questions_for_sidebar(
            self.user_email,
            limit=10,
            allowed_metrics=["headcount", "attrition"],
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["topics"], ["Attrition rate"])

    def test_history_summary_topics_prefer_question_topic_over_response_mentions(self):
        self.store.remember(
            self.user_email,
            "Can you overlay the demographic information on this breakdown?",
            (
                "Here is the demographic mix.\n"
                "The underlying headcount remains 1,470 employees."
            ),
        )

        summary = self.store.history_summary(
            self.user_email,
            allowed_metrics=["headcount", "demographics"],
        )

        self.assertEqual(summary["favorite_questions"][0]["topics"], ["Demographic mix"])

    def test_sidebar_topics_match_plural_question_terms_before_summary_fallback(self):
        self.store.remember(
            self.user_email,
            "Show employees with recent promotions in Business Units",
            "Attrition is 16.1%, but this answer is mainly about promotion activity.",
        )

        results = self.store.past_questions_for_sidebar(
            self.user_email,
            limit=10,
            allowed_metrics=["attrition", "tenure"],
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["topics"], ["Tenure mix"])

    def test_remember_does_not_purge_when_retention_is_disabled(self):
        with self.store._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO conversation_memory (user_email, question, response, created_at, insight_summary)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    self.user_email,
                    "Historic attrition review",
                    "Older saved response.",
                    "2020-01-01T00:00:00+00:00",
                    "- Older saved response.",
                ),
            )
            conn.commit()

        with patch("database.context_store.MEMORY_RETENTION_DAYS", 0):
            self.store.remember(
                self.user_email,
                "Current headcount snapshot",
                "The scoped headcount is 1,470 employees.",
            )

        with self.store._get_connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM conversation_memory WHERE user_email = ?",
                (self.user_email,),
            ).fetchone()[0]

        self.assertEqual(count, 2)

    def test_get_memory_derives_summary_for_legacy_rows(self):
        with self.store._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO conversation_memory (user_email, question, response, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    self.user_email,
                    "What is the headcount for Business Units?",
                    (
                        "Key Takeaways\n"
                        "- Research & Development is the largest unit.\n"
                        "- Sales is the second-largest unit.\n"
                        "- Human Resources is the smallest unit."
                    ),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            memory_id = int(cursor.lastrowid)
            conn.commit()

        memory = self.store.get_memory(
            self.user_email,
            memory_id,
            allowed_metrics=["headcount", "attrition"],
        )

        self.assertIsNotNone(memory)
        self.assertIn("Research & Development is the largest unit.", memory["insight_summary"])
        self.assertIn("Sales is the second-largest unit.", memory["insight_summary"])

    def test_memory_summary_skips_follow_up_question_section(self):
        memory_id = self.store.remember(
            self.user_email,
            "What is the headcount for Business Units?",
            (
                "The current headcount for Business Units is 1,470 employees.\n\n"
                "### Follow-up questions\n"
                "- Can you break headcount down by department in Business Units?\n"
                "- Which employee job roles have the highest headcount in Business Units?"
            ),
        )

        memory = self.store.get_memory(
            self.user_email,
            memory_id,
            allowed_metrics=["headcount", "attrition"],
        )

        self.assertIsNotNone(memory)
        self.assertIn("The current headcount for Business Units is 1,470 employees.", memory["insight_summary"])
        self.assertNotIn("Can you break headcount down by department", memory["insight_summary"])
        self.assertNotIn("Which employee job roles have the highest headcount", memory["insight_summary"])


if __name__ == "__main__":
    unittest.main()
